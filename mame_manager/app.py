from __future__ import annotations

import json
import signal
import sys
from typing import Any

from .assets import AssetManager
from .set_audit import Auditor
from .assets import ChdCache
from .system import VERSION, FatalError, atomic_write_json, sha256_bytes, sha256_file, now_iso
from .config import RunConfig
from .dat_catalog import DatExtractor, DatIndex
from .collection_index import ArchiveIndexer, Fingerprinter, Inventory
from .rebuilder import Rebuilder
from .reporting import ReportManager
from .system import Shell
from .sync import SyncManager
from .integrity import IntegrityChecker
from .torrent_selection import QBittorrentDownloadManager, TorrentPlanner
from .system import Validator

class MameRebuildApp:
    def __init__(self, cfg: RunConfig):
        self.cfg = cfg
        self.shell = Shell()
        self.report = ReportManager(cfg)

    def run(self) -> int:
        signal.signal(signal.SIGTERM, self._sigterm)
        try:
            self.report.phase("validate")
            Validator(self.cfg).validate()
            if self.cfg.restore:
                self.report.phase("restore images")
                SyncManager(self.cfg, self.shell, self.report).restore_images()
                self.report.phase("done")
                self.report.finish()
                return 0
            if self.cfg.check_broken:
                self.report.phase("check broken files")
                IntegrityChecker(self.cfg, self.shell, self.report).check_all()
                self.report.phase("done")
                self.report.finish()
                return 0
            self.report.phase("extract DAT")
            DatExtractor(self.cfg, self.shell).extract()
            self.report.phase("parse DAT")
            index = DatIndex(self.cfg.arcade_xml, self.cfg.software_xml, self.cfg.merge_mode).parse()
            manifest = index.manifest()
            manifest_payload = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
            manifest_hash = sha256_bytes(manifest_payload)
            dat_hash = sha256_bytes((sha256_file(self.cfg.arcade_xml) + sha256_file(self.cfg.software_xml)).encode())
            self.report.summary["target_counts"] = {
                "arcade_roms": len(index.arcade_targets),
                "software_roms": len(index.software_targets),
                "arcade_chds": len(index.arcade_chds),
                "software_chds": len(index.software_chds),
                "sample_sets": len(index.sample_targets),
            }
            if not self.cfg.scan_only:
                atomic_write_json(self.cfg.target_manifest_file, manifest)
            self.report.phase("fingerprint inputs")
            fp = Fingerprinter(self.cfg).collect()
            self.report.summary["input_file_count"] = len(fp["files"])
            self.report.summary["input_fingerprint"] = fp["sha256"]
            self.report.phase("index archives")
            indexer = ArchiveIndexer(self.cfg, self.shell, self.report)
            archives = indexer.index_all()
            inventory = Inventory(archives)
            self.report.phase("audit ROMs")
            missing_roms = Auditor(self.cfg, self.report).audit_roms(index, inventory)
            self.report.phase("scan CHDs")
            chds = ChdCache(self.cfg, self.shell, self.report).scan()
            assets = AssetManager(self.cfg, self.report)
            missing_chds = assets.missing_chds(index, chds)
            if self.cfg.torrent_plan:
                self.report.phase("plan torrent files")
                TorrentPlanner(self.cfg, self.report).plan(missing_roms, inventory.bad_archives, missing_chds)
            if self.cfg.qbittorrent_enabled:
                self.report.phase("apply qBittorrent file priorities")
                QBittorrentDownloadManager(self.cfg, self.report).apply(missing_roms, inventory.bad_archives, missing_chds)
            if self.cfg.scan_only:
                assets.report_chds(index, chds)
                assets.report_samples(index, indexer)
                self.report.print_scan_summary()
                self._write_scan_cache(dat_hash, fp["sha256"], manifest_hash)
            elif self.cfg.rebuild_plan_only:
                self.report.phase("plan rebuild")
                Rebuilder(self.cfg, self.shell, self.report, indexer).plan(index, inventory)
                assets.report_chds(index, chds)
                assets.report_samples(index, indexer)
                self.report.print_scan_summary()
            else:
                if inventory.bad_archives:
                    self.report.note(f"{len(inventory.bad_archives)} archive(s) failed 7z indexing; ignoring them as rebuild sources")
                self.report.phase("rebuild clean_images")
                Rebuilder(self.cfg, self.shell, self.report, indexer).rebuild(index, inventory, manifest_hash, fp["sha256"], dat_hash)
                assets.place_chds(index, chds)
                assets.place_samples(index, indexer)
                self.report.phase("rsync")
                SyncManager(self.cfg, self.shell, self.report).sync_all()
            self.report.phase("done")
            self.report.finish()
            return 0
        except FatalError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            self.report.finish(str(e))
            return 2
        except KeyboardInterrupt:
            self.report.finish("interrupted")
            return 130

    def _sigterm(self, signum: int, frame: Any) -> None:
        raise FatalError("terminated by SIGTERM")

    def _write_scan_cache(self, dat_hash: str, input_fp: str, manifest_hash: str) -> None:
        atomic_write_json(
            self.cfg.scan_cache_file,
            {
                "version": VERSION,
                "dat_sha256": dat_hash,
                "input_fingerprint": input_fp,
                "target_manifest_sha256": manifest_hash,
                "completed_at": now_iso(),
            },
        )
