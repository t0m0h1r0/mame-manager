from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

@dataclass(frozen=True)
class Config:
    mame_bin: Path
    images: Path
    new: Path
    work: Path
    rsync_pass: Path
    backup_url: str
    merge_mode: str
    scan_jobs: int
    compress_jobs: int
    scan_only: bool
    rebuild_plan_only: bool
    torrent_plan: Path | None
    skip_xml: bool
    no_qnap: bool
    rebuild_mode: str
    sevenz_bin: str
    rsync_bin: str
    chdman_bin: str
    no_chdman: bool
    yes: bool
    force_large_sync: bool
    large_sync_threshold: int

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

