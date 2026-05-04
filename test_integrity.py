from __future__ import annotations

import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from mame_manager.integrity import IntegrityChecker
from mame_manager.reporting import ReportManager
from mame_manager.system import Shell


def write_executable(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")
    path.chmod(path.stat().st_mode | 0o111)


def main() -> int:
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        log_7z = root / "7z.log"
        log_chdman = root / "chdman.log"
        fake_7z = root / "7z"
        fake_chdman = root / "chdman"
        write_executable(
            fake_7z,
            f"""#!/bin/sh
echo "$@" >> {log_7z}
case "$@" in
  *bad.7z*) echo "Data Error"; exit 2 ;;
  *) echo "Everything is Ok"; exit 0 ;;
esac
""",
        )
        write_executable(
            fake_chdman,
            f"""#!/bin/sh
echo "$@" >> {log_chdman}
exit 0
""",
        )

        images = root / "images"
        new = root / "Downloads"
        (images / "roms").mkdir(parents=True)
        (images / "software_roms" / "list").mkdir(parents=True)
        (images / "chds" / "game").mkdir(parents=True)
        new.mkdir()
        for path in (
            images / "roms" / "ok.7z",
            images / "roms" / "bad.7z",
            images / "software_roms" / "list" / "cart.zip",
            new / "incoming.7z",
            images / "chds" / "game" / "disk.chd",
        ):
            path.write_bytes(b"placeholder")

        cfg = SimpleNamespace(
            images=images,
            new=new,
            work=root / "work",
            reports=root / "work" / "reports",
            scan_only=False,
            rebuild_plan_only=False,
            restore=False,
            check_broken=True,
            merge_mode="merged",
            scan_jobs=2,
            sevenz_bin=str(fake_7z),
            chdman_bin=str(fake_chdman),
            no_chdman=False,
            mame_bin=root / "mame" / "mame",
            integrity_cache_file=root / "work" / "integrity_cache.json",
        )

        report = ReportManager(cfg)
        first = IntegrityChecker(cfg, Shell(), report).check_all()
        assert len(first) == 5
        assert report.summary["integrity_broken_files"] == 1
        broken_report = (cfg.reports / "integrity_broken_files.txt").read_text(encoding="utf-8")
        assert "bad.7z" in broken_report
        assert "Data Error" in broken_report
        assert len(log_7z.read_text(encoding="utf-8").splitlines()) == 4
        assert len(log_chdman.read_text(encoding="utf-8").splitlines()) == 1

        log_7z.write_text("", encoding="utf-8")
        log_chdman.write_text("", encoding="utf-8")
        report2 = ReportManager(cfg)
        second = IntegrityChecker(cfg, Shell(), report2).check_all()
        assert len(second) == 5
        assert report2.summary["integrity_cache"]["hits"] == 5
        assert report2.summary["integrity_cache"]["misses"] == 0
        assert log_7z.read_text(encoding="utf-8") == ""
        assert log_chdman.read_text(encoding="utf-8") == ""

        os.utime(images / "roms" / "ok.7z")
        report3 = ReportManager(cfg)
        IntegrityChecker(cfg, Shell(), report3).check_all()
        assert report3.summary["integrity_cache"]["misses"] == 1

    print("integrity check tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
