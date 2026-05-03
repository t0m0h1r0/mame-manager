#!/usr/bin/env python3
"""Compatibility entry point for qBittorrent wanted-file selection."""

from mame_manager.qbittorrent_cli import main


if __name__ == "__main__":
    raise SystemExit(main())
