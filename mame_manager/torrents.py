from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from .runtime import FatalError
from .settings import RunConfig
from .reports import ReportManager

class TorrentPlanner:
    def __init__(self, cfg: RunConfig, report: ReportManager):
        self.cfg = cfg
        self.report = report

    def plan(self, missing_roms: dict[str, list[str]], archive_errors: list[str]) -> None:
        if not self.cfg.torrent_plan:
            return
        torrent_files = self._read_torrent_file_list(self.cfg.torrent_plan)
        torrent_by_basename = defaultdict(list)
        torrent_by_norm = {}
        for item in torrent_files:
            norm = self._norm(item)
            torrent_by_norm[norm] = item
            torrent_by_basename[Path(norm).name].append(item)

        targets = self._missing_targets(missing_roms)
        broken_names = self._broken_archive_names(archive_errors)
        wanted = []
        unmatched = []
        mapping = ["target\ttorrent_file"]

        for target in sorted(targets):
            matches = self._matches_for_target(target, torrent_by_basename, torrent_by_norm)
            if matches:
                for match in matches:
                    wanted.append(match)
                    mapping.append(f"{target}\t{match}")
            else:
                unmatched.append(target)

        broken_matches = []
        broken_unmatched = []
        for name in sorted(broken_names):
            matches = torrent_by_basename.get(name, [])
            if matches:
                broken_matches.extend(matches)
            else:
                broken_unmatched.append(name)

        wanted_unique = sorted(set(wanted))
        broken_unique = sorted(set(broken_matches))
        self.report.write("torrent_wanted_files.txt", wanted_unique)
        self.report.write("torrent_unmatched_targets.txt", unmatched)
        self.report.write("torrent_target_map.tsv", mapping)
        self.report.write("torrent_broken_archive_wanted_files.txt", broken_unique)
        self.report.write("torrent_broken_archive_unmatched.txt", broken_unmatched)
        self.report.summary["torrent_plan"] = {
            "source_file_count": len(torrent_files),
            "missing_targets": len(targets),
            "wanted_files": len(wanted_unique),
            "unmatched_targets": len(unmatched),
            "broken_archive_wanted_files": len(broken_unique),
            "broken_archive_unmatched": len(broken_unmatched),
        }

    def _read_torrent_file_list(self, path: Path) -> list[str]:
        if not path.exists():
            raise FatalError(f"torrent file list not found: {path}")
        rows = []
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            item = line.strip()
            if not item or item.startswith("#"):
                continue
            rows.append(item)
        return rows

    @staticmethod
    def _norm(path: str) -> str:
        return path.strip().replace("\\", "/").lstrip("./")

    @staticmethod
    def _missing_targets(missing_roms: dict[str, list[str]]) -> set[str]:
        targets = set()
        for rows in missing_roms.values():
            for row in rows:
                target = row.split(":", 1)[0].strip()
                if target:
                    targets.add(target)
        return targets

    @staticmethod
    def _broken_archive_names(archive_errors: list[str]) -> set[str]:
        names = set()
        for row in archive_errors:
            path = row.split(":", 1)[0].strip()
            if path:
                names.add(Path(path).name)
        return names

    def _matches_for_target(
        self,
        target: str,
        torrent_by_basename: dict[str, list[str]],
        torrent_by_norm: dict[str, str],
    ) -> list[str]:
        target_norm = self._norm(target)
        target_path = Path(target_norm)
        stem = target_path.stem
        exts = [".zip", ".7z"]
        candidate_suffixes = []
        if target_norm.startswith("roms/"):
            candidate_suffixes.extend([f"{stem}{ext}" for ext in exts])
        else:
            parent = target_path.parent.as_posix()
            candidate_suffixes.extend([f"{parent}/{stem}{ext}" for ext in exts])
            candidate_suffixes.extend([f"{stem}{ext}" for ext in exts])

        matches = []
        for suffix in candidate_suffixes:
            basename = Path(suffix).name
            matches.extend(torrent_by_basename.get(basename, []))
            norm_suffix = self._norm(suffix)
            for norm, original in torrent_by_norm.items():
                if norm == norm_suffix or norm.endswith("/" + norm_suffix):
                    matches.append(original)
        return sorted(set(matches))

