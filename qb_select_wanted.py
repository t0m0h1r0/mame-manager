#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from mame_manager.qbittorrent import (
    QBittorrentClient,
    QBittorrentConfig,
    QBittorrentError,
    choose_torrent,
    read_wanted_files,
)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Select only wanted files in an existing qBittorrent torrent."
    )
    parser.add_argument("--url", required=True, help="qBittorrent WebUI URL, e.g. http://localhost:8080")
    parser.add_argument("--user", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--hash", default=None, help="Torrent hash in qBittorrent; auto-detected when omitted")
    parser.add_argument("--torrent-name", default=None, help="Optional torrent name substring used when auto-detecting")
    parser.add_argument("--wanted", type=Path, required=True, help="wanted file list, one path per line")
    parser.add_argument("--priority", type=int, default=1, help="priority for wanted files; qBittorrent default normal is 1")
    parser.add_argument("--skip-priority", type=int, default=0, help="priority for all other files")
    parser.add_argument("--resume", action="store_true", help="resume torrent after priorities are applied")
    parser.add_argument("--dry-run", action="store_true", help="show selected files without changing qBittorrent")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    wanted = read_wanted_files(args.wanted)
    client = QBittorrentClient(QBittorrentConfig(args.url, args.user, args.password))
    try:
        client.login()
        torrent_hash, files, selected_ids, unmatched = choose_torrent(
            client,
            wanted,
            torrent_hash=args.hash,
            torrent_name_filter=args.torrent_name,
        )
        all_ids = list(range(len(files)))
        print(f"torrent hash: {torrent_hash}")
        print(f"torrent files: {len(files)}")
        print(f"wanted paths: {len(wanted)}")
        print(f"selected files: {len(selected_ids)}")
        print(f"unmatched wanted paths: {len(unmatched)}")
        if unmatched:
            print("unmatched:")
            for item in unmatched:
                print(item)
        if args.dry_run:
            print("dry-run: no qBittorrent changes made")
            return 0
        client.set_file_priority(torrent_hash, all_ids, args.skip_priority)
        client.set_file_priority(torrent_hash, selected_ids, args.priority)
        if args.resume:
            client.resume(torrent_hash)
        return 0
    except QBittorrentError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
