from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from .common import VERSION, now_iso
from .config import Config

class ReportManager:
    def __init__(self, cfg: Config):
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

