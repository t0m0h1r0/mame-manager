from __future__ import annotations

import concurrent.futures
import json
import threading
from collections import defaultdict
from pathlib import Path
from typing import Any

from .runtime import (
    ARCHIVE_EXTS,
    SAMPLE_EXTS,
    VERSION,
    atomic_write_json,
    iter_visible_files,
    load_json,
    now_iso,
    sha256_bytes,
)
from .settings import RunConfig
from .reports import ReportManager
from .runtime import Shell

class Fingerprinter:
    def __init__(self, cfg: RunConfig):
        self.cfg = cfg

    def collect(self) -> dict[str, Any]:
        rows = []
        roots = [
            (self.cfg.images / "roms", "arcade_archive", ARCHIVE_EXTS),
            (self.cfg.images / "software_roms", "software_archive", ARCHIVE_EXTS),
            (self.cfg.new, "new_archive", ARCHIVE_EXTS),
            (self.cfg.images / "chds", "arcade_chd", {".chd"}),
            (self.cfg.images / "software_chds", "software_chd", {".chd"}),
            (self.cfg.new, "new_chd", {".chd"}),
            (self.cfg.images / "samples", "sample", SAMPLE_EXTS),
            (self.cfg.new, "new_sample", SAMPLE_EXTS),
        ]
        for root, kind, exts in roots:
            for path in iter_visible_files(root):
                if path.is_file() and path.suffix.lower() in exts:
                    st = path.stat()
                    rows.append({"path": str(path.resolve()), "size": st.st_size, "mtime_ns": st.st_mtime_ns, "kind": kind})
        rows.sort(key=lambda x: (x["kind"], x["path"]))
        payload = json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()
        return {"sha256": sha256_bytes(payload), "files": rows}


class ArchiveIndexer:
    def __init__(self, cfg: RunConfig, shell: Shell, report: ReportManager):
        self.cfg = cfg
        self.shell = shell
        self.report = report
        self.cache = load_json(cfg.archive_index_cache_file, {"version": VERSION, "archives": {}})
        self.lock = threading.Lock()
        self.hits = 0
        self.misses = 0
        self.dirty = False

    def save(self) -> None:
        with self.lock:
            snapshot = json.loads(json.dumps(self.cache))
        atomic_write_json(self.cfg.archive_index_cache_file, snapshot)

    def archive_paths(self) -> list[Path]:
        paths = []
        for root in (self.cfg.images / "roms", self.cfg.images / "software_roms", self.cfg.new):
            paths.extend(p for p in iter_visible_files(root) if p.suffix.lower() in ARCHIVE_EXTS)
        return sorted(paths)

    def index_all(self) -> dict[str, dict[str, Any]]:
        paths = self.archive_paths()
        indexed: dict[str, dict[str, Any]] = {}
        self.report.summary["archive_count"] = len(paths)
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.cfg.scan_jobs) as ex:
            for i, (path, rec) in enumerate(zip(paths, ex.map(self.index_one, paths)), start=1):
                indexed[str(path.resolve())] = rec
                if i % 5000 == 0:
                    if self.dirty:
                        self.save()
                        self.dirty = False
                    self.report.summary["archive_index_progress"] = f"{i}/{len(paths)}"
                    print(f"[{now_iso()}] indexed archives {i}/{len(paths)}", flush=True)
        self.save()
        self.report.summary["archive_index_cache"] = {"hits": self.hits, "misses": self.misses}
        return indexed

    def index_one(self, archive: Path) -> dict[str, Any]:
        st = archive.stat()
        key = str(archive.resolve())
        with self.lock:
            cached = self.cache.get("archives", {}).get(key)
            if cached and cached.get("size") == st.st_size and cached.get("mtime_ns") == st.st_mtime_ns:
                self.hits += 1
                return cached
        self.misses += 1
        proc = self.shell.capture([self.cfg.sevenz_bin, "l", "-slt", archive], check=False)
        ok = proc.returncode == 0
        entries = self._parse_7z_slt(proc.stdout) if ok else []
        rec = {
            "path": key,
            "size": st.st_size,
            "mtime_ns": st.st_mtime_ns,
            "ok": ok,
            "error": None if ok else proc.stdout[-4000:],
            "entries": entries,
            "indexed_at": now_iso(),
        }
        with self.lock:
            self.cache.setdefault("archives", {})[key] = rec
            self.dirty = True
        return rec

    @staticmethod
    def _parse_7z_slt(text: str) -> list[dict[str, Any]]:
        entries = []
        cur: dict[str, str] = {}
        for line in text.splitlines() + [""]:
            if " = " in line:
                key, value = line.split(" = ", 1)
                cur[key] = value
                continue
            if not cur:
                continue
            if cur.get("Folder") != "+" and cur.get("Path") and cur.get("Size"):
                entries.append(
                    {
                        "path": cur["Path"],
                        "name": Path(cur["Path"]).name,
                        "size": int(cur.get("Size") or 0),
                        "crc": (cur.get("CRC") or "").upper() or None,
                    }
                )
            cur = {}
        return entries


class Inventory:
    def __init__(self, archives: dict[str, dict[str, Any]]):
        self.archives = archives
        self.by_crc_size: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
        self.bad_archives: list[str] = []
        self._build()

    def _build(self) -> None:
        for archive_path, rec in self.archives.items():
            if not rec.get("ok"):
                self.bad_archives.append(f"{archive_path}: {rec.get('error') or '7z failed'}")
                continue
            for entry in rec.get("entries", []):
                crc = entry.get("crc")
                if not crc:
                    continue
                item = {"archive": archive_path, **entry}
                self.by_crc_size[(crc.upper(), int(entry["size"]))].append(item)

    def candidates(self, expected: dict[str, Any]) -> list[dict[str, Any]]:
        return self.by_crc_size.get(((expected.get("crc") or "").upper(), int(expected["size"])), [])


def normalize_entries(entries: list[dict[str, Any]], name_key: str = "name") -> list[tuple[str, int, str]]:
    return sorted((Path(e.get(name_key) or e.get("path") or "").name, int(e["size"]), (e.get("crc") or "").upper()) for e in entries)


def archive_matches_target(rec: dict[str, Any], target: dict[str, Any]) -> bool:
    return bool(rec.get("ok")) and normalize_entries(rec.get("entries", []), "path") == normalize_entries(target["entries"], "name")
