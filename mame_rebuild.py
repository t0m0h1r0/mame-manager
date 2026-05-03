#!/usr/bin/env python3
"""
Python-only MAME images auditor/rebuilder.

The script does not use Igir.  It treats MAME XML and software-list XML files as
the source of truth, indexes ZIP/7z contents with 7z, and only applies changes to
images/ after building work_mame/clean_images and passing rsync dry-run guards.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable
from xml.etree import ElementTree as ET


VERSION = 2
ARCHIVE_EXTS = {".zip", ".7z"}
SAMPLE_EXTS = {".wav", ".flac", ".mp3"}


class FatalError(RuntimeError):
    pass


def now_iso() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def parse_int(text: str) -> int:
    return int(text, 0)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def sha1_file(path: Path) -> str:
    h = hashlib.sha1()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def atomic_write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as f:
        json.dump(data, f, indent=2, sort_keys=True)
        f.write("\n")
        tmp = Path(f.name)
    tmp.replace(path)


def load_json(path: Path, default: Any) -> Any:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def quote_cmd(cmd: Iterable[str | os.PathLike[str]]) -> str:
    import shlex

    return " ".join(shlex.quote(str(x)) for x in cmd)


def safe_rmtree(path: Path, work: Path) -> None:
    rp = path.resolve()
    rw = work.resolve()
    if rp == rw or rw not in rp.parents:
        raise FatalError(f"refusing to remove unsafe path: {path}")
    if path.exists():
        shutil.rmtree(path)


@dataclass(frozen=True)
class Config:
    mame_bin: Path
    images: Path
    new: Path
    work: Path
    rsync_pass: Path
    backup_url: str
    merge_mode: str
    scan_jobs: int
    compress_jobs: int
    scan_only: bool
    rebuild_plan_only: bool
    skip_xml: bool
    no_qnap: bool
    rebuild_mode: str
    sevenz_bin: str
    rsync_bin: str
    chdman_bin: str
    no_chdman: bool
    yes: bool
    force_large_sync: bool
    large_sync_threshold: int

    @property
    def clean(self) -> Path:
        return self.work / "clean_images"

    @property
    def raw(self) -> Path:
        return self.work / "raw"

    @property
    def reports(self) -> Path:
        return self.work / "reports"

    @property
    def arcade_xml(self) -> Path:
        return self.work / "mame.xml"

    @property
    def software_xml(self) -> Path:
        return self.work / "software.xml"

    @property
    def archive_index_cache_file(self) -> Path:
        return self.work / "archive_index_cache.json"

    @property
    def chd_cache_file(self) -> Path:
        return self.work / "chd_cache.json"

    @property
    def scan_cache_file(self) -> Path:
        return self.work / "scan_cache.json"

    @property
    def rebuild_cache_file(self) -> Path:
        return self.work / "rebuild_cache.json"

    @property
    def target_manifest_file(self) -> Path:
        return self.work / "target_manifest.json"


class Shell:
    def capture(self, cmd: list[str | os.PathLike[str]], cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(x) for x in cmd],
            cwd=str(cwd) if cwd else None,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=check,
        )

    def run(self, cmd: list[str | os.PathLike[str]], cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
        print("$ " + quote_cmd(cmd), flush=True)
        return self.capture(cmd, cwd=cwd, check=check)

    def run_to_log(self, cmd: list[str | os.PathLike[str]], log: Path, cwd: Path | None = None, check: bool = True) -> int:
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("w", encoding="utf-8") as f:
            f.write("$ " + quote_cmd(cmd) + "\n\n")
            proc = subprocess.run([str(x) for x in cmd], cwd=str(cwd) if cwd else None, text=True, stdout=f, stderr=subprocess.STDOUT)
        if check and proc.returncode != 0:
            raise FatalError(f"command failed ({proc.returncode}); see {log}")
        return proc.returncode

    @staticmethod
    def executable_exists(name: str | Path) -> bool:
        s = str(name)
        if "/" in s:
            return Path(s).exists() and os.access(s, os.X_OK)
        return shutil.which(s) is not None


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


class DatExtractor:
    def __init__(self, cfg: Config, shell: Shell):
        self.cfg = cfg
        self.shell = shell

    def extract(self) -> None:
        self.cfg.work.mkdir(parents=True, exist_ok=True)
        if self.cfg.skip_xml:
            missing = [p for p in (self.cfg.arcade_xml, self.cfg.software_xml) if not p.exists()]
            if missing:
                raise FatalError("--skip-xml used but XML file is missing: " + ", ".join(map(str, missing)))
            return
        if not self.cfg.mame_bin.exists():
            raise FatalError(f"MAME binary not found: {self.cfg.mame_bin}")
        self._write_command([self.cfg.mame_bin, "-listxml"], self.cfg.arcade_xml)
        self._build_software_xml_from_hash()

    def _write_command(self, cmd: list[str | Path], out: Path) -> None:
        tmp = out.with_suffix(out.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            proc = subprocess.run([str(x) for x in cmd], stdout=f, stderr=subprocess.PIPE, text=True)
        if proc.returncode != 0:
            tmp.unlink(missing_ok=True)
            raise FatalError(f"XML extraction failed: {quote_cmd(cmd)}\n{proc.stderr}")
        tmp.replace(out)

    def _build_software_xml_from_hash(self) -> None:
        hash_dir = self.cfg.mame_bin.parent / "hash"
        if not hash_dir.is_dir():
            raise FatalError(f"MAME hash directory not found: {hash_dir}")
        root = ET.Element("softwarelists")
        count = 0
        for xml in sorted(hash_dir.glob("*.xml")):
            try:
                subroot = ET.parse(xml).getroot()
            except ET.ParseError as e:
                raise FatalError(f"failed to parse software list {xml}: {e}") from e
            if subroot.tag == "softwarelist":
                root.append(subroot)
                count += 1
        if not count:
            raise FatalError(f"no software list XML files found in {hash_dir}")
        tmp = self.cfg.software_xml.with_suffix(".xml.tmp")
        ET.ElementTree(root).write(tmp, encoding="utf-8", xml_declaration=True)
        tmp.replace(self.cfg.software_xml)


class DatIndex:
    def __init__(self, arcade_xml: Path, software_xml: Path, merge_mode: str):
        self.arcade_xml = arcade_xml
        self.software_xml = software_xml
        self.merge_mode = merge_mode
        self.arcade_targets: dict[str, dict[str, Any]] = {}
        self.software_targets: dict[str, dict[str, Any]] = {}
        self.arcade_chds: list[dict[str, str]] = []
        self.software_chds: list[dict[str, str]] = []
        self.samples: set[str] = set()

    def parse(self) -> "DatIndex":
        self._parse_arcade()
        self._parse_software()
        return self

    def _parse_arcade(self) -> None:
        for _, elem in ET.iterparse(self.arcade_xml, events=("end",)):
            if elem.tag != "machine":
                continue
            machine = elem.attrib.get("name")
            if not machine:
                elem.clear()
                continue
            entries = []
            for rom in elem.findall("rom"):
                if rom.attrib.get("status") == "nodump":
                    continue
                name = rom.attrib.get("name")
                size = rom.attrib.get("size")
                crc = rom.attrib.get("crc")
                if name and size and crc:
                    entries.append({"name": name, "size": parse_int(size), "crc": crc.upper(), "sha1": rom.attrib.get("sha1")})
            if entries:
                self.arcade_targets[f"roms/{machine}.7z"] = {"kind": "arcade", "machine": machine, "entries": entries}
            for disk in elem.findall("disk"):
                if disk.attrib.get("status") == "nodump":
                    continue
                name = disk.attrib.get("name")
                sha1 = disk.attrib.get("sha1")
                if name and sha1:
                    self.arcade_chds.append({"machine": machine, "disk": name, "sha1": sha1.lower()})
            for sample in elem.findall("sample"):
                name = sample.attrib.get("name")
                if name:
                    self.samples.add(name)
            elem.clear()

    def _parse_software(self) -> None:
        root = ET.parse(self.software_xml).getroot()
        swlists = [root] if root.tag == "softwarelist" else root.findall("softwarelist")
        for swlist in swlists:
            list_name = swlist.attrib.get("name")
            if not list_name:
                continue
            for software in swlist.findall("software"):
                sw_name = software.attrib.get("name")
                if not sw_name:
                    continue
                entries = []
                for rom in software.findall(".//rom"):
                    if rom.attrib.get("status") == "nodump":
                        continue
                    name = rom.attrib.get("name")
                    size = rom.attrib.get("size")
                    crc = rom.attrib.get("crc")
                    if name and size and crc:
                        entries.append({"name": name, "size": parse_int(size), "crc": crc.upper(), "sha1": rom.attrib.get("sha1")})
                if entries:
                    rel = f"software_roms/{list_name}/{sw_name}.7z"
                    self.software_targets[rel] = {
                        "kind": "software",
                        "softwarelist": list_name,
                        "software": sw_name,
                        "entries": entries,
                    }
                for disk in software.findall(".//disk"):
                    if disk.attrib.get("status") == "nodump":
                        continue
                    name = disk.attrib.get("name")
                    sha1 = disk.attrib.get("sha1")
                    if name and sha1:
                        self.software_chds.append(
                            {"softwarelist": list_name, "software": sw_name, "disk": name, "sha1": sha1.lower()}
                        )

    def manifest(self) -> dict[str, Any]:
        return {
            "version": VERSION,
            "merge_mode": self.merge_mode,
            "arcade": self.arcade_targets,
            "software": self.software_targets,
        }

    def all_targets(self) -> dict[str, dict[str, Any]]:
        return {**self.arcade_targets, **self.software_targets}


class Fingerprinter:
    def __init__(self, cfg: Config):
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
            if not root.exists():
                continue
            for path in root.rglob("*"):
                if path.is_file() and path.suffix.lower() in exts:
                    st = path.stat()
                    rows.append({"path": str(path.resolve()), "size": st.st_size, "mtime_ns": st.st_mtime_ns, "kind": kind})
        rows.sort(key=lambda x: (x["kind"], x["path"]))
        payload = json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()
        return {"sha256": sha256_bytes(payload), "files": rows}


class ArchiveIndexer:
    def __init__(self, cfg: Config, shell: Shell, report: ReportManager):
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
            if not root.exists():
                continue
            paths.extend(p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in ARCHIVE_EXTS)
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


class Auditor:
    def __init__(self, cfg: Config, report: ReportManager):
        self.cfg = cfg
        self.report = report

    def audit_roms(self, index: DatIndex, inventory: Inventory) -> dict[str, list[str]]:
        arcade = self._audit_targets(index.arcade_targets, inventory)
        software = self._audit_targets(index.software_targets, inventory)
        self.report.write("arcade_missing_roms.txt", arcade["missing_entries"])
        self.report.write("software_missing_roms.txt", software["missing_entries"])
        self.report.write("arcade_complete_sets.txt", arcade["complete_sets"])
        self.report.write("software_complete_sets.txt", software["complete_sets"])
        self.report.write("arcade_incomplete_sets.txt", arcade["incomplete_sets"])
        self.report.write("software_incomplete_sets.txt", software["incomplete_sets"])
        self.report.write("archive_errors.txt", inventory.bad_archives)
        self.report.summary["rom_sets"] = {
            "arcade": {
                "total": arcade["total_sets"],
                "complete": len(arcade["complete_sets"]),
                "incomplete": len(arcade["incomplete_sets"]),
            },
            "software": {
                "total": software["total_sets"],
                "complete": len(software["complete_sets"]),
                "incomplete": len(software["incomplete_sets"]),
            },
            "combined": {
                "total": arcade["total_sets"] + software["total_sets"],
                "complete": len(arcade["complete_sets"]) + len(software["complete_sets"]),
                "incomplete": len(arcade["incomplete_sets"]) + len(software["incomplete_sets"]),
            },
        }
        self.report.summary["rom_file_entries"] = {
            "arcade": {
                "total": arcade["total_entries"],
                "present": arcade["present_entries"],
                "missing": len(arcade["missing_entries"]),
            },
            "software": {
                "total": software["total_entries"],
                "present": software["present_entries"],
                "missing": len(software["missing_entries"]),
            },
            "combined": {
                "total": arcade["total_entries"] + software["total_entries"],
                "present": arcade["present_entries"] + software["present_entries"],
                "missing": len(arcade["missing_entries"]) + len(software["missing_entries"]),
            },
        }
        self.report.summary["missing_rom_entries"] = {
            "arcade": len(arcade["missing_entries"]),
            "software": len(software["missing_entries"]),
        }
        self.report.summary["archive_errors"] = len(inventory.bad_archives)
        return {"arcade": arcade["missing_entries"], "software": software["missing_entries"]}

    def _audit_targets(self, targets: dict[str, dict[str, Any]], inventory: Inventory) -> dict[str, Any]:
        missing_entries = []
        complete_sets = []
        incomplete_sets = []
        total_entries = 0
        present_entries = 0
        for rel, target in sorted(targets.items()):
            target_missing = []
            for entry in target["entries"]:
                total_entries += 1
                if not inventory.candidates(entry):
                    line = f"{rel}: {entry['name']} size={entry['size']} crc={entry['crc']}"
                    missing_entries.append(line)
                    target_missing.append(line)
                else:
                    present_entries += 1
            if target_missing:
                incomplete_sets.append(f"{rel}: missing {len(target_missing)}/{len(target['entries'])}")
            else:
                complete_sets.append(rel)
        return {
            "total_sets": len(targets),
            "total_entries": total_entries,
            "present_entries": present_entries,
            "missing_entries": missing_entries,
            "complete_sets": complete_sets,
            "incomplete_sets": incomplete_sets,
        }


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


class AssetManager:
    def __init__(self, cfg: Config, report: ReportManager):
        self.cfg = cfg
        self.report = report

    def report_chds(self, index: DatIndex, chds: dict[str, Path]) -> None:
        arcade = [f"{x['machine']}/{x['disk']}.chd sha1={x['sha1']}" for x in index.arcade_chds if x["sha1"] not in chds]
        software = [
            f"{x['softwarelist']}/{x['software']}/{x['disk']}.chd sha1={x['sha1']}"
            for x in index.software_chds
            if x["sha1"] not in chds
        ]
        self.report.write("arcade_missing_chds.txt", arcade)
        self.report.write("software_missing_chds.txt", software)
        self.report.summary["missing_chds"] = {"arcade": len(arcade), "software": len(software)}

    def place_chds(self, index: DatIndex, chds: dict[str, Path]) -> None:
        self.report_chds(index, chds)
        for item in index.arcade_chds:
            src = chds.get(item["sha1"])
            if not src:
                continue
            dst = self.cfg.clean / "chds" / item["machine"] / f"{item['disk']}.chd"
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        for item in index.software_chds:
            src = chds.get(item["sha1"])
            if not src:
                continue
            dst = self.cfg.clean / "software_chds" / item["softwarelist"] / item["software"] / f"{item['disk']}.chd"
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)

    def sample_sources(self) -> dict[str, Path]:
        found: dict[str, Path] = {}
        for root in (self.cfg.images / "samples", self.cfg.new):
            if not root.exists():
                continue
            for path in root.rglob("*"):
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
            dst = self.cfg.clean / "samples" / src.name
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        self.report.write("missing_samples.txt", missing)
        self.report.summary["missing_samples"] = len(missing)


class Rebuilder:
    def __init__(self, cfg: Config, shell: Shell, report: ReportManager, indexer: ArchiveIndexer):
        self.cfg = cfg
        self.shell = shell
        self.report = report
        self.indexer = indexer
        self.reused = 0
        self.created = 0

    def prepare(self) -> None:
        safe_rmtree(self.cfg.clean, self.cfg.work)
        safe_rmtree(self.cfg.raw, self.cfg.work)
        for name in ("roms", "software_roms", "chds", "software_chds", "samples"):
            (self.cfg.clean / name).mkdir(parents=True, exist_ok=True)
        self.cfg.raw.mkdir(parents=True, exist_ok=True)

    def rebuild(self, index: DatIndex, inventory: Inventory, manifest_hash: str, input_fp: str, dat_hash: str) -> None:
        action = self._action(manifest_hash, input_fp, dat_hash)
        self.report.summary["rebuild_action"] = action
        self.prepare()
        if action == "skip":
            self.report.note("rebuild cache matched, but clean_images is rebuilt from reusable archives before sync")
        failures = []
        for rel, target in sorted(index.all_targets().items()):
            if self._reuse_existing(rel, target):
                continue
            ok, reason = self._build_target(rel, target, inventory)
            if not ok:
                failures.append(f"{rel}: {reason}")
        self.report.write("rebuild_failures.txt", failures)
        self.report.summary["existing_7z_reused"] = self.reused
        self.report.summary["new_7z_created"] = self.created
        self.report.summary["rebuild_failures"] = len(failures)
        if failures:
            raise FatalError(f"failed to build {len(failures)} ROM package(s); refusing to sync")
        atomic_write_json(
            self.cfg.rebuild_cache_file,
            {
                "version": VERSION,
                "dat_sha256": dat_hash,
                "input_fingerprint": input_fp,
                "target_manifest_sha256": manifest_hash,
                "completed_at": now_iso(),
            },
        )

    def plan(self, index: DatIndex, inventory: Inventory) -> dict[str, int]:
        reusable = []
        buildable = []
        missing = []
        for rel, target in sorted(index.all_targets().items()):
            if self._can_reuse_existing(rel, target):
                reusable.append(rel)
                continue
            missing_entries = [
                f"{entry['name']} size={entry['size']} crc={entry['crc']}"
                for entry in target["entries"]
                if not inventory.candidates(entry)
            ]
            if missing_entries:
                missing.append(f"{rel}: " + "; ".join(missing_entries[:10]))
            else:
                buildable.append(rel)
        self.report.write("rebuild_plan_reusable.txt", reusable)
        self.report.write("rebuild_plan_buildable.txt", buildable)
        self.report.write("rebuild_plan_missing.txt", missing)
        result = {"reusable": len(reusable), "buildable": len(buildable), "missing": len(missing)}
        self.report.summary["rebuild_plan"] = result
        return result

    def _action(self, manifest_hash: str, input_fp: str, dat_hash: str) -> str:
        if self.cfg.rebuild_mode != "auto":
            return self.cfg.rebuild_mode
        cache = load_json(self.cfg.rebuild_cache_file, {})
        if (
            cache.get("dat_sha256") == dat_hash
            and cache.get("input_fingerprint") == input_fp
            and cache.get("target_manifest_sha256") == manifest_hash
        ):
            return "skip"
        return "full"

    def _reuse_existing(self, rel: str, target: dict[str, Any]) -> bool:
        src = self._existing_path(rel)
        if not src.exists():
            return False
        rec = self.indexer.index_one(src)
        if not archive_matches_target(rec, target):
            return False
        dst = self.cfg.clean / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        self.reused += 1
        return True

    def _can_reuse_existing(self, rel: str, target: dict[str, Any]) -> bool:
        src = self._existing_path(rel)
        if not src.exists():
            return False
        rec = self.indexer.index_one(src)
        return archive_matches_target(rec, target)

    def _existing_path(self, rel: str) -> Path:
        rel_path = Path(rel)
        if rel_path.parts[0] == "roms":
            return self.cfg.images / "roms" / rel_path.name
        return self.cfg.images / rel

    def _build_target(self, rel: str, target: dict[str, Any], inventory: Inventory) -> tuple[bool, str]:
        staging = self.cfg.raw / rel.replace("/", "__").replace(".7z", "")
        safe_rmtree(staging, self.cfg.work)
        staging.mkdir(parents=True, exist_ok=True)
        used = []
        for entry in target["entries"]:
            candidates = inventory.candidates(entry)
            if not candidates:
                return False, f"missing {entry['name']} size={entry['size']} crc={entry['crc']}"
            candidate = candidates[0]
            if not self._extract_entry(candidate, staging, entry["name"]):
                return False, f"failed to extract {entry['name']} from {candidate['archive']}"
            used.append(candidate["archive"])
        dst = self.cfg.clean / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        tmp = dst.with_suffix(".7z.tmp")
        tmp.unlink(missing_ok=True)
        names = sorted(p.name for p in staging.iterdir() if p.is_file())
        if not names:
            return False, "no staged files"
        self.shell.run([self.cfg.sevenz_bin, "a", "-t7z", "-mx=9", "-mmt=1", tmp.resolve(), *names], cwd=staging)
        tmp.replace(dst)
        rec = self.indexer.index_one(dst)
        if not archive_matches_target(rec, target):
            return False, "created archive does not match expected entries"
        self.created += 1
        return True, "ok"

    def _extract_entry(self, candidate: dict[str, Any], staging: Path, out_name: str) -> bool:
        archive = Path(candidate["archive"])
        entry_path = candidate["path"]
        tmpdir = staging / ".extract_tmp"
        safe_rmtree(tmpdir, self.cfg.work)
        tmpdir.mkdir(parents=True, exist_ok=True)
        proc = self.shell.capture([self.cfg.sevenz_bin, "e", "-y", f"-o{tmpdir}", archive, entry_path], check=False)
        if proc.returncode != 0:
            return False
        extracted = tmpdir / Path(entry_path).name
        if not extracted.exists():
            files = [p for p in tmpdir.iterdir() if p.is_file()]
            if len(files) != 1:
                return False
            extracted = files[0]
        dst = staging / Path(out_name).name
        if dst.exists():
            dst.unlink()
        extracted.replace(dst)
        safe_rmtree(tmpdir, self.cfg.work)
        return True


class SyncManager:
    def __init__(self, cfg: Config, shell: Shell, report: ReportManager):
        self.cfg = cfg
        self.shell = shell
        self.report = report

    def sync_all(self) -> None:
        self._sync(self.cfg.clean, self.cfg.images, "rsync_clean_to_images_dry_run.txt")
        if not self.cfg.no_qnap:
            self._sync(self.cfg.images, self.cfg.backup_url, "rsync_images_to_qnap_dry_run.txt", password=self.cfg.rsync_pass)

    def _sync(self, src: Path, dst: Path | str, log_name: str, password: Path | None = None) -> None:
        dry_log = self.cfg.reports / log_name
        dry_cmd = self._cmd(src, dst, dry=True, password=password)
        self.shell.run_to_log(dry_cmd, dry_log, check=True)
        changes = self._count_changes(dry_log)
        self.report.summary[log_name.replace(".txt", "_changes")] = changes
        if changes >= self.cfg.large_sync_threshold and not self.cfg.force_large_sync:
            raise FatalError(f"rsync dry-run has {changes} changes; rerun with --force-large-sync if intended")
        if not self.cfg.yes:
            answer = input(f"Apply rsync with {changes} changes to {dst}? [y/N] ")
            if answer.strip().lower() not in {"y", "yes"}:
                raise FatalError("user declined rsync")
        self.shell.run(self._cmd(src, dst, dry=False, password=password), check=True)

    def _cmd(self, src: Path, dst: Path | str, dry: bool, password: Path | None) -> list[str | Path]:
        cmd: list[str | Path] = [self.cfg.rsync_bin, "-av", "--delete", "--itemize-changes", "--info=progress2"]
        if dry:
            cmd.append("--dry-run")
        if password:
            cmd.extend(["--password-file", password])
        src_s = str(src)
        if not src_s.endswith("/"):
            src_s += "/"
        cmd.extend([src_s, str(dst)])
        return cmd

    @staticmethod
    def _count_changes(log: Path) -> int:
        count = 0
        for line in log.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("*deleting "):
                count += 1
            elif re.match(r"^[<>ch\.\*][A-Za-z0-9\.\+][A-Za-z0-9\.\+]{9}\s", line):
                count += 1
        return count


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
        read_only = self.cfg.scan_only or self.cfg.rebuild_plan_only
        for exe, needed in ((self.cfg.sevenz_bin, True), (self.cfg.rsync_bin, not read_only)):
            if needed and not Shell.executable_exists(exe):
                raise FatalError(f"required executable not found: {exe}")
        if not read_only and not self.cfg.no_qnap and not self.cfg.rsync_pass.exists():
            raise FatalError(f"rsync password file not found: {self.cfg.rsync_pass}")


class MameRebuildApp:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.shell = Shell()
        self.report = ReportManager(cfg)

    def run(self) -> int:
        signal.signal(signal.SIGTERM, self._sigterm)
        try:
            self.report.phase("validate")
            Validator(self.cfg).validate()
            self.report.phase("extract DAT")
            DatExtractor(self.cfg, self.shell).extract()
            self.report.phase("parse DAT")
            index = DatIndex(self.cfg.arcade_xml, self.cfg.software_xml, self.cfg.merge_mode).parse()
            manifest = index.manifest()
            manifest_payload = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
            manifest_hash = sha256_bytes(manifest_payload)
            dat_hash = sha256_bytes((sha256_file(self.cfg.arcade_xml) + sha256_file(self.cfg.software_xml)).encode())
            self.report.summary["target_counts"] = {
                "arcade_roms": len(index.arcade_targets),
                "software_roms": len(index.software_targets),
                "arcade_chds": len(index.arcade_chds),
                "software_chds": len(index.software_chds),
                "samples": len(index.samples),
            }
            if not self.cfg.scan_only:
                atomic_write_json(self.cfg.target_manifest_file, manifest)
            self.report.phase("fingerprint inputs")
            fp = Fingerprinter(self.cfg).collect()
            self.report.summary["input_file_count"] = len(fp["files"])
            self.report.summary["input_fingerprint"] = fp["sha256"]
            self.report.phase("index archives")
            indexer = ArchiveIndexer(self.cfg, self.shell, self.report)
            archives = indexer.index_all()
            inventory = Inventory(archives)
            self.report.phase("audit ROMs")
            Auditor(self.cfg, self.report).audit_roms(index, inventory)
            self.report.phase("scan CHDs")
            chds = ChdCache(self.cfg, self.shell, self.report).scan()
            assets = AssetManager(self.cfg, self.report)
            if self.cfg.scan_only:
                assets.report_chds(index, chds)
                assets.report_samples(index.samples)
                self._write_scan_cache(dat_hash, fp["sha256"], manifest_hash)
            elif self.cfg.rebuild_plan_only:
                self.report.phase("plan rebuild")
                Rebuilder(self.cfg, self.shell, self.report, indexer).plan(index, inventory)
                assets.report_chds(index, chds)
                assets.report_samples(index.samples)
            else:
                if inventory.bad_archives:
                    raise FatalError(f"{len(inventory.bad_archives)} archive(s) failed 7z indexing; refusing rebuild")
                self.report.phase("rebuild clean_images")
                Rebuilder(self.cfg, self.shell, self.report, indexer).rebuild(index, inventory, manifest_hash, fp["sha256"], dat_hash)
                assets.place_chds(index, chds)
                assets.place_samples(index.samples)
                self.report.phase("rsync")
                SyncManager(self.cfg, self.shell, self.report).sync_all()
            self.report.phase("done")
            self.report.finish()
            return 0
        except FatalError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            self.report.finish(str(e))
            return 2
        except KeyboardInterrupt:
            self.report.finish("interrupted")
            return 130

    def _sigterm(self, signum: int, frame: Any) -> None:
        raise FatalError("terminated by SIGTERM")

    def _write_scan_cache(self, dat_hash: str, input_fp: str, manifest_hash: str) -> None:
        atomic_write_json(
            self.cfg.scan_cache_file,
            {
                "version": VERSION,
                "dat_sha256": dat_hash,
                "input_fingerprint": input_fp,
                "target_manifest_sha256": manifest_hash,
                "completed_at": now_iso(),
            },
        )


def parse_args(argv: list[str]) -> Config:
    parser = argparse.ArgumentParser(description="Python-only MAME images auditor/rebuilder.")
    parser.add_argument("--scan-only", action="store_true")
    parser.add_argument("--rebuild-plan-only", action="store_true")
    parser.add_argument("--skip-xml", action="store_true")
    parser.add_argument("--no-qnap", action="store_true")
    parser.add_argument("--mame-bin", type=Path, default=Path("mame/mame"))
    parser.add_argument("--images", type=Path, default=Path("images"))
    parser.add_argument("--new", type=Path, default=Path("new"))
    parser.add_argument("--work", type=Path, default=Path("work_mame"))
    parser.add_argument("--rsync-pass", type=Path, default=Path(".rsync"))
    parser.add_argument("--backup-url", default="rsync://rsync@qnap2/Game/Multi-Platform/images/")
    parser.add_argument("--merge-mode", choices=["merged", "split", "non-merged"], default="merged")
    parser.add_argument("--scan-jobs", type=int, default=int(os.environ.get("SCAN_JOBS", "16")))
    parser.add_argument("--compress-jobs", type=int, default=int(os.environ.get("COMPRESS_JOBS", "4")))
    parser.add_argument("--rebuild-mode", choices=["auto", "full", "skip"], default="auto")
    parser.add_argument("--7z-bin", dest="sevenz_bin", default="7z")
    parser.add_argument("--rsync-bin", default="rsync")
    parser.add_argument("--chdman-bin", default="chdman")
    parser.add_argument("--no-chdman", action="store_true")
    parser.add_argument("--yes", action="store_true")
    parser.add_argument("--force-large-sync", action="store_true")
    parser.add_argument("--large-sync-threshold", type=int, default=1000)

    # Backward-compatible no-op options from the Igir-based prototype.
    parser.add_argument("--igir-bin", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--igir-scan-command", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--igir-checksum-max", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--igir-checksum-archives", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--no-igir-checksum-quick", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--allow-igir-parse-warnings", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--rom-scan-mode", default=None, help=argparse.SUPPRESS)

    args = parser.parse_args(argv)
    return Config(
        mame_bin=args.mame_bin,
        images=args.images,
        new=args.new,
        work=args.work,
        rsync_pass=args.rsync_pass,
        backup_url=args.backup_url,
        merge_mode=args.merge_mode,
        scan_jobs=args.scan_jobs,
        compress_jobs=args.compress_jobs,
        scan_only=args.scan_only,
        rebuild_plan_only=args.rebuild_plan_only,
        skip_xml=args.skip_xml,
        no_qnap=args.no_qnap,
        rebuild_mode=args.rebuild_mode,
        sevenz_bin=args.sevenz_bin,
        rsync_bin=args.rsync_bin,
        chdman_bin=args.chdman_bin,
        no_chdman=args.no_chdman,
        yes=args.yes,
        force_large_sync=args.force_large_sync,
        large_sync_threshold=args.large_sync_threshold,
    )


def main(argv: list[str] | None = None) -> int:
    return MameRebuildApp(parse_args(argv if argv is not None else sys.argv[1:])).run()


if __name__ == "__main__":
    raise SystemExit(main())
