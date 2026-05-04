from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from ..config import RunConfig
from ..reporting import ReportManager
from ..system import ARCHIVE_EXTS, Shell, iter_visible_files


@dataclass(frozen=True)
class IntegrityTarget:
    path: Path
    kind: str
    checker: str | None

    @property
    def key(self) -> str:
        return str(self.path.resolve())


class IntegrityTargetFinder:
    def __init__(self, cfg: RunConfig, report: ReportManager):
        self.cfg = cfg
        self.report = report

    def targets(self) -> list[IntegrityTarget]:
        targets = self.archive_targets()
        targets.extend(self.chd_targets())
        return sorted(targets, key=lambda target: str(target.path))

    def archive_targets(self) -> list[IntegrityTarget]:
        targets: list[IntegrityTarget] = []
        for root in (self.cfg.images / "roms", self.cfg.images / "software_roms", self.cfg.new):
            targets.extend(
                IntegrityTarget(path, "archive", str(self.cfg.sevenz_bin))
                for path in iter_visible_files(root)
                if path.suffix.lower() in ARCHIVE_EXTS
            )
        return targets

    def chd_targets(self) -> list[IntegrityTarget]:
        chdman = self._resolve_chdman()
        checker = str(chdman) if not self.cfg.no_chdman and Shell.executable_exists(chdman) else None
        targets: list[IntegrityTarget] = []
        for root in (self.cfg.images / "chds", self.cfg.images / "software_chds", self.cfg.new):
            targets.extend(
                IntegrityTarget(path, "chd", checker)
                for path in iter_visible_files(root)
                if path.suffix.lower() == ".chd"
            )
        return targets

    def _resolve_chdman(self) -> str | Path:
        if self.cfg.no_chdman:
            return self.cfg.chdman_bin
        if Shell.executable_exists(self.cfg.chdman_bin):
            return self.cfg.chdman_bin
        sibling = self.cfg.mame_bin.parent / "chdman"
        if sibling.exists() and os.access(sibling, os.X_OK):
            self.report.note(f"using chdman at {sibling}")
            return sibling
        return self.cfg.chdman_bin
