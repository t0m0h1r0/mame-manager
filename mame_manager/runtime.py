from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import shutil
import socket
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

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


def is_hidden_path(path: Path, root: Path) -> bool:
    try:
        rel = path.relative_to(root)
    except ValueError:
        rel = path
    return any(part.startswith(".") for part in rel.parts)


def iter_visible_files(root: Path) -> Iterable[Path]:
    if not root.exists():
        return
    for current, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if not name.startswith(".")]
        current_path = Path(current)
        for filename in filenames:
            if filename.startswith("."):
                continue
            path = current_path / filename
            if path.is_file() and not is_hidden_path(path, root):
                yield path


class Shell:
    def capture(
        self,
        cmd: list[str | os.PathLike[str]],
        cwd: Path | None = None,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(x) for x in cmd],
            cwd=str(cwd) if cwd else None,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=check,
        )

    def run(
        self,
        cmd: list[str | os.PathLike[str]],
        cwd: Path | None = None,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        print("$ " + quote_cmd(cmd), flush=True)
        return self.capture(cmd, cwd=cwd, check=check)

    def run_to_log(
        self,
        cmd: list[str | os.PathLike[str]],
        log: Path,
        cwd: Path | None = None,
        check: bool = True,
    ) -> int:
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("w", encoding="utf-8") as f:
            f.write("$ " + quote_cmd(cmd) + "\n\n")
            f.flush()
            proc = subprocess.run(
                [str(x) for x in cmd],
                cwd=str(cwd) if cwd else None,
                text=True,
                stdout=f,
                stderr=subprocess.STDOUT,
            )
        if check and proc.returncode != 0:
            raise FatalError(f"command failed ({proc.returncode}); see {log}")
        return proc.returncode

    @staticmethod
    def executable_exists(name: str | Path) -> bool:
        value = str(name)
        if "/" in value:
            return Path(value).exists() and os.access(value, os.X_OK)
        return shutil.which(value) is not None


class Validator:
    def __init__(self, cfg: Any):
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
        if not self.cfg.restore:
            self.cfg.new.mkdir(parents=True, exist_ok=True)
        if self.cfg.update_xml and not self.cfg.mame_bin.exists():
            raise FatalError(f"MAME binary not found: {self.cfg.mame_bin}")
        read_only = self.cfg.scan_only or self.cfg.rebuild_plan_only or self.cfg.check_broken or bool(self.cfg.torrent_plan)
        needs_rsync = self.cfg.restore or not read_only
        needs_7z = not self.cfg.restore
        for exe, needed in ((self.cfg.sevenz_bin, needs_7z), (self.cfg.rsync_bin, needs_rsync)):
            if needed and not Shell.executable_exists(exe):
                raise FatalError(f"required executable not found: {exe}")
        if self.cfg.backup or self.cfg.restore:
            if not self.cfg.backup_url:
                raise FatalError("--backup-url or BACKUP_URL is required for backup/restore")
            if str(self.cfg.backup_url).startswith("rsync://"):
                self._validate_rsync_url(self.cfg.backup_url)
                if not self.cfg.rsync_pass.exists():
                    raise FatalError(f"rsync password file not found: {self.cfg.rsync_pass}")
        if self.cfg.qbittorrent_enabled:
            if not self.cfg.qbittorrent_password:
                raise FatalError("--qbittorrent-password or QBITTORRENT_PASSWORD is required when qBittorrent is enabled")
            if self.cfg.qbittorrent_priority < 0 or self.cfg.qbittorrent_skip_priority < 0:
                raise FatalError("qBittorrent priorities must be >= 0")
            if self.cfg.qbittorrent_timeout < 1:
                raise FatalError("--qbittorrent-timeout must be >= 1")

    @staticmethod
    def _validate_rsync_url(url: str) -> None:
        parsed = urlparse(url)
        host = parsed.hostname
        if not host:
            raise FatalError(f"invalid rsync URL: {url}")
        try:
            socket.getaddrinfo(host, parsed.port or 873)
        except socket.gaierror:
            raise FatalError(
                f"backup URL host cannot be resolved: {host}; "
                "set --backup-url or BACKUP_URL to a reachable hostname or IP address"
            )
