from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from .integrity_targets import IntegrityTarget
from .runtime import VERSION, atomic_write_json, load_json


class IntegrityCache:
    def __init__(self, path: Path):
        self.path = path
        self.data = load_json(path, {"version": VERSION, "files": {}})
        self.lock = threading.Lock()
        self.hits = 0
        self.misses = 0
        self.dirty = False

    def lookup(self, target: IntegrityTarget, size: int, mtime_ns: int) -> dict[str, Any] | None:
        with self.lock:
            cached = self.data.get("files", {}).get(target.key)
            if self._matches(cached, target, size, mtime_ns):
                self.hits += 1
                return cached
        return None

    def mark_miss(self) -> None:
        with self.lock:
            self.misses += 1

    def store(self, record: dict[str, Any]) -> None:
        with self.lock:
            self.data.setdefault("files", {})[record["path"]] = record
            self.dirty = True

    def save_if_dirty(self) -> None:
        with self.lock:
            if not self.dirty:
                return
            snapshot = json.loads(json.dumps(self.data))
            self.dirty = False
        atomic_write_json(self.path, snapshot)

    def summary(self) -> dict[str, int]:
        return {"hits": self.hits, "misses": self.misses}

    @staticmethod
    def _matches(cached: dict[str, Any] | None, target: IntegrityTarget, size: int, mtime_ns: int) -> bool:
        return bool(
            cached
            and cached.get("size") == size
            and cached.get("mtime_ns") == mtime_ns
            and cached.get("kind") == target.kind
            and cached.get("checker") == target.checker
            and cached.get("status") in {"ok", "broken"}
        )
