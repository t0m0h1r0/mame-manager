from __future__ import annotations

import re
from pathlib import Path

from .runtime import FatalError
from .settings import RunConfig
from .reports import ReportManager
from .runtime import Shell

class SyncManager:
    def __init__(self, cfg: RunConfig, shell: Shell, report: ReportManager):
        self.cfg = cfg
        self.shell = shell
        self.report = report

    def sync_all(self) -> None:
        self._sync(self.cfg.clean, self.cfg.images, "rsync_clean_to_images_dry_run.txt")
        if self.cfg.backup_qnap and not self.cfg.no_qnap:
            self._sync(self.cfg.images, self.cfg.backup_url, "rsync_images_to_qnap_dry_run.txt", password=self.cfg.rsync_pass)

    def _sync(self, src: Path, dst: Path | str, log_name: str, password: Path | None = None) -> None:
        dry_log = self.cfg.reports / log_name
        dry_cmd = self._cmd(src, dst, dry=True, password=password)
        self.shell.run_to_log(dry_cmd, dry_log, check=True)
        changes = self._count_changes(dry_log)
        self.report.summary[log_name.replace(".txt", "_changes")] = changes
        if changes >= self.cfg.large_sync_threshold and not self.cfg.force_large_sync:
            raise FatalError(f"rsync dry-run has {changes} changes; rerun with --force-large-sync if intended")
        if not self.cfg.yes:
            answer = input(f"Apply rsync with {changes} changes to {dst}? [y/N] ")
            if answer.strip().lower() not in {"y", "yes"}:
                raise FatalError("user declined rsync")
        self.shell.run(self._cmd(src, dst, dry=False, password=password), check=True)

    def _cmd(self, src: Path, dst: Path | str, dry: bool, password: Path | None) -> list[str | Path]:
        cmd: list[str | Path] = [self.cfg.rsync_bin, "-av", "--delete", "--itemize-changes", "--info=progress2"]
        if dry:
            cmd.append("--dry-run")
        if password:
            cmd.extend(["--password-file", password])
        src_s = str(src)
        if not src_s.endswith("/"):
            src_s += "/"
        cmd.extend([src_s, str(dst)])
        return cmd

    @staticmethod
    def _count_changes(log: Path) -> int:
        count = 0
        for line in log.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("*deleting "):
                count += 1
            elif re.match(r"^[<>ch\.\*][A-Za-z0-9\.\+][A-Za-z0-9\.\+]{9}\s", line):
                count += 1
        return count
