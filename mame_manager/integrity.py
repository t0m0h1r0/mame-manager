from __future__ import annotations

import concurrent.futures
import json
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .runtime import ARCHIVE_EXTS, VERSION, atomic_write_json, iter_visible_files, load_json, now_iso
from .settings import RunConfig
from .reports import ReportManager
from .runtime import Shell


@dataclass(frozen=True)
class IntegrityTarget:
    path: Path
    kind: str
    checker: str | None


class IntegrityChecker:
    def __init__(self, cfg: RunConfig, shell: Shell, report: ReportManager):
        self.cfg = cfg
        self.shell = shell
        self.report = report
        self.cache = load_json(cfg.integrity_cache_file, {"version": VERSION, "files": {}})
        self.lock = threading.Lock()
        self.hits = 0
        self.misses = 0
        self.skipped = 0
        self.dirty = False
        self.chdman_bin = self._resolve_chdman()

    def check_all(self) -> list[dict[str, Any]]:
        targets = self.targets()
        self.report.summary["integrity_files"] = len(targets)
        results: list[dict[str, Any]] = []
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=self.cfg.scan_jobs) as ex:
                futures = [ex.submit(self.check_one, target) for target in targets]
                for i, future in enumerate(concurrent.futures.as_completed(futures), start=1):
                    results.append(future.result())
                    if i % 200 == 0:
                        self.save_if_dirty()
                    if i % 1000 == 0:
                        self.report.summary["integrity_progress"] = f"{i}/{len(targets)}"
                        print(f"[{now_iso()}] checked files {i}/{len(targets)}", flush=True)
        finally:
            self.save_if_dirty()

        results.sort(key=lambda rec: rec["path"])
        broken = [rec for rec in results if rec["status"] == "broken"]
        skipped = [rec for rec in results if rec["status"] == "skipped"]
        self.report.write("integrity_broken_files.txt", self._format_broken(broken))
        self.report.write("integrity_skipped_files.txt", self._format_skipped(skipped))
        self.report.summary["integrity_cache"] = {"hits": self.hits, "misses": self.misses}
        self.report.summary["integrity_broken_files"] = len(broken)
        self.report.summary["integrity_skipped_files"] = len(skipped)
        self.report.summary["integrity_ok_files"] = len(results) - len(broken) - len(skipped)
        print("integrity summary:", flush=True)
        print(f"ok: {self.report.summary['integrity_ok_files']}", flush=True)
        print(f"broken: {len(broken)}", flush=True)
        print(f"skipped: {len(skipped)}", flush=True)
        print(f"cache: hits={self.hits} misses={self.misses}", flush=True)
        return results

    def targets(self) -> list[IntegrityTarget]:
        targets: list[IntegrityTarget] = []
        for root, kind in (
            (self.cfg.images / "roms", "archive"),
            (self.cfg.images / "software_roms", "archive"),
            (self.cfg.new, "archive"),
        ):
            targets.extend(
                IntegrityTarget(path, kind, str(self.cfg.sevenz_bin))
                for path in iter_visible_files(root)
                if path.suffix.lower() in ARCHIVE_EXTS
            )
        chd_checker = str(self.chdman_bin) if not self.cfg.no_chdman and Shell.executable_exists(self.chdman_bin) else None
        for root in (self.cfg.images / "chds", self.cfg.images / "software_chds", self.cfg.new):
            targets.extend(
                IntegrityTarget(path, "chd", chd_checker)
                for path in iter_visible_files(root)
                if path.suffix.lower() == ".chd"
            )
        return sorted(targets, key=lambda target: str(target.path))

    def check_one(self, target: IntegrityTarget) -> dict[str, Any]:
        key = str(target.path.resolve())
        try:
            st = target.path.stat()
        except FileNotFoundError:
            return self._record_broken(key, target, 0, 0, "file disappeared before integrity check")

        with self.lock:
            cached = self.cache.get("files", {}).get(key)
            if (
                cached
                and cached.get("size") == st.st_size
                and cached.get("mtime_ns") == st.st_mtime_ns
                and cached.get("kind") == target.kind
                and cached.get("checker") == target.checker
                and cached.get("status") in {"ok", "broken"}
            ):
                self.hits += 1
                return cached

        if not target.checker:
            with self.lock:
                self.skipped += 1
            return {
                "path": key,
                "kind": target.kind,
                "size": st.st_size,
                "mtime_ns": st.st_mtime_ns,
                "checker": None,
                "status": "skipped",
                "ok": None,
                "error": "chdman not available",
                "checked_at": now_iso(),
            }

        with self.lock:
            self.misses += 1
        if target.kind == "archive":
            cmd: list[str | os.PathLike[str]] = [self.cfg.sevenz_bin, "t", "-bd", target.path]
        else:
            cmd = [target.checker, "verify", "-i", target.path]
        proc = self.shell.capture(cmd, check=False)
        status = "ok" if proc.returncode == 0 else "broken"
        rec = {
            "path": key,
            "kind": target.kind,
            "size": st.st_size,
            "mtime_ns": st.st_mtime_ns,
            "checker": target.checker,
            "status": status,
            "ok": proc.returncode == 0,
            "error": None if proc.returncode == 0 else proc.stdout[-4000:],
            "checked_at": now_iso(),
        }
        with self.lock:
            self.cache.setdefault("files", {})[key] = rec
            self.dirty = True
        return rec

    def save_if_dirty(self) -> None:
        with self.lock:
            if not self.dirty:
                return
            snapshot = json.loads(json.dumps(self.cache))
            self.dirty = False
        atomic_write_json(self.cfg.integrity_cache_file, snapshot)

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

    @staticmethod
    def _record_broken(key: str, target: IntegrityTarget, size: int, mtime_ns: int, error: str) -> dict[str, Any]:
        return {
            "path": key,
            "kind": target.kind,
            "size": size,
            "mtime_ns": mtime_ns,
            "checker": target.checker,
            "status": "broken",
            "ok": False,
            "error": error,
            "checked_at": now_iso(),
        }

    @staticmethod
    def _format_broken(records: list[dict[str, Any]]) -> list[str]:
        lines = []
        for rec in records:
            first_error = (rec.get("error") or "").strip().splitlines()
            suffix = f": {first_error[-1]}" if first_error else ""
            lines.append(f"{rec['path']}{suffix}")
        return lines

    @staticmethod
    def _format_skipped(records: list[dict[str, Any]]) -> list[str]:
        return [f"{rec['path']}: {rec.get('error') or 'skipped'}" for rec in records]
