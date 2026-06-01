from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from mame_manager.gui_model import (
    GUI_REMOTE_BACKUP_AFTER_REBUILD,
    GuiSettings,
    WorkflowAction,
    build_command,
    load_gui_settings,
    phase_index,
)


def make_settings(root: Path, remote_backup: bool = False) -> GuiSettings:
    return GuiSettings(
        config_file=root / "config.env",
        mame_bin=root / "mame",
        images=root / "images",
        new=root / "Downloads",
        work=root / "work_mame",
        rsync_pass=root / ".rsync",
        backup_url="rsync://backup/images/",
        scan_jobs=8,
        compress_jobs=2,
        merge_mode="merged",
        rebuild_mode="auto",
        sevenz_bin="7z",
        rsync_bin="rsync",
        chdman_bin="chdman",
        no_chdman=False,
        yes=False,
        force_large_sync=False,
        large_sync_threshold=1000,
        remote_backup_after_rebuild=remote_backup,
        qbittorrent_url="http://localhost:8080",
        qbittorrent_user="admin",
        qbittorrent_password="secret",
        qbittorrent_hash=None,
        qbittorrent_name="MAME",
        qbittorrent_priority=1,
        qbittorrent_skip_priority=0,
        qbittorrent_timeout=30,
        python_executable="python",
    )


def main() -> int:
    with TemporaryDirectory() as td:
        root = Path(td)
        settings = make_settings(root)

        update_scan = build_command(settings, WorkflowAction.UPDATE_SCAN)
        assert update_scan.arguments[:2] == ("-m", "mame_manager.cli")
        assert "--update-xml" in update_scan.arguments
        assert "--scan-only" in update_scan.arguments
        assert update_scan.workflow_index == 1

        rebuild = build_command(settings, WorkflowAction.LOCAL_REBUILD)
        assert "--rebuild" in rebuild.arguments
        assert "--backup" not in rebuild.arguments

        rebuild_with_backup = build_command(make_settings(root, remote_backup=True), WorkflowAction.LOCAL_REBUILD)
        assert "--rebuild" in rebuild_with_backup.arguments
        assert "--backup" in rebuild_with_backup.arguments

        qb_dry_run = build_command(settings, WorkflowAction.QB_DRY_RUN)
        assert "--download-missing" in qb_dry_run.arguments
        assert "--qbittorrent-dry-run" in qb_dry_run.arguments
        assert qb_dry_run.environment == {"QBITTORRENT_PASSWORD": "secret"}
        assert "secret" not in qb_dry_run.display()
        assert "QBITTORRENT_PASSWORD=***" in qb_dry_run.display()

        final_scan = build_command(settings, WorkflowAction.FINAL_SCAN)
        assert str(settings.empty_incoming_dir) in final_scan.arguments
        assert final_scan.required_dirs == (settings.empty_incoming_dir,)

        remote_backup = build_command(settings, WorkflowAction.REMOTE_BACKUP)
        assert "--backup" in remote_backup.arguments
        assert str(settings.empty_incoming_dir) in remote_backup.arguments
        assert remote_backup.confirm

        assert phase_index("[2026-06-01T00:00:00] index archives", update_scan.phases) == 5
        assert phase_index("unrelated output", update_scan.phases) is None

        config = root / "gui.env"
        config.write_text(f"{GUI_REMOTE_BACKUP_AFTER_REBUILD}=1\n", encoding="utf-8")
        loaded = load_gui_settings(config)
        assert loaded.remote_backup_after_rebuild

    print("GUI model tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
