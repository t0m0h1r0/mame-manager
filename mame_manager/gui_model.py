from __future__ import annotations

import shlex
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from . import defaults
from .cli import parse_args


class WorkflowAction(str, Enum):
    UPDATE_SCAN = "update_scan"
    LOCAL_REBUILD = "local_rebuild"
    SCAN_MISSING = "scan_missing"
    REBUILD_PLAN = "rebuild_plan"
    QB_DRY_RUN = "qb_dry_run"
    QB_APPLY = "qb_apply"
    QB_APPLY_RESUME = "qb_apply_resume"
    DOWNLOAD_REBUILD = "download_rebuild"
    FINAL_SCAN = "final_scan"
    CHECK_BROKEN = "check_broken"
    REMOTE_BACKUP = "remote_backup"
    RESTORE = "restore"


@dataclass(frozen=True)
class GuiSettings:
    config_file: Path
    mame_bin: Path
    images: Path
    new: Path
    work: Path
    rsync_pass: Path
    backup_url: str | None
    scan_jobs: int
    compress_jobs: int
    merge_mode: str
    rebuild_mode: str
    sevenz_bin: str
    rsync_bin: str
    chdman_bin: str
    no_chdman: bool
    yes: bool
    force_large_sync: bool
    large_sync_threshold: int
    remote_backup_after_rebuild: bool
    qbittorrent_url: str | None
    qbittorrent_user: str
    qbittorrent_password: str | None
    qbittorrent_hash: str | None
    qbittorrent_name: str | None
    qbittorrent_priority: int
    qbittorrent_skip_priority: int
    qbittorrent_timeout: int
    python_executable: str = sys.executable

    @property
    def reports_dir(self) -> Path:
        return self.work / "reports"

    @property
    def empty_incoming_dir(self) -> Path:
        return self.work / "empty_incoming"


@dataclass(frozen=True)
class CommandSpec:
    action: WorkflowAction
    title: str
    program: str
    arguments: tuple[str, ...]
    environment: dict[str, str]
    phases: tuple[str, ...]
    workflow_index: int
    workflow_total: int
    required_dirs: tuple[Path, ...] = ()
    confirm: str | None = None

    def display(self) -> str:
        env_parts = [f"{key}=***" for key in sorted(self.environment)]
        command = [self.program, *self.arguments]
        return " ".join([*env_parts, *(shlex.quote(part) for part in command)])


WORKFLOW_TOTAL = 10
GUI_REMOTE_BACKUP_AFTER_REBUILD = "GUI_REMOTE_BACKUP_AFTER_REBUILD"

COMMON_SCAN_PHASES = (
    "validate",
    "extract DAT",
    "parse DAT",
    "fingerprint inputs",
    "index archives",
    "audit ROMs",
    "scan CHDs",
    "done",
)

REBUILD_PHASES = (
    "validate",
    "extract DAT",
    "parse DAT",
    "fingerprint inputs",
    "index archives",
    "audit ROMs",
    "scan CHDs",
    "rebuild clean_images",
    "rsync",
    "done",
)

QB_PHASES = (
    "validate",
    "extract DAT",
    "parse DAT",
    "fingerprint inputs",
    "index archives",
    "audit ROMs",
    "scan CHDs",
    "apply qBittorrent file priorities",
    "done",
)

ACTION_TITLES = {
    WorkflowAction.UPDATE_SCAN: "XML更新してスキャン",
    WorkflowAction.LOCAL_REBUILD: "ローカル素材でrebuild",
    WorkflowAction.SCAN_MISSING: "不足を再確認",
    WorkflowAction.REBUILD_PLAN: "rebuild計画だけ確認",
    WorkflowAction.QB_DRY_RUN: "qBittorrent dry-run / torrent確認",
    WorkflowAction.QB_APPLY: "qBittorrentに適用",
    WorkflowAction.QB_APPLY_RESUME: "qBittorrentに適用して開始",
    WorkflowAction.DOWNLOAD_REBUILD: "ダウンロード後rebuild",
    WorkflowAction.FINAL_SCAN: "最終スキャン",
    WorkflowAction.CHECK_BROKEN: "破損チェック",
    WorkflowAction.REMOTE_BACKUP: "リモートバックアップ",
    WorkflowAction.RESTORE: "バックアップから復元",
}

ACTION_INDEX = {
    WorkflowAction.UPDATE_SCAN: 1,
    WorkflowAction.LOCAL_REBUILD: 2,
    WorkflowAction.SCAN_MISSING: 3,
    WorkflowAction.REBUILD_PLAN: 3,
    WorkflowAction.QB_DRY_RUN: 4,
    WorkflowAction.QB_APPLY: 5,
    WorkflowAction.QB_APPLY_RESUME: 5,
    WorkflowAction.DOWNLOAD_REBUILD: 6,
    WorkflowAction.FINAL_SCAN: 8,
    WorkflowAction.CHECK_BROKEN: 9,
    WorkflowAction.REMOTE_BACKUP: 10,
    WorkflowAction.RESTORE: 10,
}


def load_gui_settings(config_file: Path | None = None) -> GuiSettings:
    config_path = config_file or defaults.config_file_default()
    config_values = defaults.load_config_env(config_path)
    cfg = parse_args(["--config", str(config_path)])
    return GuiSettings(
        config_file=config_path,
        mame_bin=cfg.mame_bin,
        images=cfg.images,
        new=cfg.new,
        work=cfg.work,
        rsync_pass=cfg.rsync_pass,
        backup_url=cfg.backup_url,
        scan_jobs=cfg.scan_jobs,
        compress_jobs=cfg.compress_jobs,
        merge_mode=cfg.merge_mode,
        rebuild_mode=cfg.rebuild_mode,
        sevenz_bin=cfg.sevenz_bin,
        rsync_bin=cfg.rsync_bin,
        chdman_bin=cfg.chdman_bin,
        no_chdman=cfg.no_chdman,
        yes=cfg.yes,
        force_large_sync=cfg.force_large_sync,
        large_sync_threshold=cfg.large_sync_threshold,
        remote_backup_after_rebuild=_config_bool(config_values.get(GUI_REMOTE_BACKUP_AFTER_REBUILD), False),
        qbittorrent_url=cfg.qbittorrent_url,
        qbittorrent_user=cfg.qbittorrent_user,
        qbittorrent_password=cfg.qbittorrent_password,
        qbittorrent_hash=cfg.qbittorrent_hash,
        qbittorrent_name=cfg.qbittorrent_name,
        qbittorrent_priority=cfg.qbittorrent_priority,
        qbittorrent_skip_priority=cfg.qbittorrent_skip_priority,
        qbittorrent_timeout=cfg.qbittorrent_timeout,
    )


def _config_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def build_command(settings: GuiSettings, action: WorkflowAction) -> CommandSpec:
    action_args, phases, required_dirs, confirm = _action_config(settings, action)
    arguments = ("-m", "mame_manager.cli", *action_args, *_common_args(settings, action))
    return CommandSpec(
        action=action,
        title=ACTION_TITLES[action],
        program=settings.python_executable,
        arguments=tuple(str(arg) for arg in arguments),
        environment=_environment(settings, action),
        phases=phases,
        workflow_index=ACTION_INDEX[action],
        workflow_total=WORKFLOW_TOTAL,
        required_dirs=required_dirs,
        confirm=confirm,
    )


def phase_index(line: str, phases: tuple[str, ...]) -> int | None:
    text = line.strip()
    for index, phase in enumerate(phases, start=1):
        if text == phase or text.endswith(f"] {phase}"):
            return index
    return None


def _action_config(settings: GuiSettings, action: WorkflowAction) -> tuple[tuple[str, ...], tuple[str, ...], tuple[Path, ...], str | None]:
    if action == WorkflowAction.UPDATE_SCAN:
        return ("--update-xml", "--scan-only"), COMMON_SCAN_PHASES, (), None
    if action == WorkflowAction.LOCAL_REBUILD:
        return _rebuild_args(settings), REBUILD_PHASES, (), None
    if action == WorkflowAction.SCAN_MISSING:
        return ("--scan-only",), COMMON_SCAN_PHASES, (), None
    if action == WorkflowAction.REBUILD_PLAN:
        return ("--rebuild-plan-only",), (*COMMON_SCAN_PHASES[:-1], "plan rebuild", "done"), (), None
    if action == WorkflowAction.QB_DRY_RUN:
        return ("--scan-only", "--download-missing", "--qbittorrent-dry-run"), QB_PHASES, (), None
    if action == WorkflowAction.QB_APPLY:
        return ("--scan-only", "--download-missing"), QB_PHASES, (), "qBittorrentのファイル優先度を変更します。"
    if action == WorkflowAction.QB_APPLY_RESUME:
        return (
            "--scan-only",
            "--download-missing",
            "--qbittorrent-resume",
        ), QB_PHASES, (), "qBittorrentのファイル優先度を変更してtorrentを開始します。"
    if action == WorkflowAction.DOWNLOAD_REBUILD:
        return _rebuild_args(settings), REBUILD_PHASES, (), None
    if action == WorkflowAction.FINAL_SCAN:
        return ("--scan-only",), COMMON_SCAN_PHASES, (settings.empty_incoming_dir,), None
    if action == WorkflowAction.CHECK_BROKEN:
        return ("--check-broken",), ("validate", "check broken files", "done"), (settings.empty_incoming_dir,), None
    if action == WorkflowAction.REMOTE_BACKUP:
        return (
            "--rebuild",
            "--backup",
        ), REBUILD_PHASES, (settings.empty_incoming_dir,), "リモートバックアップ先へ同期します。"
    if action == WorkflowAction.RESTORE:
        return ("--restore",), ("validate", "restore images", "done"), (), "バックアップURLからimagesへ復元します。"
    raise ValueError(f"unsupported workflow action: {action}")


def _rebuild_args(settings: GuiSettings) -> tuple[str, ...]:
    args = ["--rebuild"]
    if settings.remote_backup_after_rebuild:
        args.append("--backup")
    return tuple(args)


def _common_args(settings: GuiSettings, action: WorkflowAction) -> tuple[str, ...]:
    new_dir = settings.empty_incoming_dir if action in {
        WorkflowAction.FINAL_SCAN,
        WorkflowAction.CHECK_BROKEN,
        WorkflowAction.REMOTE_BACKUP,
    } else settings.new
    args = [
        "--config",
        settings.config_file,
        "--mame-bin",
        settings.mame_bin,
        "--images",
        settings.images,
        "--new",
        new_dir,
        "--work",
        settings.work,
        "--rsync-pass",
        settings.rsync_pass,
        "--merge-mode",
        settings.merge_mode,
        "--scan-jobs",
        str(settings.scan_jobs),
        "--compress-jobs",
        str(settings.compress_jobs),
        "--rebuild-mode",
        settings.rebuild_mode,
        "--7z-bin",
        settings.sevenz_bin,
        "--rsync-bin",
        settings.rsync_bin,
        "--chdman-bin",
        settings.chdman_bin,
        "--large-sync-threshold",
        str(settings.large_sync_threshold),
    ]
    if settings.backup_url:
        args.extend(["--backup-url", settings.backup_url])
    if settings.no_chdman:
        args.append("--no-chdman")
    if settings.yes:
        args.append("--yes")
    if settings.force_large_sync:
        args.append("--force-large-sync")
    if action in {
        WorkflowAction.QB_DRY_RUN,
        WorkflowAction.QB_APPLY,
        WorkflowAction.QB_APPLY_RESUME,
    }:
        args.extend(_qbittorrent_args(settings))
    return tuple(str(arg) for arg in args)


def _qbittorrent_args(settings: GuiSettings) -> tuple[str, ...]:
    args = [
        "--qbittorrent-user",
        settings.qbittorrent_user,
        "--qbittorrent-priority",
        str(settings.qbittorrent_priority),
        "--qbittorrent-skip-priority",
        str(settings.qbittorrent_skip_priority),
        "--qbittorrent-timeout",
        str(settings.qbittorrent_timeout),
    ]
    if settings.qbittorrent_url:
        args.extend(["--qbittorrent-url", settings.qbittorrent_url])
    if settings.qbittorrent_hash:
        args.extend(["--qbittorrent-hash", settings.qbittorrent_hash])
    if settings.qbittorrent_name:
        args.extend(["--qbittorrent-name", settings.qbittorrent_name])
    return tuple(args)


def _environment(settings: GuiSettings, action: WorkflowAction) -> dict[str, str]:
    if action not in {
        WorkflowAction.QB_DRY_RUN,
        WorkflowAction.QB_APPLY,
        WorkflowAction.QB_APPLY_RESUME,
    }:
        return {}
    if not settings.qbittorrent_password:
        return {}
    return {defaults.ENV_QBITTORRENT_PASSWORD: settings.qbittorrent_password}
