from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from tempfile import TemporaryDirectory

from mame_manager.assets import AssetManager
from mame_manager.reporting import ReportManager


class FakeIndexer:
    def __init__(self, records: dict[Path, dict[str, object]]):
        self.records = records

    def index_one(self, path: Path) -> dict[str, object]:
        return self.records[path]


def main() -> int:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        cfg = SimpleNamespace(
            images=root / "images",
            new=root / "Downloads",
            clean=root / "work" / "clean_images",
            reports=root / "work" / "reports",
            scan_only=True,
            rebuild_plan_only=False,
            restore=False,
            check_broken=False,
            merge_mode="merged",
        )
        (cfg.images / "samples").mkdir(parents=True)
        cfg.new.mkdir(parents=True)

        existing = cfg.images / "samples" / "qbert.zip"
        existing.write_bytes(b"placeholder")
        incoming = cfg.new / "fresh.7z"
        incoming.write_bytes(b"placeholder")

        index = SimpleNamespace(
            sample_targets={
                "samples/qbert": {
                    "sample_set": "qbert",
                    "entries": [{"name": "jump"}, {"name": "fall"}],
                },
                "samples/fresh": {
                    "sample_set": "fresh",
                    "entries": [{"name": "coin"}, {"name": "hit"}],
                },
                "samples/missing": {
                    "sample_set": "missing",
                    "entries": [{"name": "zap"}],
                },
            }
        )
        indexer = FakeIndexer(
            {
                existing: {
                    "ok": True,
                    "entries": [
                        {"path": "jump.wav", "name": "jump.wav"},
                        {"path": "fall.flac", "name": "fall.flac"},
                    ],
                },
                incoming: {
                    "ok": True,
                    "entries": [
                        {"path": "coin.wav", "name": "coin.wav"},
                        {"path": "hit.mp3", "name": "hit.mp3"},
                    ],
                },
            }
        )

        report = ReportManager(cfg)
        assets = AssetManager(cfg, report)
        assets.report_samples(index, indexer)
        assert report.summary["sample_sets"] == {"complete": 2, "incomplete": 1, "total": 3}
        assert report.summary["sample_file_entries"] == {"missing": 1, "present": 4, "total": 5}
        assert (cfg.reports / "sample_missing_entries.txt").read_text(encoding="utf-8") == "samples/missing: zap\n"

        assets.place_samples(index, indexer)
        assert (cfg.clean / "samples" / "fresh.7z").exists()
        assert not (cfg.clean / "samples" / "qbert.zip").exists()

    print("sample asset tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
