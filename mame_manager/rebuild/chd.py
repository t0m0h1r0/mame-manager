from __future__ import annotations

import concurrent.futures
import os
import re
from pathlib import Path

from .common import VERSION, atomic_write_json, load_json, now_iso, sha1_file
from .config import Config
from .report import ReportManager
from .shell import Shell

class ChdCache:
    def __init__(self, cfg: Config, shell: Shell, report: ReportManager):
        self.cfg = cfg
        self.shell = shell
        self.report = report
        self.chdman_bin = self._resolve_chdman()
        self.data = load_json(cfg.chd_cache_file, {"version": VERSION, "files": {}})
        self.hits = 0
        self.misses = 0

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

    def save(self) -> None:
        atomic_write_json(self.cfg.chd_cache_file, self.data)

    def scan(self) -> dict[str, Path]:
        paths = []
        for root in (self.cfg.images / "chds", self.cfg.images / "software_chds", self.cfg.new):
            if root.exists():
                paths.extend(p for p in root.rglob("*.chd") if p.is_file())
        by_sha1: dict[str, Path] = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.cfg.scan_jobs) as ex:
            for path, sha1 in ex.map(self._sha1_for, paths):
                if sha1:
                    by_sha1.setdefault(sha1, path)
        self.save()
        self.report.summary["chd_cache"] = {"hits": self.hits, "misses": self.misses, "files": len(paths)}
        return by_sha1

    def _sha1_for(self, path: Path) -> tuple[Path, str | None]:
        st = path.stat()
        key = str(path.resolve())
        cached = self.data.get("files", {}).get(key)
        if cached and cached.get("size") == st.st_size and cached.get("mtime_ns") == st.st_mtime_ns:
            self.hits += 1
            return path, cached.get("sha1")
        self.misses += 1
        sha1 = None
        method = "file"
        if not self.cfg.no_chdman and Shell.executable_exists(self.chdman_bin):
            proc = self.shell.capture([self.chdman_bin, "info", "-i", path], check=False)
            match = re.search(r"SHA1:\s*([0-9a-fA-F]{40})", proc.stdout)
            if proc.returncode == 0 and match:
                sha1 = match.group(1).lower()
                method = "chdman"
        if not sha1:
            sha1 = sha1_file(path)
        self.data.setdefault("files", {})[key] = {
            "size": st.st_size,
            "mtime_ns": st.st_mtime_ns,
            "sha1": sha1,
            "method": method,
            "updated_at": now_iso(),
        }
        return path, sha1
