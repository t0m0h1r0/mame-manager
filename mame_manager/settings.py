from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

@dataclass(frozen=True)
class RunConfig:
    mame_bin: Path
    images: Path
    new: Path
    work: Path
    rsync_pass: Path
    backup_url: str | None
    backup: bool
    restore: bool
    merge_mode: str
    scan_jobs: int
    compress_jobs: int
    scan_only: bool
    rebuild_plan_only: bool
    torrent_plan: Path | None
    update_xml: bool
    rebuild_mode: str
    sevenz_bin: str
    rsync_bin: str
    chdman_bin: str
    no_chdman: bool
    yes: bool
    force_large_sync: bool
    large_sync_threshold: int
    download_missing: bool
    qbittorrent_url: str | None
    qbittorrent_user: str
    qbittorrent_password: str | None
    qbittorrent_hash: str | None
    qbittorrent_name: str | None
    qbittorrent_priority: int
    qbittorrent_skip_priority: int
    qbittorrent_resume: bool
    qbittorrent_dry_run: bool
    qbittorrent_timeout: int

    @property
    def qbittorrent_enabled(self) -> bool:
        return self.download_missing

    @property
    def clean(self) -> Path:
        return self.work / "clean_images"

    @property
    def raw(self) -> Path:
        return self.work / "raw"

    @property
    def reports(self) -> Path:
        return self.work / "reports"

    @property
    def arcade_xml(self) -> Path:
        return self.work / "mame.xml"

    @property
    def software_xml(self) -> Path:
        return self.work / "software.xml"

    @property
    def archive_index_cache_file(self) -> Path:
        return self.work / "archive_index_cache.json"

    @property
    def chd_cache_file(self) -> Path:
        return self.work / "chd_cache.json"

    @property
    def scan_cache_file(self) -> Path:
        return self.work / "scan_cache.json"

    @property
    def rebuild_cache_file(self) -> Path:
        return self.work / "rebuild_cache.json"

    @property
    def target_manifest_file(self) -> Path:
        return self.work / "target_manifest.json"
