from __future__ import annotations

import concurrent.futures
import os
import re
import shutil
from pathlib import Path

from .system import SAMPLE_EXTS, VERSION, atomic_write_json, iter_visible_files, load_json, now_iso, sha1_file
from .config import RunConfig
from .dat_catalog import DatIndex
from .reporting import ReportManager
from .system import Shell


class ChdCache:
    def __init__(self, cfg: RunConfig, shell: Shell, report: ReportManager):
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
            paths.extend(p for p in iter_visible_files(root) if p.suffix.lower() == ".chd")
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

class AssetManager:
    def __init__(self, cfg: RunConfig, report: ReportManager):
        self.cfg = cfg
        self.report = report

    def report_chds(self, index: DatIndex, chds: dict[str, Path]) -> None:
        missing = self.missing_chds(index, chds)
        arcade = missing["arcade"]
        software = missing["software"]
        self.report.write("arcade_missing_chds.txt", arcade)
        self.report.write("software_missing_chds.txt", software)
        self.report.summary["missing_chds"] = {"arcade": len(arcade), "software": len(software)}

    def missing_chds(self, index: DatIndex, chds: dict[str, Path]) -> dict[str, list[str]]:
        return {
            "arcade": [
                f"{x['machine']}/{x['disk']}.chd sha1={x['sha1']}" for x in index.arcade_chds if x["sha1"] not in chds
            ],
            "software": [
                f"{x['softwarelist']}/{x['software']}/{x['disk']}.chd sha1={x['sha1']}"
                for x in index.software_chds
                if x["sha1"] not in chds
            ],
        }

    def place_chds(self, index: DatIndex, chds: dict[str, Path]) -> None:
        self.report_chds(index, chds)
        for item in index.arcade_chds:
            src = chds.get(item["sha1"])
            if not src or not self._is_incoming(src):
                continue
            dst = self.cfg.clean / "chds" / item["machine"] / f"{item['disk']}.chd"
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        for item in index.software_chds:
            src = chds.get(item["sha1"])
            if not src or not self._is_incoming(src):
                continue
            dst = self.cfg.clean / "software_chds" / item["softwarelist"] / item["software"] / f"{item['disk']}.chd"
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)

    def sample_sources(self) -> dict[str, Path]:
        found: dict[str, Path] = {}
        for root in (self.cfg.images / "samples", self.cfg.new):
            for path in iter_visible_files(root):
                if path.is_file() and path.suffix.lower() in SAMPLE_EXTS:
                    found[path.stem] = path
        return found

    def report_samples(self, samples: set[str]) -> None:
        found = self.sample_sources()
        missing = sorted(samples - set(found))
        self.report.write("missing_samples.txt", missing)
        self.report.summary["missing_samples"] = len(missing)

    def place_samples(self, samples: set[str]) -> None:
        found = self.sample_sources()
        missing = sorted(samples - set(found))
        for name in sorted(samples & set(found)):
            src = found[name]
            if not self._is_incoming(src):
                continue
            dst = self.cfg.clean / "samples" / src.name
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        self.report.write("missing_samples.txt", missing)
        self.report.summary["missing_samples"] = len(missing)

    def _is_incoming(self, path: Path) -> bool:
        try:
            path.resolve().relative_to(self.cfg.new.resolve())
        except ValueError:
            return False
        return True
