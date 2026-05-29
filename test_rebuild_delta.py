from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from tempfile import TemporaryDirectory

from mame_manager.rebuilder import Rebuilder
from mame_manager.collection_index import Inventory, archive_matches_target
from mame_manager.sync import SyncManager
from mame_manager.reporting import ReportManager


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
            new=root / "Downloads",
            rebuild_mode="full",
            scan_only=False,
            rebuild_plan_only=False,
            restore=False,
            check_broken=False,
            merge_mode="merged",
            rsync_bin="rsync",
            rebuild_cache_file=root / "work" / "rebuild_cache.json",
        )
        (cfg.images / "roms").mkdir(parents=True)
        cfg.new.mkdir(parents=True)
        (cfg.images / "roms" / "keep.7z").write_bytes(b"placeholder")
        incoming = cfg.new / "partial.zip"
        incoming.write_bytes(b"placeholder")

        targets = {
            "roms/keep.7z": {
                "entries": [{"name": "keep.bin", "size": 1, "crc": "11111111"}],
            },
            "roms/missing.7z": {
                "entries": [{"name": "missing.bin", "size": 2, "crc": "22222222"}],
            },
            "roms/partial.7z": {
                "entries": [
                    {"name": "have.bin", "size": 3, "crc": "33333333"},
                    {"name": "need.bin", "size": 4, "crc": "44444444"},
                ],
            },
        }
        report = ReportManager(cfg)
        inventory = Inventory(
            {
                str(incoming.resolve()): {
                    "ok": True,
                    "entries": [{"path": "have.bin", "name": "have.bin", "size": 3, "crc": "33333333"}],
                }
            }
        )
        Rebuilder(cfg, SimpleNamespace(), report, FakeIndexer()).rebuild(
            FakeIndex(targets),
            inventory,
            manifest_hash="manifest",
            input_fp="input",
            dat_hash="dat",
        )

        assert not (cfg.clean / "roms" / "keep.7z").exists()
        assert not (cfg.clean / "roms" / "missing.7z").exists()
        assert not (cfg.clean / "roms" / "partial.7z").exists()
        assert report.summary["unchanged_rom_packages"] == 1
        assert report.summary["rebuilt_rom_packages"] == 0
        assert report.summary["unbuildable_rom_packages"] == 1
        assert report.summary["skipped_no_incoming_rom_packages"] == 1
        assert "roms/partial.7z" in (cfg.reports / "rebuild_unbuildable.txt").read_text(encoding="utf-8")
        assert "roms/missing.7z" in (cfg.reports / "rebuild_skipped_no_incoming.txt").read_text(encoding="utf-8")

        sync = SyncManager(cfg, SimpleNamespace(), report)
        patch_cmd = sync._cmd(cfg.clean, cfg.images, dry=True, password=None, delete=False)
        backup_cmd = sync._cmd(cfg.images, "rsync://backup/images/", dry=True, password=None, delete=True)
        restore_cmd = sync._cmd(
            "rsync://backup/images/",
            cfg.images,
            dry=True,
            password=cfg.rebuild_cache_file,
            delete=True,
            delete_before=True,
        )
        assert "--delete" not in patch_cmd
        assert "--delete" in backup_cmd
        assert "--delete-before" in restore_cmd
        assert "--delete" not in restore_cmd
        assert str(restore_cmd[-2]).endswith("/")
        assert restore_cmd[-1] == str(cfg.images)

    test_merged_archive_paths()
    test_duplicate_staging_paths_keep_distinct_entries()
    print("delta rebuild tests passed")
    return 0


def test_merged_archive_paths() -> None:
    rec = {
        "ok": True,
        "entries": [
            {"path": "parent.bin", "name": "parent.bin", "size": 1, "crc": "11111111"},
            {"path": "clone/rom.bin", "name": "rom.bin", "size": 2, "crc": "22222222"},
            {"path": "clone/original-name.bin", "name": "original-name.bin", "size": 3, "crc": "33333333"},
        ],
    }
    target = {
        "entries": [
            {"name": "parent.bin", "size": 1, "crc": "11111111"},
            {"name": "rom.bin", "size": 2, "crc": "22222222"},
            {"name": "renamed.bin", "size": 3, "crc": "33333333"},
        ],
    }
    assert archive_matches_target(rec, target)


def test_duplicate_staging_paths_keep_distinct_entries() -> None:
    duplicate_names = {"rom.bin"}
    used: set[str] = set()

    first = Rebuilder._staging_relpath("rom.bin", "parent/rom.bin", duplicate_names, used)
    second = Rebuilder._staging_relpath("rom.bin", "clone/rom.bin", duplicate_names, used)
    third = Rebuilder._staging_relpath("rom.bin", "clone/rom.bin", duplicate_names, used)
    normal = Rebuilder._staging_relpath("renamed.bin", "source/original.bin", duplicate_names, used)

    assert first == Path("parent/rom.bin")
    assert second == Path("clone/rom.bin")
    assert third == Path("__dup2/rom.bin")
    assert normal == Path("renamed.bin")


if __name__ == "__main__":
    raise SystemExit(main())
