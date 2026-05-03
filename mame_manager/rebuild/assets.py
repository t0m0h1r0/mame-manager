from __future__ import annotations

import shutil
from pathlib import Path

from .common import SAMPLE_EXTS
from .config import Config
from .dat import DatIndex
from .report import ReportManager

class AssetManager:
    def __init__(self, cfg: Config, report: ReportManager):
        self.cfg = cfg
        self.report = report

    def report_chds(self, index: DatIndex, chds: dict[str, Path]) -> None:
        arcade = [f"{x['machine']}/{x['disk']}.chd sha1={x['sha1']}" for x in index.arcade_chds if x["sha1"] not in chds]
        software = [
            f"{x['softwarelist']}/{x['software']}/{x['disk']}.chd sha1={x['sha1']}"
            for x in index.software_chds
            if x["sha1"] not in chds
        ]
        self.report.write("arcade_missing_chds.txt", arcade)
        self.report.write("software_missing_chds.txt", software)
        self.report.summary["missing_chds"] = {"arcade": len(arcade), "software": len(software)}

    def place_chds(self, index: DatIndex, chds: dict[str, Path]) -> None:
        self.report_chds(index, chds)
        for item in index.arcade_chds:
            src = chds.get(item["sha1"])
            if not src:
                continue
            dst = self.cfg.clean / "chds" / item["machine"] / f"{item['disk']}.chd"
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        for item in index.software_chds:
            src = chds.get(item["sha1"])
            if not src:
                continue
            dst = self.cfg.clean / "software_chds" / item["softwarelist"] / item["software"] / f"{item['disk']}.chd"
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)

    def sample_sources(self) -> dict[str, Path]:
        found: dict[str, Path] = {}
        for root in (self.cfg.images / "samples", self.cfg.new):
            if not root.exists():
                continue
            for path in root.rglob("*"):
                if path.is_file() and path.suffix.lower() in SAMPLE_EXTS:
                    found[path.stem] = path
        return found

    def report_samples(self, samples: set[str]) -> None:
        found = self.sample_sources()
        missing = sorted(samples - set(found))
        self.report.write("missing_samples.txt", missing)
        self.report.summary["missing_samples"] = len(missing)

    def place_samples(self, samples: set[str]) -> None:
        found = self.sample_sources()
        missing = sorted(samples - set(found))
        for name in sorted(samples & set(found)):
            src = found[name]
            dst = self.cfg.clean / "samples" / src.name
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        self.report.write("missing_samples.txt", missing)
        self.report.summary["missing_samples"] = len(missing)

