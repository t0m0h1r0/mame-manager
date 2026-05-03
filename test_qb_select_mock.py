from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib import parse


REQUESTS: list[tuple[str, dict[str, list[str]]]] = []
TORRENTS = [
    {"hash": "bad111", "name": "Other torrent"},
    {"hash": "abc123", "name": "MAME 0.287 ROMs (merged)"},
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
        if self.path in {"/api/v2/torrents/filePrio", "/api/v2/torrents/resume", "/api/v2/torrents/pause"}:
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


def main() -> int:
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}"
    with tempfile.TemporaryDirectory() as td:
        wanted = Path(td) / "wanted.txt"
        wanted.write_text(
            "\n".join(
                [
                    "MAME 0.287 ROMs (merged)/100in1rg.zip",
                    "bloodstm.zip",
                    "missing.zip",
                ]
            )
            + "\n"
        )
        dry = subprocess.run(
            [
                sys.executable,
                "qb_select_wanted.py",
                "--url",
                url,
                "--user",
                "admin",
                "--password",
                "secret",
                "--hash",
                "abc123",
                "--wanted",
                str(wanted),
                "--dry-run",
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        assert "selected files: 2" in dry.stdout
        assert "unmatched wanted paths: 1" in dry.stdout
        assert not any(path == "/api/v2/torrents/filePrio" for path, _ in REQUESTS)

        REQUESTS.clear()
        real = subprocess.run(
            [
                sys.executable,
                "qb_select_wanted.py",
                "--url",
                url,
                "--user",
                "admin",
                "--password",
                "secret",
                "--hash",
                "abc123",
                "--wanted",
                str(wanted),
                "--resume",
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        assert "selected files: 2" in real.stdout
        file_prio = [(path, fields) for path, fields in REQUESTS if path == "/api/v2/torrents/filePrio"]
        assert len(file_prio) == 2, REQUESTS
        assert file_prio[0][1]["id"] == ["0|1|2"]
        assert file_prio[0][1]["priority"] == ["0"]
        assert file_prio[1][1]["id"] == ["0|1"]
        assert file_prio[1][1]["priority"] == ["1"]
        assert any(path == "/api/v2/torrents/resume" for path, _ in REQUESTS)

        REQUESTS.clear()
        auto = subprocess.run(
            [
                sys.executable,
                "qb_select_wanted.py",
                "--url",
                url,
                "--user",
                "admin",
                "--password",
                "secret",
                "--wanted",
                str(wanted),
                "--torrent-name",
                "MAME",
                "--dry-run",
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
        assert "torrent hash: abc123" in auto.stdout
        assert "selected files: 2" in auto.stdout
    server.shutdown()
    print("mock qBittorrent selector tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
