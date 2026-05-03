from __future__ import annotations

from .common import FatalError
from .config import Config
from .shell import Shell

class Validator:
    def __init__(self, cfg: Config):
        self.cfg = cfg

    def validate(self) -> None:
        self.cfg.work.mkdir(parents=True, exist_ok=True)
        self.cfg.reports.mkdir(parents=True, exist_ok=True)
        if self.cfg.merge_mode not in {"merged", "split", "non-merged"}:
            raise FatalError(f"invalid merge mode: {self.cfg.merge_mode}")
        if self.cfg.merge_mode != "merged":
            raise FatalError("Python-only v2 currently supports --merge-mode merged only")
        if self.cfg.scan_jobs < 1 or self.cfg.compress_jobs < 1:
            raise FatalError("--scan-jobs and --compress-jobs must be >= 1")
        if not self.cfg.images.exists():
            raise FatalError(f"images directory not found: {self.cfg.images}")
        self.cfg.new.mkdir(parents=True, exist_ok=True)
        if not self.cfg.skip_xml and not self.cfg.mame_bin.exists():
            raise FatalError(f"MAME binary not found: {self.cfg.mame_bin}")
        read_only = self.cfg.scan_only or self.cfg.rebuild_plan_only or bool(self.cfg.torrent_plan)
        for exe, needed in ((self.cfg.sevenz_bin, True), (self.cfg.rsync_bin, not read_only)):
            if needed and not Shell.executable_exists(exe):
                raise FatalError(f"required executable not found: {exe}")
        if not read_only and not self.cfg.no_qnap and not self.cfg.rsync_pass.exists():
            raise FatalError(f"rsync password file not found: {self.cfg.rsync_pass}")

