from __future__ import annotations

import re
from pathlib import Path

from .system import FatalError
from .config import RunConfig
from .reporting import ReportManager
from .system import Shell

class SyncManager:
    def __init__(self, cfg: RunConfig, shell: Shell, report: ReportManager):
        self.cfg = cfg
        self.shell = shell
        self.report = report

    def sync_all(self) -> None:
        self._sync(self.cfg.clean, self.cfg.images, "rsync_clean_to_images_dry_run.txt", delete=False)
        if self.cfg.backup:
            backup_url = self._backup_url()
            self._sync(
                self.cfg.images,
                backup_url,
                "rsync_images_to_backup_dry_run.txt",
                password=self._password_for(self.cfg.images, backup_url),
            )

    def restore_images(self) -> None:
        backup_url = self._backup_url()
        self._sync(
            backup_url,
            self.cfg.images,
            "rsync_backup_to_images_dry_run.txt",
            password=self._password_for(backup_url, self.cfg.images),
            delete=True,
            delete_before=True,
        )

    def _sync(
        self,
        src: Path | str,
        dst: Path | str,
        log_name: str,
        password: Path | None = None,
        delete: bool = True,
        delete_before: bool = False,
    ) -> None:
        dry_log = self.cfg.reports / log_name
        dry_cmd = self._cmd(src, dst, dry=True, password=password, delete=delete, delete_before=delete_before)
        self.shell.run_to_log(dry_cmd, dry_log, check=True)
        changes = self._count_changes(dry_log)
        self.report.summary[log_name.replace(".txt", "_changes")] = changes
        if changes >= self.cfg.large_sync_threshold and not self.cfg.force_large_sync:
            raise FatalError(f"rsync dry-run has {changes} changes; rerun with --force-large-sync if intended")
        if not self.cfg.yes:
            answer = input(f"Apply rsync with {changes} changes to {dst}? [y/N] ")
            if answer.strip().lower() not in {"y", "yes"}:
                raise FatalError("user declined rsync")
        self.shell.run(self._cmd(src, dst, dry=False, password=password, delete=delete, delete_before=delete_before), check=True)

    def _cmd(
        self,
        src: Path | str,
        dst: Path | str,
        dry: bool,
        password: Path | None,
        delete: bool,
        delete_before: bool = False,
    ) -> list[str | Path]:
        cmd: list[str | Path] = [self.cfg.rsync_bin, "-av", "--itemize-changes", "--info=progress2"]
        if delete_before:
            cmd.append("--delete-before")
        elif delete:
            cmd.append("--delete")
        if dry:
            cmd.append("--dry-run")
        if password:
            cmd.extend(["--password-file", password])
        src_s = str(src)
        if not src_s.endswith("/"):
            src_s += "/"
        cmd.extend([src_s, str(dst)])
        return cmd

    def _password_for(self, *endpoints: Path | str) -> Path | None:
        if any(str(endpoint).startswith("rsync://") for endpoint in endpoints):
            return self.cfg.rsync_pass
        return None

    def _backup_url(self) -> str:
        if not self.cfg.backup_url:
            raise FatalError("--backup-url or BACKUP_URL is required for backup/restore")
        return self.cfg.backup_url

    @staticmethod
    def _count_changes(log: Path) -> int:
        count = 0
        for line in log.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("*deleting "):
                count += 1
            elif re.match(r"^[<>ch\.\*][A-Za-z0-9\.\+][A-Za-z0-9\.\+]{9}\s", line):
                count += 1
        return count
