from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from .runtime import VERSION, FatalError, parse_int, quote_cmd
from .settings import RunConfig
from .runtime import Shell

class DatExtractor:
    def __init__(self, cfg: RunConfig, shell: Shell):
        self.cfg = cfg
        self.shell = shell

    def extract(self) -> None:
        self.cfg.work.mkdir(parents=True, exist_ok=True)
        if not self.cfg.update_xml:
            missing = [p for p in (self.cfg.arcade_xml, self.cfg.software_xml) if not p.exists()]
            if missing:
                raise FatalError("XML file is missing; run with --update-xml to generate it: " + ", ".join(map(str, missing)))
            return
        if not self.cfg.mame_bin.exists():
            raise FatalError(f"MAME binary not found: {self.cfg.mame_bin}")
        self._write_command([self.cfg.mame_bin, "-listxml"], self.cfg.arcade_xml)
        self._build_software_xml_from_hash()

    def _write_command(self, cmd: list[str | Path], out: Path) -> None:
        tmp = out.with_suffix(out.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            proc = subprocess.run([str(x) for x in cmd], stdout=f, stderr=subprocess.PIPE, text=True)
        if proc.returncode != 0:
            tmp.unlink(missing_ok=True)
            raise FatalError(f"XML extraction failed: {quote_cmd(cmd)}\n{proc.stderr}")
        tmp.replace(out)

    def _build_software_xml_from_hash(self) -> None:
        hash_dir = self.cfg.mame_bin.parent / "hash"
        if not hash_dir.is_dir():
            raise FatalError(f"MAME hash directory not found: {hash_dir}")
        root = ET.Element("softwarelists")
        count = 0
        for xml in sorted(hash_dir.glob("*.xml")):
            try:
                subroot = ET.parse(xml).getroot()
            except ET.ParseError as e:
                raise FatalError(f"failed to parse software list {xml}: {e}") from e
            if subroot.tag == "softwarelist":
                root.append(subroot)
                count += 1
        if not count:
            raise FatalError(f"no software list XML files found in {hash_dir}")
        tmp = self.cfg.software_xml.with_suffix(".xml.tmp")
        ET.ElementTree(root).write(tmp, encoding="utf-8", xml_declaration=True)
        tmp.replace(self.cfg.software_xml)


class DatIndex:
    def __init__(self, arcade_xml: Path, software_xml: Path, merge_mode: str):
        self.arcade_xml = arcade_xml
        self.software_xml = software_xml
        self.merge_mode = merge_mode
        self.arcade_targets: dict[str, dict[str, Any]] = {}
        self.software_targets: dict[str, dict[str, Any]] = {}
        self.arcade_chds: list[dict[str, str]] = []
        self.software_chds: list[dict[str, str]] = []
        self.samples: set[str] = set()

    def parse(self) -> "DatIndex":
        self._parse_arcade()
        self._parse_software()
        return self

    def _parse_arcade(self) -> None:
        for _, elem in ET.iterparse(self.arcade_xml, events=("end",)):
            if elem.tag != "machine":
                continue
            machine = elem.attrib.get("name")
            if not machine:
                elem.clear()
                continue
            parent = elem.attrib.get("cloneof") or machine
            entries = []
            for rom in elem.findall("rom"):
                if rom.attrib.get("status") == "nodump":
                    continue
                if self.merge_mode == "merged" and rom.attrib.get("merge"):
                    continue
                name = rom.attrib.get("name")
                size = rom.attrib.get("size")
                crc = rom.attrib.get("crc")
                if name and size and crc:
                    entries.append({"name": name, "size": parse_int(size), "crc": crc.upper(), "sha1": rom.attrib.get("sha1")})
            if entries:
                rel = f"roms/{parent}.7z" if self.merge_mode == "merged" else f"roms/{machine}.7z"
                target = self.arcade_targets.setdefault(
                    rel,
                    {"kind": "arcade", "machine": parent, "machines": [], "entries": []},
                )
                target["machines"].append(machine)
                self._add_unique_entries(target["entries"], entries)
            for disk in elem.findall("disk"):
                if disk.attrib.get("status") == "nodump":
                    continue
                name = disk.attrib.get("name")
                sha1 = disk.attrib.get("sha1")
                if name and sha1:
                    self.arcade_chds.append({"machine": machine, "disk": name, "sha1": sha1.lower()})
            for sample in elem.findall("sample"):
                name = sample.attrib.get("name")
                if name:
                    self.samples.add(name)
            elem.clear()

    def _parse_software(self) -> None:
        root = ET.parse(self.software_xml).getroot()
        swlists = [root] if root.tag == "softwarelist" else root.findall("softwarelist")
        for swlist in swlists:
            list_name = swlist.attrib.get("name")
            if not list_name:
                continue
            for software in swlist.findall("software"):
                sw_name = software.attrib.get("name")
                if not sw_name:
                    continue
                parent = software.attrib.get("cloneof") or sw_name
                entries = []
                for rom in software.findall(".//rom"):
                    if rom.attrib.get("status") == "nodump":
                        continue
                    if self.merge_mode == "merged" and rom.attrib.get("merge"):
                        continue
                    name = rom.attrib.get("name")
                    size = rom.attrib.get("size")
                    crc = rom.attrib.get("crc")
                    if name and size and crc:
                        entries.append({"name": name, "size": parse_int(size), "crc": crc.upper(), "sha1": rom.attrib.get("sha1")})
                if entries:
                    rel_name = parent if self.merge_mode == "merged" else sw_name
                    rel = f"software_roms/{list_name}/{rel_name}.7z"
                    target = self.software_targets.setdefault(rel, {
                        "kind": "software",
                        "softwarelist": list_name,
                        "software": rel_name,
                        "software_items": [],
                        "entries": [],
                    })
                    target["software_items"].append(sw_name)
                    self._add_unique_entries(target["entries"], entries)
                for disk in software.findall(".//disk"):
                    if disk.attrib.get("status") == "nodump":
                        continue
                    name = disk.attrib.get("name")
                    sha1 = disk.attrib.get("sha1")
                    if name and sha1:
                        self.software_chds.append(
                            {"softwarelist": list_name, "software": sw_name, "disk": name, "sha1": sha1.lower()}
                        )

    @staticmethod
    def _add_unique_entries(dst: list[dict[str, Any]], src: list[dict[str, Any]]) -> None:
        seen = {(e["name"], int(e["size"]), (e.get("crc") or "").upper()) for e in dst}
        for entry in src:
            key = (entry["name"], int(entry["size"]), (entry.get("crc") or "").upper())
            if key in seen:
                continue
            dst.append(entry)
            seen.add(key)

    def manifest(self) -> dict[str, Any]:
        return {
            "version": VERSION,
            "merge_mode": self.merge_mode,
            "arcade": self.arcade_targets,
            "software": self.software_targets,
        }

    def all_targets(self) -> dict[str, dict[str, Any]]:
        return {**self.arcade_targets, **self.software_targets}
