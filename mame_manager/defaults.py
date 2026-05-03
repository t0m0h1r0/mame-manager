from __future__ import annotations

import os
from pathlib import Path

DEFAULT_MAME_BIN = Path("mame/mame")
DEFAULT_IMAGES_DIR = Path("images")
DEFAULT_NEW_DIR = Path("Downloads")
DEFAULT_WORK_DIR = Path("work_mame")
DEFAULT_RSYNC_PASSWORD_FILE = Path(".rsync")
DEFAULT_BACKUP_URL = "rsync://rsync@qnap2/Game/Multi-Platform/images/"
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
ENV_QBITTORRENT_URL = "QBITTORRENT_URL"
ENV_QBITTORRENT_USER = "QBITTORRENT_USER"
ENV_QBITTORRENT_PASSWORD = "QBITTORRENT_PASSWORD"


def env_default(name: str, default: str) -> str:
    return os.environ.get(name, default)


def env_optional(name: str) -> str | None:
    return os.environ.get(name)


def env_int_default(name: str, default: int) -> int:
    return int(os.environ.get(name, str(default)))
