from __future__ import annotations

import concurrent.futures
from typing import Any

from .integrity_cache import IntegrityCache
from .integrity_runner import IntegrityRunner
from .integrity_targets import IntegrityTargetFinder
from .reports import ReportManager
from .runtime import Shell, now_iso
from .settings import RunConfig


SAVE_INTERVAL = 50
PROGRESS_INTERVAL = 1000


class IntegrityChecker:
    def __init__(self, cfg: RunConfig, shell: Shell, report: ReportManager):
        self.cfg = cfg
        self.report = report
        self.cache = IntegrityCache(cfg.integrity_cache_file)
        self.finder = IntegrityTargetFinder(cfg, report)
        self.runner = IntegrityRunner(cfg, shell, self.cache)

    def check_all(self) -> list[dict[str, Any]]:
        targets = self.finder.targets()
        self.report.summary["integrity_files"] = len(targets)
        results: list[dict[str, Any]] = []
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=self.cfg.scan_jobs) as ex:
                futures = [ex.submit(self.runner.check, target) for target in targets]
                for i, future in enumerate(concurrent.futures.as_completed(futures), start=1):
                    results.append(future.result())
                    self._checkpoint(i, len(targets))
        finally:
            self.cache.save_if_dirty()

        self._report(results)
        return results

    def _checkpoint(self, checked: int, total: int) -> None:
        if checked % SAVE_INTERVAL == 0:
            self.cache.save_if_dirty()
        if checked % PROGRESS_INTERVAL == 0:
            self.report.summary["integrity_progress"] = f"{checked}/{total}"
            print(f"[{now_iso()}] checked files {checked}/{total}", flush=True)

    def _report(self, results: list[dict[str, Any]]) -> None:
        results.sort(key=lambda rec: rec["path"])
        broken = [rec for rec in results if rec["status"] == "broken"]
        skipped = [rec for rec in results if rec["status"] == "skipped"]
        ok_count = len(results) - len(broken) - len(skipped)

        self.report.write("integrity_broken_files.txt", self._format_broken(broken))
        self.report.write("integrity_skipped_files.txt", self._format_skipped(skipped))
        self.report.summary["integrity_cache"] = self.cache.summary()
        self.report.summary["integrity_broken_files"] = len(broken)
        self.report.summary["integrity_skipped_files"] = len(skipped)
        self.report.summary["integrity_ok_files"] = ok_count

        print("integrity summary:", flush=True)
        print(f"ok: {ok_count}", flush=True)
        print(f"broken: {len(broken)}", flush=True)
        print(f"skipped: {len(skipped)}", flush=True)
        print(f"cache: hits={self.cache.hits} misses={self.cache.misses}", flush=True)

    @staticmethod
    def _format_broken(records: list[dict[str, Any]]) -> list[str]:
        lines = []
        for rec in records:
            error_lines = (rec.get("error") or "").strip().splitlines()
            suffix = f": {error_lines[-1]}" if error_lines else ""
            lines.append(f"{rec['path']}{suffix}")
        return lines

    @staticmethod
    def _format_skipped(records: list[dict[str, Any]]) -> list[str]:
        return [f"{rec['path']}: {rec.get('error') or 'skipped'}" for rec in records]
