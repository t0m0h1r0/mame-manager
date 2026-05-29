from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .qbittorrent_client import (
    QBittorrentClient,
    QBittorrentConfig,
    QBittorrentError,
    normalize_torrent_path,
    select_file_ids,
    torrent_display_name,
)
from .system import FatalError
from .config import RunConfig
from .reporting import ReportManager


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


@dataclass(frozen=True)
class QBittorrentTorrentPlan:
    torrent_hash: str
    torrent_name: str
    files: list[dict[str, Any]]
    plan: TorrentPlan

    @property
    def score(self) -> int:
        return len(self.plan.download_files())


class TorrentPlanner:
    def __init__(self, cfg: RunConfig, report: ReportManager):
        self.cfg = cfg
        self.report = report

    def plan(
        self,
        missing_roms: dict[str, list[str]],
        archive_errors: list[str],
        missing_chds: dict[str, list[str]] | None = None,
    ) -> TorrentPlan | None:
        if not self.cfg.torrent_plan:
            return None
        plan = self.plan_from_file_list(
            self._read_torrent_file_list(self.cfg.torrent_plan),
            missing_roms,
            archive_errors,
            missing_chds,
        )
        self.write_plan(plan)
        return plan

    def plan_from_file_list(
        self,
        torrent_files: list[str],
        missing_roms: dict[str, list[str]],
        archive_errors: list[str],
        missing_chds: dict[str, list[str]] | None = None,
    ) -> TorrentPlan:
        torrent_by_basename = defaultdict(list)
        torrent_by_norm = {}
        for item in torrent_files:
            norm = self._norm(item)
            torrent_by_norm[norm] = item
            torrent_by_basename[Path(norm).name].append(item)

        targets = self._missing_targets(missing_roms, missing_chds)
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
    def _missing_targets(
        missing_roms: dict[str, list[str]],
        missing_chds: dict[str, list[str]] | None = None,
    ) -> set[str]:
        targets = set()
        for rows in missing_roms.values():
            for row in rows:
                target = TorrentPlanner._target_from_row(row)
                if target:
                    targets.add(target)
        for rows in (missing_chds or {}).values():
            for row in rows:
                target = TorrentPlanner._target_from_row(row)
                if target:
                    targets.add(target)
        return targets

    @staticmethod
    def _target_from_row(row: str) -> str:
        return row.split(":", 1)[0].split(" sha1=", 1)[0].strip()

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
        if target_path.suffix.lower() == ".chd":
            matches = []
            for norm, original in torrent_by_norm.items():
                if norm == target_norm or norm.endswith("/" + target_norm):
                    matches.append(original)
            return sorted(set(matches))

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

    def apply(
        self,
        missing_roms: dict[str, list[str]],
        archive_errors: list[str],
        missing_chds: dict[str, list[str]] | None = None,
    ) -> None:
        if not self.cfg.qbittorrent_enabled:
            return
        if not any(missing_roms.values()) and not any((missing_chds or {}).values()) and not archive_errors:
            self.report.note("qBittorrent skipped: no missing ROM/CHD targets or broken archives")
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
            torrent_plans = self._matching_torrent_plans(client, missing_roms, archive_errors, missing_chds)
            combined_plan = self._combine_plans([item.plan for item in torrent_plans])
            self.planner.write_plan(combined_plan)

            selected_report = []
            unmatched_report = []
            per_torrent = []
            total_files = 0
            total_selected = 0
            total_unmatched = 0

            for item in torrent_plans:
                wanted = {normalize_torrent_path(path) for path in item.plan.download_files()}
                selected_ids, unmatched = select_file_ids(item.files, wanted)
                if wanted and not selected_ids:
                    raise FatalError(
                        f"qBittorrent plan for {item.torrent_name} found wanted files but no file IDs matched; refusing to change priorities"
                    )
                selected_names = [normalize_torrent_path(str(item.files[i].get("name", ""))) for i in selected_ids]
                selected_report.extend(f"{item.torrent_hash}\t{item.torrent_name}\t{name}" for name in selected_names)
                unmatched_report.extend(f"{item.torrent_hash}\t{item.torrent_name}\t{name}" for name in unmatched)
                total_files += len(item.files)
                total_selected += len(selected_ids)
                total_unmatched += len(unmatched)
                per_torrent.append(
                    {
                        "torrent_hash": item.torrent_hash,
                        "torrent_name": item.torrent_name,
                        "torrent_files": len(item.files),
                        "wanted_files": len(wanted),
                        "selected_files": len(selected_ids),
                        "unmatched_wanted_files": len(unmatched),
                        "resumed": False,
                    }
                )
                print(f"qBittorrent torrent: {item.torrent_name} ({item.torrent_hash})", flush=True)
                print(f"qBittorrent selected files: {len(selected_ids)}/{len(item.files)}", flush=True)
                print(f"qBittorrent unmatched wanted files: {len(unmatched)}", flush=True)

                if self.cfg.qbittorrent_dry_run:
                    continue
                all_ids = list(range(len(item.files)))
                client.set_file_priority(item.torrent_hash, all_ids, self.cfg.qbittorrent_skip_priority)
                client.set_file_priority(item.torrent_hash, selected_ids, self.cfg.qbittorrent_priority)
                if self.cfg.qbittorrent_resume:
                    client.resume(item.torrent_hash)
                    per_torrent[-1]["resumed"] = True

            self.report.write("qbittorrent_selected_files.txt", selected_report)
            self.report.write("qbittorrent_unmatched_wanted_files.txt", unmatched_report)
            self.report.summary["qbittorrent"] = {
                "torrents": len(torrent_plans),
                "torrent_files": total_files,
                "wanted_files": len(combined_plan.download_files()),
                "selected_files": total_selected,
                "unmatched_wanted_files": total_unmatched,
                "dry_run": self.cfg.qbittorrent_dry_run,
                "resumed": bool(self.cfg.qbittorrent_resume and not self.cfg.qbittorrent_dry_run),
                "per_torrent": per_torrent,
            }
            if self.cfg.qbittorrent_dry_run:
                self.report.note("qBittorrent dry-run: no file priorities changed")
        except QBittorrentError as exc:
            raise FatalError(str(exc)) from exc

    def _matching_torrent_plans(
        self,
        client: QBittorrentClient,
        missing_roms: dict[str, list[str]],
        archive_errors: list[str],
        missing_chds: dict[str, list[str]] | None = None,
    ) -> list[QBittorrentTorrentPlan]:
        if self.cfg.qbittorrent_hash:
            files = client.torrent_files(self.cfg.qbittorrent_hash)
            plan = self._plan_for_files(files, missing_roms, archive_errors, missing_chds)
            if not plan.download_files():
                raise FatalError("specified qBittorrent torrent contains no missing or broken targets")
            return [
                QBittorrentTorrentPlan(
                    torrent_hash=self.cfg.qbittorrent_hash,
                    torrent_name=self.cfg.qbittorrent_hash,
                    files=files,
                    plan=plan,
                )
            ]

        torrents = client.torrents()
        if self.cfg.qbittorrent_name:
            needle = self.cfg.qbittorrent_name.lower()
            torrents = [torrent for torrent in torrents if needle in torrent_display_name(torrent).lower()]
        if not torrents:
            raise FatalError("no qBittorrent torrents matched the selection criteria")

        matched = []
        for torrent in torrents:
            torrent_hash = torrent.get("hash")
            if not torrent_hash:
                continue
            files = client.torrent_files(str(torrent_hash))
            plan = self._plan_for_files(files, missing_roms, archive_errors, missing_chds)
            if not plan.download_files():
                continue
            matched.append(
                QBittorrentTorrentPlan(
                    torrent_hash=str(torrent_hash),
                    torrent_name=torrent_display_name(torrent),
                    files=files,
                    plan=plan,
                )
            )
        if not matched:
            raise FatalError("no qBittorrent torrents contain missing or broken targets")
        matched.sort(key=lambda item: (-item.score, item.torrent_name, item.torrent_hash))
        return matched

    def _plan_for_files(
        self,
        files: list[dict[str, Any]],
        missing_roms: dict[str, list[str]],
        archive_errors: list[str],
        missing_chds: dict[str, list[str]] | None = None,
    ) -> TorrentPlan:
        names = [str(file_info.get("name", "")) for file_info in files]
        return self.planner.plan_from_file_list(names, missing_roms, archive_errors, missing_chds)

    @staticmethod
    def _combine_plans(plans: list[TorrentPlan]) -> TorrentPlan:
        target_mapping = ["target\ttorrent_file"]
        wanted_files = set()
        broken_archive_wanted_files = set()
        missing_targets = 0
        source_file_count = 0
        unmatched_targets: set[str] | None = None
        broken_archive_unmatched: set[str] | None = None

        for plan in plans:
            source_file_count += plan.source_file_count
            missing_targets = max(missing_targets, plan.missing_targets)
            wanted_files.update(plan.wanted_files)
            broken_archive_wanted_files.update(plan.broken_archive_wanted_files)
            target_mapping.extend(plan.target_mapping[1:])
            plan_unmatched = set(plan.unmatched_targets)
            broken_unmatched = set(plan.broken_archive_unmatched)
            unmatched_targets = plan_unmatched if unmatched_targets is None else unmatched_targets & plan_unmatched
            broken_archive_unmatched = (
                broken_unmatched
                if broken_archive_unmatched is None
                else broken_archive_unmatched & broken_unmatched
            )

        return TorrentPlan(
            source_file_count=source_file_count,
            missing_targets=missing_targets,
            wanted_files=sorted(wanted_files),
            unmatched_targets=sorted(unmatched_targets or set()),
            target_mapping=target_mapping,
            broken_archive_wanted_files=sorted(broken_archive_wanted_files),
            broken_archive_unmatched=sorted(broken_archive_unmatched or set()),
        )
