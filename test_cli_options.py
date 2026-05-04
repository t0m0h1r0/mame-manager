from __future__ import annotations

import contextlib
import io

from mame_manager.cli import parse_args


def assert_parse_error(args: list[str]) -> None:
    try:
        with contextlib.redirect_stderr(io.StringIO()):
            parse_args(args)
    except SystemExit as exc:
        assert exc.code == 2
        return
    raise AssertionError(f"expected parse error for {args}")


def main() -> int:
    default_cfg = parse_args([])
    assert default_cfg.scan_only
    assert not default_cfg.check_broken

    integrity_cfg = parse_args(["--check-broken"])
    assert integrity_cfg.check_broken
    assert not integrity_cfg.scan_only

    download_cfg = parse_args(["--download-missing", "--qbittorrent-dry-run"])
    assert download_cfg.download_missing
    assert download_cfg.qbittorrent_dry_run

    assert_parse_error(["--scan-only", "--rebuild"])
    assert_parse_error(["--check-broken", "--rebuild"])
    assert_parse_error(["--restore", "--download-missing"])
    assert_parse_error(["--qbittorrent-dry-run"])

    print("argument parsing tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
