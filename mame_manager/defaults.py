from __future__ import annotations

import os
from pathlib import Path

ENV_CONFIG_FILE = "MAME_MANAGER_CONFIG"

DEFAULT_CONFIG_FILE = Path.home() / ".config" / "mame-manager" / "config.env"
DEFAULT_MAME_BIN = Path("mame/mame")
DEFAULT_IMAGES_DIR = Path("images")
DEFAULT_NEW_DIR = Path("Downloads")
DEFAULT_WORK_DIR = Path("work_mame")
DEFAULT_RSYNC_PASSWORD_FILE = Path(".rsync")
DEFAULT_BACKUP_URL = None
DEFAULT_TORRENT_PLAN = None

DEFAULT_MERGE_MODE = "merged"
DEFAULT_REBUILD_MODE = "auto"
DEFAULT_SCAN_JOBS = 16
DEFAULT_COMPRESS_JOBS = 4
DEFAULT_LARGE_SYNC_THRESHOLD = 1000

DEFAULT_SEVENZ_BIN = "7z"
DEFAULT_RSYNC_BIN = "rsync"
DEFAULT_CHDMAN_BIN = "chdman"

DEFAULT_QBITTORRENT_URL = "http://localhost:8080"
DEFAULT_QBITTORRENT_USER = "admin"
DEFAULT_QBITTORRENT_PRIORITY = 1
DEFAULT_QBITTORRENT_SKIP_PRIORITY = 0
DEFAULT_QBITTORRENT_TIMEOUT = 30
DEFAULT_QBITTORRENT_HASH = None
DEFAULT_QBITTORRENT_NAME = None

DEFAULT_COMPAT_OPTION = None

ENV_SCAN_JOBS = "SCAN_JOBS"
ENV_COMPRESS_JOBS = "COMPRESS_JOBS"
ENV_BACKUP_URL = "BACKUP_URL"
ENV_QBITTORRENT_URL = "QBITTORRENT_URL"
ENV_QBITTORRENT_USER = "QBITTORRENT_USER"
ENV_QBITTORRENT_PASSWORD = "QBITTORRENT_PASSWORD"


def config_file_default() -> Path:
    return Path(os.environ.get(ENV_CONFIG_FILE, str(DEFAULT_CONFIG_FILE))).expanduser()


def load_config_env(path: Path | None = None) -> dict[str, str]:
    config_path = (path or config_file_default()).expanduser()
    if not config_path.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in config_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("'\"")
    return values


def configured_default(name: str, default: str | None, config: dict[str, str]) -> str | None:
    return os.environ.get(name, config.get(name, default))


def configured_optional(name: str, config: dict[str, str]) -> str | None:
    return os.environ.get(name, config.get(name))


def configured_int_default(name: str, default: int, config: dict[str, str]) -> int:
    return int(os.environ.get(name, config.get(name, str(default))))


def env_default(name: str, default: str) -> str:
    return os.environ.get(name, default)


def env_optional(name: str) -> str | None:
    return os.environ.get(name)


def env_int_default(name: str, default: int) -> int:
    return int(os.environ.get(name, str(default)))
