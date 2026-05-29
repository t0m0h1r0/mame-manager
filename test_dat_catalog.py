from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from mame_manager.dat_catalog import DatIndex


def write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def main() -> int:
    arcade = """<?xml version="1.0"?>
<mame>
  <machine name="bios" isbios="yes">
    <rom name="bios.bin" size="1" crc="11111111" />
  </machine>
  <machine name="parent">
    <rom name="parent.bin" size="2" crc="22222222" />
  </machine>
  <machine name="clone" cloneof="parent">
    <rom name="parent.bin" merge="parent.bin" size="2" crc="22222222" />
    <rom name="clone.bin" size="3" crc="33333333" />
  </machine>
  <machine name="biosgame" romof="bios">
    <rom name="bios.bin" merge="bios.bin" size="1" crc="11111111" />
    <rom name="game.bin" size="4" crc="44444444" />
  </machine>
  <machine name="continued">
    <rom name="continued.bin" size="2" crc="77777777" />
    <rom size="3" loadflag="continue" />
    <rom size="4" loadflag="reload" />
  </machine>
</mame>
"""
    software = """<?xml version="1.0"?>
<softwarelists>
  <softwarelist name="list">
    <software name="cart">
      <part name="p" interface="cart">
        <dataarea name="rom" size="2">
          <rom name="cart.bin" size="2" crc="55555555" />
        </dataarea>
      </part>
    </software>
    <software name="cartclone" cloneof="cart">
      <part name="p" interface="cart">
        <dataarea name="rom" size="5">
          <rom name="cart.bin" merge="cart.bin" size="2" crc="55555555" />
          <rom name="cartclone.bin" size="3" crc="66666666" />
        </dataarea>
      </part>
    </software>
    <software name="continued">
      <part name="p" interface="cart">
        <dataarea name="rom" size="9">
          <rom name="continued.bin" size="2" crc="7777777" />
          <rom size="3" loadflag="continue" />
          <rom size="4" loadflag="reload" />
        </dataarea>
      </part>
    </software>
  </softwarelist>
</softwarelists>
"""
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        arcade_xml = root / "mame.xml"
        software_xml = root / "software.xml"
        write(arcade_xml, arcade)
        write(software_xml, software)

        index = DatIndex(arcade_xml, software_xml, "merged").parse()

    assert sorted(index.arcade_targets) == ["roms/bios.7z", "roms/biosgame.7z", "roms/continued.7z", "roms/parent.7z"]
    assert names(index.arcade_targets["roms/bios.7z"]) == ["bios.bin"]
    assert names(index.arcade_targets["roms/parent.7z"]) == ["parent.bin", "clone.bin"]
    assert names(index.arcade_targets["roms/biosgame.7z"]) == ["game.bin"]
    assert entry_size(index.arcade_targets["roms/continued.7z"], "continued.bin") == 5

    assert sorted(index.software_targets) == ["software_roms/list/cart.7z", "software_roms/list/continued.7z"]
    assert names(index.software_targets["software_roms/list/cart.7z"]) == ["cart.bin", "cartclone.bin"]
    assert entry_size(index.software_targets["software_roms/list/continued.7z"], "continued.bin") == 5
    assert entry_crc(index.software_targets["software_roms/list/continued.7z"], "continued.bin") == "07777777"

    print("catalog merged inheritance tests passed")
    return 0


def names(target: dict[str, object]) -> list[str]:
    return [entry["name"] for entry in target["entries"]]  # type: ignore[index]


def entry_size(target: dict[str, object], name: str) -> int:
    for entry in target["entries"]:  # type: ignore[index]
        if entry["name"] == name:
            return int(entry["size"])
    raise AssertionError(f"missing entry: {name}")


def entry_crc(target: dict[str, object], name: str) -> str:
    for entry in target["entries"]:  # type: ignore[index]
        if entry["name"] == name:
            return str(entry["crc"])
    raise AssertionError(f"missing entry: {name}")


if __name__ == "__main__":
    raise SystemExit(main())
