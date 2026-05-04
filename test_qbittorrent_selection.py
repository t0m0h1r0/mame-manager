from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib import parse

from mame_manager.defaults import DEFAULT_NEW_DIR
from mame_manager.system import iter_visible_files


REQUESTS: list[tuple[str, dict[str, list[str]]]] = []
TORRENTS = [
    {"hash": "bad111", "name": "Other torrent"},
    {"hash": "abc123", "name": "MAME 0.287 ROMs (merged)"},
    {"hash": "def456", "name": "MAME 0.287 ROMs update pack"},
]


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode()
        fields = parse.parse_qs(body)
        REQUESTS.append((self.path, fields))
        if self.path == "/api/v2/auth/login":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Ok.")
            return
        if self.path in {
            "/api/v2/torrents/filePrio",
            "/api/v2/torrents/resume",
            "/api/v2/torrents/pause",
            "/api/v2/torrents/start",
            "/api/v2/torrents/stop",
        }:
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"")
            return
        self.send_error(404)

    def do_GET(self):
        REQUESTS.append((self.path, {}))
        if self.path.startswith("/api/v2/torrents/files"):
            qs = parse.parse_qs(parse.urlsplit(self.path).query)
            torrent_hash = qs.get("hash", [""])[0]
            if torrent_hash == "abc123":
                payload = [
                    {"name": "MAME 0.287 ROMs (merged)/100in1rg.zip"},
                    {"name": "MAME 0.287 ROMs (merged)/bloodstm.zip"},
                    {"name": "MAME 0.287 ROMs (merged)/other.zip"},
                ]
            elif torrent_hash == "def456":
                payload = [
                    {"name": "MAME 0.287 ROMs update pack/missing.zip"},
                    {"name": "MAME 0.287 ROMs update pack/other.zip"},
                ]
            else:
                payload = [{"name": "other.zip"}]
            data = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        if self.path == "/api/v2/torrents/info":
            data = json.dumps(TORRENTS).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        self.send_error(404)

    def log_message(self, fmt, *args):
        return


def write_fixture(root: Path) -> tuple[Path, Path, Path, Path]:
    images = root / "images"
    new = root / "new"
    work = root / "work_mame"
    root.mkdir(parents=True)
    images.mkdir()
    new.mkdir()
    work.mkdir()
    (work / "mame.xml").write_text(
        """<?xml version="1.0"?>
<mame>
  <machine name="100in1rg"><rom name="a.bin" size="1" crc="11111111"/></machine>
  <machine name="bloodstm"><rom name="b.bin" size="1" crc="22222222"/></machine>
  <machine name="missing"><rom name="c.bin" size="1" crc="33333333"/></machine>
</mame>
""",
        encoding="utf-8",
    )
    (work / "software.xml").write_text("<softwarelists/>\n", encoding="utf-8")
    sevenz = root / "7z"
    sevenz.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    sevenz.chmod(0o755)
    return images, new, work, sevenz


def run_manager(root: Path, url: str, *extra: str, enable_download: bool = True) -> subprocess.CompletedProcess[str]:
    images, new, work, sevenz = write_fixture(root)
    env = os.environ.copy()
    env["QBITTORRENT_PASSWORD"] = "secret"
    action = ["--download-missing"] if enable_download else []
    return subprocess.run(
        [
            sys.executable,
            "mame_manager.py",
            "--scan-only",
            "--skip-xml",
            "--images",
            str(images),
            "--new",
            str(new),
            "--work",
            str(work),
            "--7z-bin",
            str(sevenz),
            "--qbittorrent-url",
            url,
            "--qbittorrent-user",
            "admin",
            *action,
            *extra,
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        check=True,
    )


def main() -> int:
    assert DEFAULT_NEW_DIR == Path("Downloads")
    with tempfile.TemporaryDirectory() as td:
        incoming = Path(td) / "Downloads"
        incoming.mkdir()
        (incoming / "visible.zip").write_text("", encoding="utf-8")
        (incoming / ".hidden.zip").write_text("", encoding="utf-8")
        hidden_dir = incoming / ".partial"
        hidden_dir.mkdir()
        (hidden_dir / "nested.zip").write_text("", encoding="utf-8")
        assert [path.name for path in iter_visible_files(incoming)] == ["visible.zip"]

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}"
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        passive = run_manager(root / "passive", url, enable_download=False)
        assert "qBittorrent selected files" not in passive.stdout
        assert not REQUESTS

        dry = run_manager(root / "dry", url, "--qbittorrent-hash", "abc123", "--qbittorrent-dry-run")
        assert "qBittorrent selected files: 2/3" in dry.stdout
        assert "qBittorrent unmatched wanted files: 0" in dry.stdout
        assert not any(path == "/api/v2/torrents/filePrio" for path, _ in REQUESTS)

        REQUESTS.clear()
        real = run_manager(root / "real", url, "--qbittorrent-hash", "abc123", "--qbittorrent-resume")
        assert "qBittorrent selected files: 2/3" in real.stdout
        file_prio = [(path, fields) for path, fields in REQUESTS if path == "/api/v2/torrents/filePrio"]
        assert len(file_prio) == 2, REQUESTS
        assert file_prio[0][1]["id"] == ["0|1|2"]
        assert file_prio[0][1]["priority"] == ["0"]
        assert file_prio[1][1]["id"] == ["0|1"]
        assert file_prio[1][1]["priority"] == ["1"]
        assert any(path == "/api/v2/torrents/resume" for path, _ in REQUESTS)

        REQUESTS.clear()
        auto = run_manager(root / "auto", url, "--qbittorrent-name", "MAME", "--qbittorrent-dry-run")
        assert "qBittorrent torrent: MAME 0.287 ROMs (merged) (abc123)" in auto.stdout
        assert "qBittorrent selected files: 2/3" in auto.stdout
        assert "qBittorrent torrent: MAME 0.287 ROMs update pack (def456)" in auto.stdout
        assert "qBittorrent selected files: 1/2" in auto.stdout

        REQUESTS.clear()
        all_torrents = run_manager(root / "all", url, "--qbittorrent-name", "MAME", "--qbittorrent-resume")
        assert "qBittorrent selected files: 2/3" in all_torrents.stdout
        assert "qBittorrent selected files: 1/2" in all_torrents.stdout
        file_prio = [(path, fields) for path, fields in REQUESTS if path == "/api/v2/torrents/filePrio"]
        assert len(file_prio) == 4, REQUESTS
        assert file_prio[0][1]["hash"] == ["abc123"]
        assert file_prio[0][1]["id"] == ["0|1|2"]
        assert file_prio[0][1]["priority"] == ["0"]
        assert file_prio[1][1]["hash"] == ["abc123"]
        assert file_prio[1][1]["id"] == ["0|1"]
        assert file_prio[1][1]["priority"] == ["1"]
        assert file_prio[2][1]["hash"] == ["def456"]
        assert file_prio[2][1]["id"] == ["0|1"]
        assert file_prio[2][1]["priority"] == ["0"]
        assert file_prio[3][1]["hash"] == ["def456"]
        assert file_prio[3][1]["id"] == ["0"]
        assert file_prio[3][1]["priority"] == ["1"]
        resumes = [(path, fields) for path, fields in REQUESTS if path == "/api/v2/torrents/resume"]
        assert [fields["hashes"] for _, fields in resumes] == [["abc123"], ["def456"]]
    server.shutdown()
    print("mock qBittorrent integration tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
