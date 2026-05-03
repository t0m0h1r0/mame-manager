from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Iterable

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

