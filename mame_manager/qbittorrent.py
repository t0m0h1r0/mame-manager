from __future__ import annotations

import json
from dataclasses import dataclass
from http.cookiejar import CookieJar
from pathlib import Path
from typing import Any
from urllib import parse, request


class QBittorrentError(RuntimeError):
    pass


@dataclass(frozen=True)
class QBittorrentConfig:
    url: str
    username: str
    password: str
    timeout: int = 30


class QBittorrentClient:
    """Small qBittorrent Web API client using only the Python standard library."""

    def __init__(self, cfg: QBittorrentConfig):
        self.cfg = cfg
        self.base = cfg.url.rstrip("/")
        self.cookies = CookieJar()
        self.opener = request.build_opener(request.HTTPCookieProcessor(self.cookies))

    def login(self) -> None:
        body = parse.urlencode({"username": self.cfg.username, "password": self.cfg.password}).encode()
        data = self._request("/api/v2/auth/login", body=body)
        if data.strip() != b"Ok.":
            raise QBittorrentError("qBittorrent login failed")

    def torrents(self) -> list[dict[str, Any]]:
        return json.loads(self._request("/api/v2/torrents/info").decode())

    def torrent_files(self, torrent_hash: str) -> list[dict[str, Any]]:
        query = parse.urlencode({"hash": torrent_hash})
        return json.loads(self._request(f"/api/v2/torrents/files?{query}").decode())

    def set_file_priority(self, torrent_hash: str, file_ids: list[int], priority: int) -> None:
        if not file_ids:
            return
        body = parse.urlencode(
            {
                "hash": torrent_hash,
                "id": "|".join(str(x) for x in file_ids),
                "priority": str(priority),
            }
        ).encode()
        self._request("/api/v2/torrents/filePrio", body=body)

    def resume(self, torrent_hash: str) -> None:
        body = parse.urlencode({"hashes": torrent_hash}).encode()
        self._request_first(["/api/v2/torrents/resume", "/api/v2/torrents/start"], body=body)

    def pause(self, torrent_hash: str) -> None:
        body = parse.urlencode({"hashes": torrent_hash}).encode()
        self._request_first(["/api/v2/torrents/pause", "/api/v2/torrents/stop"], body=body)

    def _request_first(self, paths: list[str], body: bytes | None = None) -> bytes:
        errors = []
        for path in paths:
            try:
                return self._request(path, body=body)
            except QBittorrentError as exc:
                errors.append(str(exc))
        raise QBittorrentError("; ".join(errors))

    def _request(self, path: str, body: bytes | None = None) -> bytes:
        req = request.Request(self.base + path, data=body)
        if body is not None:
            req.add_header("Content-Type", "application/x-www-form-urlencoded")
        try:
            with self.opener.open(req, timeout=self.cfg.timeout) as resp:
                return resp.read()
        except Exception as exc:  # urllib raises several exception types.
            raise QBittorrentError(f"qBittorrent API request failed: {path}: {exc}") from exc


def normalize_torrent_path(path: str) -> str:
    return path.strip().replace("\\", "/").lstrip("./")


def select_file_ids(files: list[dict[str, Any]], wanted: set[str]) -> tuple[list[int], list[str]]:
    wanted_by_basename: dict[str, set[str]] = {}
    for item in wanted:
        wanted_by_basename.setdefault(Path(item).name, set()).add(item)

    selected = []
    matched_wanted = set()
    for idx, file_info in enumerate(files):
        name = normalize_torrent_path(str(file_info.get("name", "")))
        basename = Path(name).name
        direct = name in wanted
        suffix = any(name.endswith("/" + item) for item in wanted_by_basename.get(basename, set()))
        basename_only = basename in wanted_by_basename
        if direct or suffix or basename_only:
            selected.append(idx)
            if direct:
                matched_wanted.add(name)
            else:
                matched_wanted.update(wanted_by_basename.get(basename, set()))

    return selected, sorted(wanted - matched_wanted)


def torrent_display_name(torrent: dict[str, Any]) -> str:
    return str(torrent.get("name") or torrent.get("hash") or "<unnamed>")
