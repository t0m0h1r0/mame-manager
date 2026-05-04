from __future__ import annotations

import argparse
from dataclasses import fields
from pathlib import Path

from . import defaults
from .settings import RunConfig


def parse_run_config(argv: list[str]) -> RunConfig:
    config_defaults = _load_config_defaults(argv)
    parser = _build_parser(config_defaults)
    args = parser.parse_args(argv)
    _validate_args(parser, args)
    return _run_config(args)


def _load_config_defaults(argv: list[str]) -> dict[str, str]:
    base = argparse.ArgumentParser(add_help=False)
    base.add_argument("--config", type=Path, default=defaults.config_file_default())
    args, _ = base.parse_known_args(argv)
    return defaults.load_config_env(args.config)


def _build_parser(config_defaults: dict[str, str]) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Python-only MAME images auditor/rebuilder.",
        parents=[_base_parser()],
    )
    _add_main_options(parser, config_defaults)
    _add_qbittorrent_options(parser, config_defaults)
    _add_compat_options(parser)
    return parser


def _base_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--config", type=Path, default=defaults.config_file_default())
    return parser


def _add_main_options(parser: argparse.ArgumentParser, config_defaults: dict[str, str]) -> None:
    parser.add_argument("--scan-only", action="store_true", help="scan only; this is the default")
    parser.add_argument("--rebuild", action="store_true", help="rebuild clean_images and sync it to images after scanning")
    parser.add_argument("--rebuild-plan-only", action="store_true")
    parser.add_argument("--torrent-plan", type=Path, default=defaults.DEFAULT_TORRENT_PLAN, metavar="FILE_LIST")
    parser.add_argument(
        "--update-xml",
        "--generate-xml",
        dest="update_xml",
        action="store_true",
        help="generate/update MAME XML before scanning",
    )
    parser.add_argument("--skip-xml", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--mame-bin", type=Path, default=defaults.DEFAULT_MAME_BIN)
    parser.add_argument("--images", type=Path, default=defaults.DEFAULT_IMAGES_DIR)
    parser.add_argument("--new", type=Path, default=defaults.DEFAULT_NEW_DIR)
    parser.add_argument("--work", type=Path, default=defaults.DEFAULT_WORK_DIR)
    parser.add_argument("--rsync-pass", type=Path, default=defaults.DEFAULT_RSYNC_PASSWORD_FILE)
    parser.add_argument(
        "--backup-url",
        default=defaults.configured_default(defaults.ENV_BACKUP_URL, defaults.DEFAULT_BACKUP_URL, config_defaults),
        help="backup/restore source URL; can also be set with BACKUP_URL or the config file",
    )
    parser.add_argument("--backup", action="store_true", help="also rsync images to the backup URL")
    parser.add_argument("--restore", action="store_true", help="rsync the backup URL back to images")
    parser.add_argument(
        "--check-broken",
        action="store_true",
        help="test archives and CHDs for corruption, resuming from the integrity cache",
    )
    parser.add_argument("--merge-mode", choices=["merged", "split", "non-merged"], default=defaults.DEFAULT_MERGE_MODE)
    parser.add_argument(
        "--scan-jobs",
        type=int,
        default=defaults.configured_int_default(defaults.ENV_SCAN_JOBS, defaults.DEFAULT_SCAN_JOBS, config_defaults),
    )
    parser.add_argument(
        "--compress-jobs",
        type=int,
        default=defaults.configured_int_default(defaults.ENV_COMPRESS_JOBS, defaults.DEFAULT_COMPRESS_JOBS, config_defaults),
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


def _add_qbittorrent_options(parser: argparse.ArgumentParser, config_defaults: dict[str, str]) -> None:
    qb = parser.add_argument_group("qBittorrent")
    qb.add_argument(
        "--qbittorrent-url",
        "--qb-url",
        dest="qbittorrent_url",
        default=defaults.configured_default(
            defaults.ENV_QBITTORRENT_URL,
            defaults.DEFAULT_QBITTORRENT_URL,
            config_defaults,
        ),
    )
    qb.add_argument(
        "--qbittorrent-user",
        "--qb-user",
        dest="qbittorrent_user",
        default=defaults.configured_default(
            defaults.ENV_QBITTORRENT_USER,
            defaults.DEFAULT_QBITTORRENT_USER,
            config_defaults,
        ),
    )
    qb.add_argument(
        "--qbittorrent-password",
        "--qb-password",
        dest="qbittorrent_password",
        default=defaults.configured_optional(defaults.ENV_QBITTORRENT_PASSWORD, config_defaults),
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


def _add_compat_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--igir-bin", default=defaults.DEFAULT_COMPAT_OPTION, help=argparse.SUPPRESS)
    parser.add_argument("--igir-scan-command", default=defaults.DEFAULT_COMPAT_OPTION, help=argparse.SUPPRESS)
    parser.add_argument("--igir-checksum-max", default=defaults.DEFAULT_COMPAT_OPTION, help=argparse.SUPPRESS)
    parser.add_argument("--igir-checksum-archives", default=defaults.DEFAULT_COMPAT_OPTION, help=argparse.SUPPRESS)
    parser.add_argument("--no-igir-checksum-quick", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--allow-igir-parse-warnings", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--rom-scan-mode", default=defaults.DEFAULT_COMPAT_OPTION, help=argparse.SUPPRESS)


def _validate_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    _reject(parser, args.scan_only and args.rebuild, "--scan-only and --rebuild cannot be used together")
    _reject(parser, args.rebuild and args.rebuild_plan_only, "--rebuild and --rebuild-plan-only cannot be used together")
    _reject(
        parser,
        args.restore and (args.scan_only or args.rebuild or args.rebuild_plan_only),
        "--restore cannot be combined with scan or rebuild options",
    )
    _reject(
        parser,
        args.restore and (args.backup or args.update_xml or args.download_missing or args.torrent_plan),
        "--restore cannot be combined with backup, XML update, torrent, or download actions",
    )
    _reject(
        parser,
        args.check_broken and _has_check_broken_conflict(args),
        "--check-broken cannot be combined with scan, rebuild, restore, backup, XML, torrent, or download actions",
    )
    _reject(parser, args.skip_xml and args.update_xml, "--skip-xml and --update-xml cannot be used together")
    _reject(parser, args.backup and not args.rebuild, "--backup requires --rebuild")
    _reject(parser, _has_qbittorrent_selection_without_action(args), "qBittorrent selection options require --download-missing")


def _reject(parser: argparse.ArgumentParser, condition: bool, message: str) -> None:
    if condition:
        parser.error(message)


def _has_check_broken_conflict(args: argparse.Namespace) -> bool:
    return bool(
        args.scan_only
        or args.rebuild
        or args.rebuild_plan_only
        or args.restore
        or args.backup
        or args.update_xml
        or args.download_missing
        or args.torrent_plan
    )


def _has_qbittorrent_selection_without_action(args: argparse.Namespace) -> bool:
    return bool(
        not args.download_missing
        and (
            args.qbittorrent_dry_run
            or args.qbittorrent_resume
            or args.qbittorrent_hash
            or args.qbittorrent_name
        )
    )


def _run_config(args: argparse.Namespace) -> RunConfig:
    values = vars(args).copy()
    values["scan_only"] = _default_scan_only(args)
    return RunConfig(**{field.name: values[field.name] for field in fields(RunConfig)})


def _default_scan_only(args: argparse.Namespace) -> bool:
    return not (args.rebuild or args.rebuild_plan_only or args.restore or args.check_broken)
