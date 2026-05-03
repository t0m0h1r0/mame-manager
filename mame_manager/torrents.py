from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .qbittorrent import (
    QBittorrentClient,
    QBittorrentConfig,
    QBittorrentError,
    normalize_torrent_path,
    select_file_ids,
    torrent_display_name,
)
from .runtime import FatalError
from .settings import RunConfig
from .reports import ReportManager


@dataclass(frozen=True)
class TorrentPlan:
    source_file_count: int
    missing_targets: int
    wanted_files: list[str]
    unmatched_targets: list[str]
    target_mapping: list[str]
    broken_archive_wanted_files: list[str]
    broken_archive_unmatched: list[str]

    def download_files(self) -> list[str]:
        return sorted(set(self.wanted_files) | set(self.broken_archive_wanted_files))


class TorrentPlanner:
    def __init__(self, cfg: RunConfig, report: ReportManager):
        self.cfg = cfg
        self.report = report

    def plan(self, missing_roms: dict[str, list[str]], archive_errors: list[str]) -> TorrentPlan | None:
        if not self.cfg.torrent_plan:
            return None
        plan = self.plan_from_file_list(self._read_torrent_file_list(self.cfg.torrent_plan), missing_roms, archive_errors)
        self.write_plan(plan)
        return plan

    def plan_from_file_list(
        self,
        torrent_files: list[str],
        missing_roms: dict[str, list[str]],
        archive_errors: list[str],
    ) -> TorrentPlan:
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
        return TorrentPlan(
            source_file_count=len(torrent_files),
            missing_targets=len(targets),
            wanted_files=wanted_unique,
            unmatched_targets=unmatched,
            target_mapping=mapping,
            broken_archive_wanted_files=broken_unique,
            broken_archive_unmatched=broken_unmatched,
        )

    def write_plan(self, plan: TorrentPlan) -> None:
        self.report.write("torrent_wanted_files.txt", plan.wanted_files)
        self.report.write("torrent_unmatched_targets.txt", plan.unmatched_targets)
        self.report.write("torrent_target_map.tsv", plan.target_mapping)
        self.report.write("torrent_broken_archive_wanted_files.txt", plan.broken_archive_wanted_files)
        self.report.write("torrent_broken_archive_unmatched.txt", plan.broken_archive_unmatched)
        self.report.summary["torrent_plan"] = {
            "source_file_count": plan.source_file_count,
            "missing_targets": plan.missing_targets,
            "wanted_files": len(plan.wanted_files),
            "unmatched_targets": len(plan.unmatched_targets),
            "broken_archive_wanted_files": len(plan.broken_archive_wanted_files),
            "broken_archive_unmatched": len(plan.broken_archive_unmatched),
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


class QBittorrentDownloadManager:
    def __init__(self, cfg: RunConfig, report: ReportManager):
        self.cfg = cfg
        self.report = report
        self.planner = TorrentPlanner(cfg, report)

    def apply(self, missing_roms: dict[str, list[str]], archive_errors: list[str]) -> None:
        if not self.cfg.qbittorrent_enabled:
            return
        if not any(missing_roms.values()) and not archive_errors:
            self.report.note("qBittorrent skipped: no missing ROM targets or broken archives")
            self.report.summary["qbittorrent"] = {"wanted_files": 0, "selected_files": 0, "dry_run": self.cfg.qbittorrent_dry_run}
            return
        assert self.cfg.qbittorrent_url is not None
        assert self.cfg.qbittorrent_password is not None
        client = QBittorrentClient(
            QBittorrentConfig(
                self.cfg.qbittorrent_url,
                self.cfg.qbittorrent_user,
                self.cfg.qbittorrent_password,
                self.cfg.qbittorrent_timeout,
            )
        )
        try:
            client.login()
            torrent_hash, torrent_name, files, plan = self._choose_torrent(client, missing_roms, archive_errors)
            wanted = {normalize_torrent_path(path) for path in plan.download_files()}
            selected_ids, unmatched = select_file_ids(files, wanted)
            if wanted and not selected_ids:
                raise FatalError("qBittorrent plan found wanted files but no torrent file IDs matched; refusing to change priorities")
            selected_names = [normalize_torrent_path(str(files[i].get("name", ""))) for i in selected_ids]
            self.planner.write_plan(plan)
            self.report.write("qbittorrent_selected_files.txt", selected_names)
            self.report.write("qbittorrent_unmatched_wanted_files.txt", unmatched)
            self.report.summary["qbittorrent"] = {
                "torrent_hash": torrent_hash,
                "torrent_name": torrent_name,
                "torrent_files": len(files),
                "wanted_files": len(wanted),
                "selected_files": len(selected_ids),
                "unmatched_wanted_files": len(unmatched),
                "dry_run": self.cfg.qbittorrent_dry_run,
                "resumed": False,
            }
            print(f"qBittorrent torrent: {torrent_name} ({torrent_hash})", flush=True)
            print(f"qBittorrent selected files: {len(selected_ids)}/{len(files)}", flush=True)
            print(f"qBittorrent unmatched wanted files: {len(unmatched)}", flush=True)
            if self.cfg.qbittorrent_dry_run:
                self.report.note("qBittorrent dry-run: no file priorities changed")
                return
            all_ids = list(range(len(files)))
            client.set_file_priority(torrent_hash, all_ids, self.cfg.qbittorrent_skip_priority)
            client.set_file_priority(torrent_hash, selected_ids, self.cfg.qbittorrent_priority)
            if self.cfg.qbittorrent_resume:
                client.resume(torrent_hash)
                self.report.summary["qbittorrent"]["resumed"] = True
        except QBittorrentError as exc:
            raise FatalError(str(exc)) from exc

    def _choose_torrent(
        self,
        client: QBittorrentClient,
        missing_roms: dict[str, list[str]],
        archive_errors: list[str],
    ) -> tuple[str, str, list[dict[str, Any]], TorrentPlan]:
        if self.cfg.qbittorrent_hash:
            files = client.torrent_files(self.cfg.qbittorrent_hash)
            plan = self._plan_for_files(files, missing_roms, archive_errors)
            return self.cfg.qbittorrent_hash, self.cfg.qbittorrent_hash, files, plan

        torrents = client.torrents()
        if self.cfg.qbittorrent_name:
            needle = self.cfg.qbittorrent_name.lower()
            torrents = [torrent for torrent in torrents if needle in torrent_display_name(torrent).lower()]
        if not torrents:
            raise FatalError("no qBittorrent torrents matched the selection criteria")

        scored = []
        for torrent in torrents:
            torrent_hash = torrent.get("hash")
            if not torrent_hash:
                continue
            files = client.torrent_files(str(torrent_hash))
            plan = self._plan_for_files(files, missing_roms, archive_errors)
            score = len(plan.download_files())
            scored.append(
                {
                    "hash": str(torrent_hash),
                    "name": torrent_display_name(torrent),
                    "files": files,
                    "plan": plan,
                    "score": score,
                }
            )
        if not scored:
            raise FatalError("could not inspect any qBittorrent torrent files")
        scored.sort(key=lambda item: (-int(item["score"]), str(item["name"])))
        best = scored[0]
        if best["score"] == 0:
            raise FatalError("no qBittorrent torrent contains missing or broken targets")
        ties = [item for item in scored if item["score"] == best["score"]]
        if len(ties) > 1:
            names = ", ".join(f"{item['name']} ({item['hash']})" for item in ties[:10])
            raise FatalError(
                f"multiple qBittorrent torrents have the same best match score {best['score']}; "
                f"use --qbittorrent-hash or --qbittorrent-name. Candidates: {names}"
            )
        return str(best["hash"]), str(best["name"]), best["files"], best["plan"]

    def _plan_for_files(
        self,
        files: list[dict[str, Any]],
        missing_roms: dict[str, list[str]],
        archive_errors: list[str],
    ) -> TorrentPlan:
        names = [str(file_info.get("name", "")) for file_info in files]
        return self.planner.plan_from_file_list(names, missing_roms, archive_errors)
