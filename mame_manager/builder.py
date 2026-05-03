from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from .runtime import VERSION, FatalError, atomic_write_json, load_json, now_iso, safe_rmtree
from .settings import RunConfig
from .catalog import DatIndex
from .inventory import ArchiveIndexer, Inventory, archive_matches_target
from .reports import ReportManager
from .runtime import Shell

class Rebuilder:
    def __init__(self, cfg: RunConfig, shell: Shell, report: ReportManager, indexer: ArchiveIndexer):
        self.cfg = cfg
        self.shell = shell
        self.report = report
        self.indexer = indexer
        self.reused = 0
        self.created = 0

    def prepare(self) -> None:
        safe_rmtree(self.cfg.clean, self.cfg.work)
        safe_rmtree(self.cfg.raw, self.cfg.work)
        for name in ("roms", "software_roms", "chds", "software_chds", "samples"):
            (self.cfg.clean / name).mkdir(parents=True, exist_ok=True)
        self.cfg.raw.mkdir(parents=True, exist_ok=True)

    def rebuild(self, index: DatIndex, inventory: Inventory, manifest_hash: str, input_fp: str, dat_hash: str) -> None:
        action = self._action(manifest_hash, input_fp, dat_hash)
        self.report.summary["rebuild_action"] = action
        self.prepare()
        if action == "skip":
            self.report.note("rebuild cache matched, but clean_images is rebuilt from reusable archives before sync")
        failures = []
        for rel, target in sorted(index.all_targets().items()):
            if self._reuse_existing(rel, target):
                continue
            ok, reason = self._build_target(rel, target, inventory)
            if not ok:
                failures.append(f"{rel}: {reason}")
        self.report.write("rebuild_failures.txt", failures)
        self.report.summary["existing_7z_reused"] = self.reused
        self.report.summary["new_7z_created"] = self.created
        self.report.summary["rebuild_failures"] = len(failures)
        if failures:
            raise FatalError(f"failed to build {len(failures)} ROM package(s); refusing to sync")
        atomic_write_json(
            self.cfg.rebuild_cache_file,
            {
                "version": VERSION,
                "dat_sha256": dat_hash,
                "input_fingerprint": input_fp,
                "target_manifest_sha256": manifest_hash,
                "completed_at": now_iso(),
            },
        )

    def plan(self, index: DatIndex, inventory: Inventory) -> dict[str, int]:
        reusable = []
        buildable = []
        missing = []
        for rel, target in sorted(index.all_targets().items()):
            if self._can_reuse_existing(rel, target):
                reusable.append(rel)
                continue
            missing_entries = [
                f"{entry['name']} size={entry['size']} crc={entry['crc']}"
                for entry in target["entries"]
                if not inventory.candidates(entry)
            ]
            if missing_entries:
                missing.append(f"{rel}: " + "; ".join(missing_entries[:10]))
            else:
                buildable.append(rel)
        self.report.write("rebuild_plan_reusable.txt", reusable)
        self.report.write("rebuild_plan_buildable.txt", buildable)
        self.report.write("rebuild_plan_missing.txt", missing)
        result = {"reusable": len(reusable), "buildable": len(buildable), "missing": len(missing)}
        self.report.summary["rebuild_plan"] = result
        return result

    def _action(self, manifest_hash: str, input_fp: str, dat_hash: str) -> str:
        if self.cfg.rebuild_mode != "auto":
            return self.cfg.rebuild_mode
        cache = load_json(self.cfg.rebuild_cache_file, {})
        if (
            cache.get("dat_sha256") == dat_hash
            and cache.get("input_fingerprint") == input_fp
            and cache.get("target_manifest_sha256") == manifest_hash
        ):
            return "skip"
        return "full"

    def _reuse_existing(self, rel: str, target: dict[str, Any]) -> bool:
        src = self._existing_path(rel)
        if not src.exists():
            return False
        rec = self.indexer.index_one(src)
        if not archive_matches_target(rec, target):
            return False
        dst = self.cfg.clean / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        self.reused += 1
        return True

    def _can_reuse_existing(self, rel: str, target: dict[str, Any]) -> bool:
        src = self._existing_path(rel)
        if not src.exists():
            return False
        rec = self.indexer.index_one(src)
        return archive_matches_target(rec, target)

    def _existing_path(self, rel: str) -> Path:
        rel_path = Path(rel)
        if rel_path.parts[0] == "roms":
            return self.cfg.images / "roms" / rel_path.name
        return self.cfg.images / rel

    def _build_target(self, rel: str, target: dict[str, Any], inventory: Inventory) -> tuple[bool, str]:
        staging = self.cfg.raw / rel.replace("/", "__").replace(".7z", "")
        safe_rmtree(staging, self.cfg.work)
        staging.mkdir(parents=True, exist_ok=True)
        used = []
        for entry in target["entries"]:
            candidates = inventory.candidates(entry)
            if not candidates:
                return False, f"missing {entry['name']} size={entry['size']} crc={entry['crc']}"
            candidate = candidates[0]
            if not self._extract_entry(candidate, staging, entry["name"]):
                return False, f"failed to extract {entry['name']} from {candidate['archive']}"
            used.append(candidate["archive"])
        dst = self.cfg.clean / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        tmp = dst.with_suffix(".7z.tmp")
        tmp.unlink(missing_ok=True)
        names = sorted(p.name for p in staging.iterdir() if p.is_file())
        if not names:
            return False, "no staged files"
        self.shell.run([self.cfg.sevenz_bin, "a", "-t7z", "-mx=9", "-mmt=1", tmp.resolve(), *names], cwd=staging)
        tmp.replace(dst)
        rec = self.indexer.index_one(dst)
        if not archive_matches_target(rec, target):
            return False, "created archive does not match expected entries"
        self.created += 1
        return True, "ok"

    def _extract_entry(self, candidate: dict[str, Any], staging: Path, out_name: str) -> bool:
        archive = Path(candidate["archive"])
        entry_path = candidate["path"]
        tmpdir = staging / ".extract_tmp"
        safe_rmtree(tmpdir, self.cfg.work)
        tmpdir.mkdir(parents=True, exist_ok=True)
        proc = self.shell.capture([self.cfg.sevenz_bin, "e", "-y", f"-o{tmpdir}", archive, entry_path], check=False)
        if proc.returncode != 0:
            return False
        extracted = tmpdir / Path(entry_path).name
        if not extracted.exists():
            files = [p for p in tmpdir.iterdir() if p.is_file()]
            if len(files) != 1:
                return False
            extracted = files[0]
        dst = staging / Path(out_name).name
        if dst.exists():
            dst.unlink()
        extracted.replace(dst)
        safe_rmtree(tmpdir, self.cfg.work)
        return True
