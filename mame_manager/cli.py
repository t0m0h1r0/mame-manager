from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .workflow import MameRebuildApp
from .settings import RunConfig

def parse_args(argv: list[str]) -> RunConfig:
    parser = argparse.ArgumentParser(description="Python-only MAME images auditor/rebuilder.")
    parser.add_argument("--scan-only", action="store_true")
    parser.add_argument("--rebuild-plan-only", action="store_true")
    parser.add_argument("--torrent-plan", type=Path, default=None, metavar="FILE_LIST")
    parser.add_argument("--skip-xml", action="store_true")
    parser.add_argument("--no-qnap", action="store_true")
    parser.add_argument("--mame-bin", type=Path, default=Path("mame/mame"))
    parser.add_argument("--images", type=Path, default=Path("images"))
    parser.add_argument("--new", type=Path, default=Path("new"))
    parser.add_argument("--work", type=Path, default=Path("work_mame"))
    parser.add_argument("--rsync-pass", type=Path, default=Path(".rsync"))
    parser.add_argument("--backup-url", default="rsync://rsync@qnap2/Game/Multi-Platform/images/")
    parser.add_argument("--merge-mode", choices=["merged", "split", "non-merged"], default="merged")
    parser.add_argument("--scan-jobs", type=int, default=int(os.environ.get("SCAN_JOBS", "16")))
    parser.add_argument("--compress-jobs", type=int, default=int(os.environ.get("COMPRESS_JOBS", "4")))
    parser.add_argument("--rebuild-mode", choices=["auto", "full", "skip"], default="auto")
    parser.add_argument("--7z-bin", dest="sevenz_bin", default="7z")
    parser.add_argument("--rsync-bin", default="rsync")
    parser.add_argument("--chdman-bin", default="chdman")
    parser.add_argument("--no-chdman", action="store_true")
    parser.add_argument("--yes", action="store_true")
    parser.add_argument("--force-large-sync", action="store_true")
    parser.add_argument("--large-sync-threshold", type=int, default=1000)

    # Backward-compatible no-op options from the Igir-based prototype.
    parser.add_argument("--igir-bin", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--igir-scan-command", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--igir-checksum-max", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--igir-checksum-archives", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--no-igir-checksum-quick", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--allow-igir-parse-warnings", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--rom-scan-mode", default=None, help=argparse.SUPPRESS)

    args = parser.parse_args(argv)
    return RunConfig(
        mame_bin=args.mame_bin,
        images=args.images,
        new=args.new,
        work=args.work,
        rsync_pass=args.rsync_pass,
        backup_url=args.backup_url,
        merge_mode=args.merge_mode,
        scan_jobs=args.scan_jobs,
        compress_jobs=args.compress_jobs,
        scan_only=args.scan_only,
        rebuild_plan_only=args.rebuild_plan_only,
        torrent_plan=args.torrent_plan,
        skip_xml=args.skip_xml,
        no_qnap=args.no_qnap,
        rebuild_mode=args.rebuild_mode,
        sevenz_bin=args.sevenz_bin,
        rsync_bin=args.rsync_bin,
        chdman_bin=args.chdman_bin,
        no_chdman=args.no_chdman,
        yes=args.yes,
        force_large_sync=args.force_large_sync,
        large_sync_threshold=args.large_sync_threshold,
    )


def main(argv: list[str] | None = None) -> int:
    return MameRebuildApp(parse_args(argv if argv is not None else sys.argv[1:])).run()


if __name__ == "__main__":
    raise SystemExit(main())
