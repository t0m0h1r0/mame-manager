from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from mame_manager import defaults
from mame_manager.cli import parse_args


def main() -> int:
    with TemporaryDirectory() as tmp:
        empty_config = Path(tmp) / "missing.env"
        default_cfg = parse_args(["--config", str(empty_config), "--scan-only"])
        assert default_cfg.backup_url == defaults.DEFAULT_BACKUP_URL
        assert default_cfg.rsync_pass == defaults.DEFAULT_RSYNC_PASSWORD_FILE

        config = Path(tmp) / "config.env"
        config.write_text(
            "\n".join(
                [
                    "# local machine settings",
                    "BACKUP_URL=rsync://rsync@backup-host/Game/Multi-Platform/images/",
                    "QBITTORRENT_PASSWORD='secret'",
                    "SCAN_JOBS=7",
                    "COMPRESS_JOBS=3",
                ]
            ),
            encoding="utf-8",
        )

        values = defaults.load_config_env(config)
        assert values["BACKUP_URL"] == "rsync://rsync@backup-host/Game/Multi-Platform/images/"
        assert values["QBITTORRENT_PASSWORD"] == "secret"
        assert defaults.configured_int_default(defaults.ENV_SCAN_JOBS, 16, values) == 7

        cfg = parse_args(["--config", str(config), "--scan-only"])
        assert cfg.backup_url == "rsync://rsync@backup-host/Game/Multi-Platform/images/"
        assert cfg.qbittorrent_password == "secret"
        assert cfg.scan_jobs == 7
        assert cfg.compress_jobs == 3

    print("config default tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
