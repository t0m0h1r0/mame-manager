from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import defaults
from .workflow import MameRebuildApp
from .settings import RunConfig

def parse_args(argv: list[str]) -> RunConfig:
    parser = argparse.ArgumentParser(description="Python-only MAME images auditor/rebuilder.")
    parser.add_argument("--scan-only", action="store_true", help="scan only; this is the default")
    parser.add_argument("--rebuild", action="store_true", help="rebuild clean_images and run guarded rsync after scanning")
    parser.add_argument("--rebuild-plan-only", action="store_true")
    parser.add_argument("--torrent-plan", type=Path, default=defaults.DEFAULT_TORRENT_PLAN, metavar="FILE_LIST")
    parser.add_argument("--skip-xml", action="store_true")
    parser.add_argument("--no-qnap", action="store_true")
    parser.add_argument("--mame-bin", type=Path, default=defaults.DEFAULT_MAME_BIN)
    parser.add_argument("--images", type=Path, default=defaults.DEFAULT_IMAGES_DIR)
    parser.add_argument("--new", type=Path, default=defaults.DEFAULT_NEW_DIR)
    parser.add_argument("--work", type=Path, default=defaults.DEFAULT_WORK_DIR)
    parser.add_argument("--rsync-pass", type=Path, default=defaults.DEFAULT_RSYNC_PASSWORD_FILE)
    parser.add_argument("--backup-url", default=defaults.DEFAULT_BACKUP_URL)
    parser.add_argument("--merge-mode", choices=["merged", "split", "non-merged"], default=defaults.DEFAULT_MERGE_MODE)
    parser.add_argument(
        "--scan-jobs",
        type=int,
        default=defaults.env_int_default(defaults.ENV_SCAN_JOBS, defaults.DEFAULT_SCAN_JOBS),
    )
    parser.add_argument(
        "--compress-jobs",
        type=int,
        default=defaults.env_int_default(defaults.ENV_COMPRESS_JOBS, defaults.DEFAULT_COMPRESS_JOBS),
    )
    parser.add_argument("--rebuild-mode", choices=["auto", "full", "skip"], default=defaults.DEFAULT_REBUILD_MODE)
    parser.add_argument("--7z-bin", dest="sevenz_bin", default=defaults.DEFAULT_SEVENZ_BIN)
    parser.add_argument("--rsync-bin", default=defaults.DEFAULT_RSYNC_BIN)
    parser.add_argument("--chdman-bin", default=defaults.DEFAULT_CHDMAN_BIN)
    parser.add_argument("--no-chdman", action="store_true")
    parser.add_argument("--yes", action="store_true")
    parser.add_argument("--force-large-sync", action="store_true")
    parser.add_argument("--large-sync-threshold", type=int, default=defaults.DEFAULT_LARGE_SYNC_THRESHOLD)
    parser.add_argument(
        "--download-missing",
        action="store_true",
        help="apply missing/broken archive selection to qBittorrent after the scan",
    )
    qb = parser.add_argument_group("qBittorrent")
    qb.add_argument(
        "--qbittorrent-url",
        "--qb-url",
        dest="qbittorrent_url",
        default=defaults.env_default(defaults.ENV_QBITTORRENT_URL, defaults.DEFAULT_QBITTORRENT_URL),
    )
    qb.add_argument(
        "--qbittorrent-user",
        "--qb-user",
        dest="qbittorrent_user",
        default=defaults.env_default(defaults.ENV_QBITTORRENT_USER, defaults.DEFAULT_QBITTORRENT_USER),
    )
    qb.add_argument(
        "--qbittorrent-password",
        "--qb-password",
        dest="qbittorrent_password",
        default=defaults.env_optional(defaults.ENV_QBITTORRENT_PASSWORD),
    )
    qb.add_argument("--qbittorrent-hash", "--qb-hash", dest="qbittorrent_hash", default=defaults.DEFAULT_QBITTORRENT_HASH)
    qb.add_argument("--qbittorrent-name", "--qb-name", dest="qbittorrent_name", default=defaults.DEFAULT_QBITTORRENT_NAME)
    qb.add_argument(
        "--qbittorrent-priority",
        "--qb-priority",
        dest="qbittorrent_priority",
        type=int,
        default=defaults.DEFAULT_QBITTORRENT_PRIORITY,
    )
    qb.add_argument(
        "--qbittorrent-skip-priority",
        "--qb-skip-priority",
        dest="qbittorrent_skip_priority",
        type=int,
        default=defaults.DEFAULT_QBITTORRENT_SKIP_PRIORITY,
    )
    qb.add_argument("--qbittorrent-resume", "--qb-resume", dest="qbittorrent_resume", action="store_true")
    qb.add_argument("--qbittorrent-dry-run", "--qb-dry-run", dest="qbittorrent_dry_run", action="store_true")
    qb.add_argument(
        "--qbittorrent-timeout",
        "--qb-timeout",
        dest="qbittorrent_timeout",
        type=int,
        default=defaults.DEFAULT_QBITTORRENT_TIMEOUT,
    )

    # Backward-compatible no-op options from the Igir-based prototype.
    parser.add_argument("--igir-bin", default=defaults.DEFAULT_COMPAT_OPTION, help=argparse.SUPPRESS)
    parser.add_argument("--igir-scan-command", default=defaults.DEFAULT_COMPAT_OPTION, help=argparse.SUPPRESS)
    parser.add_argument("--igir-checksum-max", default=defaults.DEFAULT_COMPAT_OPTION, help=argparse.SUPPRESS)
    parser.add_argument("--igir-checksum-archives", default=defaults.DEFAULT_COMPAT_OPTION, help=argparse.SUPPRESS)
    parser.add_argument("--no-igir-checksum-quick", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--allow-igir-parse-warnings", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--rom-scan-mode", default=defaults.DEFAULT_COMPAT_OPTION, help=argparse.SUPPRESS)

    args = parser.parse_args(argv)
    if args.scan_only and args.rebuild:
        parser.error("--scan-only and --rebuild cannot be used together")
    if args.rebuild and args.rebuild_plan_only:
        parser.error("--rebuild and --rebuild-plan-only cannot be used together")
    if not args.download_missing and (
        args.qbittorrent_dry_run
        or args.qbittorrent_resume
        or args.qbittorrent_hash
        or args.qbittorrent_name
    ):
        parser.error("qBittorrent selection options require --download-missing")
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
        scan_only=not (args.rebuild or args.rebuild_plan_only),
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
        download_missing=args.download_missing,
        qbittorrent_url=args.qbittorrent_url,
        qbittorrent_user=args.qbittorrent_user,
        qbittorrent_password=args.qbittorrent_password,
        qbittorrent_hash=args.qbittorrent_hash,
        qbittorrent_name=args.qbittorrent_name,
        qbittorrent_priority=args.qbittorrent_priority,
        qbittorrent_skip_priority=args.qbittorrent_skip_priority,
        qbittorrent_resume=args.qbittorrent_resume,
        qbittorrent_dry_run=args.qbittorrent_dry_run,
        qbittorrent_timeout=args.qbittorrent_timeout,
    )


def main(argv: list[str] | None = None) -> int:
    return MameRebuildApp(parse_args(argv if argv is not None else sys.argv[1:])).run()


if __name__ == "__main__":
    raise SystemExit(main())
