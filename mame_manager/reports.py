from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from .runtime import VERSION, now_iso
from .settings import RunConfig

class ReportManager:
    def __init__(self, cfg: RunConfig):
        self.cfg = cfg
        self.cfg.reports.mkdir(parents=True, exist_ok=True)
        self.summary: dict[str, Any] = {
            "version": VERSION,
            "started_at": now_iso(),
            "scan_only": cfg.scan_only,
            "rebuild_plan_only": cfg.rebuild_plan_only,
            "merge_mode": cfg.merge_mode,
            "engine": "python-only",
            "notes": [],
        }

    def phase(self, text: str) -> None:
        self.summary["phase"] = text
        print(f"[{now_iso()}] {text}", flush=True)

    def note(self, text: str) -> None:
        self.summary.setdefault("notes", []).append(text)

    def write(self, name: str, lines: Iterable[str] | str) -> Path:
        path = self.cfg.reports / name
        text = lines if isinstance(lines, str) else "\n".join(lines)
        path.write_text(text.rstrip() + ("\n" if text else ""), encoding="utf-8")
        return path

    def finish(self, stopped_reason: str | None = None) -> None:
        self.summary["finished_at"] = now_iso()
        if stopped_reason:
            self.summary["stopped_reason"] = stopped_reason
        lines = []
        for key in sorted(self.summary):
            val = self.summary[key]
            if isinstance(val, (dict, list)):
                lines.append(f"{key}: {json.dumps(val, ensure_ascii=False, sort_keys=True)}")
            else:
                lines.append(f"{key}: {val}")
        self.write("summary.txt", lines)

    def print_scan_summary(self) -> None:
        print("scan summary:", flush=True)
        self._print_json_summary("rom_sets")
        self._print_json_summary("rom_file_entries")
        self._print_json_summary("missing_rom_entries")
        self._print_json_summary("missing_chds")
        self._print_plain_summary("missing_samples")
        self._print_plain_summary("archive_errors")
        self._print_json_summary("qbittorrent")

    def _print_json_summary(self, key: str) -> None:
        if key in self.summary:
            print(f"{key}: {json.dumps(self.summary[key], ensure_ascii=False, sort_keys=True)}", flush=True)

    def _print_plain_summary(self, key: str) -> None:
        if key in self.summary:
            print(f"{key}: {self.summary[key]}", flush=True)
