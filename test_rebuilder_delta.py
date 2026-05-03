from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from tempfile import TemporaryDirectory

from mame_manager.builder import Rebuilder
from mame_manager.inventory import Inventory, archive_matches_target
from mame_manager.publisher import SyncManager
from mame_manager.reports import ReportManager


class FakeIndex:
    def __init__(self, targets: dict[str, dict[str, object]]):
        self.targets = targets

    def all_targets(self) -> dict[str, dict[str, object]]:
        return self.targets


class FakeIndexer:
    def index_one(self, path: Path) -> dict[str, object]:
        if path.name == "keep.7z":
            return {
                "ok": True,
                "entries": [{"path": "keep.bin", "name": "keep.bin", "size": 1, "crc": "11111111"}],
            }
        return {"ok": False, "entries": []}


def main() -> int:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        cfg = SimpleNamespace(
            work=root / "work",
            clean=root / "work" / "clean_images",
            raw=root / "work" / "raw",
            reports=root / "work" / "reports",
            images=root / "images",
            rebuild_mode="full",
            scan_only=False,
            rebuild_plan_only=False,
            merge_mode="merged",
            rsync_bin="rsync",
            rebuild_cache_file=root / "work" / "rebuild_cache.json",
        )
        (cfg.images / "roms").mkdir(parents=True)
        (cfg.images / "roms" / "keep.7z").write_bytes(b"placeholder")

        targets = {
            "roms/keep.7z": {
                "entries": [{"name": "keep.bin", "size": 1, "crc": "11111111"}],
            },
            "roms/missing.7z": {
                "entries": [{"name": "missing.bin", "size": 2, "crc": "22222222"}],
            },
        }
        report = ReportManager(cfg)
        Rebuilder(cfg, SimpleNamespace(), report, FakeIndexer()).rebuild(
            FakeIndex(targets),
            Inventory({}),
            manifest_hash="manifest",
            input_fp="input",
            dat_hash="dat",
        )

        assert not (cfg.clean / "roms" / "keep.7z").exists()
        assert not (cfg.clean / "roms" / "missing.7z").exists()
        assert report.summary["unchanged_rom_packages"] == 1
        assert report.summary["rebuilt_rom_packages"] == 0
        assert report.summary["unbuildable_rom_packages"] == 1
        assert "roms/missing.7z" in (cfg.reports / "rebuild_unbuildable.txt").read_text(encoding="utf-8")

        sync = SyncManager(cfg, SimpleNamespace(), report)
        patch_cmd = sync._cmd(cfg.clean, cfg.images, dry=True, password=None, delete=False)
        backup_cmd = sync._cmd(cfg.images, "rsync://backup/images/", dry=True, password=None, delete=True)
        assert "--delete" not in patch_cmd
        assert "--delete" in backup_cmd

    test_merged_archive_paths()
    print("delta rebuild tests passed")
    return 0


def test_merged_archive_paths() -> None:
    rec = {
        "ok": True,
        "entries": [
            {"path": "parent.bin", "name": "parent.bin", "size": 1, "crc": "11111111"},
            {"path": "clone/rom.bin", "name": "rom.bin", "size": 2, "crc": "22222222"},
        ],
    }
    target = {
        "entries": [
            {"name": "parent.bin", "size": 1, "crc": "11111111"},
            {"name": "rom.bin", "size": 2, "crc": "22222222"},
        ],
    }
    assert archive_matches_target(rec, target)


if __name__ == "__main__":
    raise SystemExit(main())
