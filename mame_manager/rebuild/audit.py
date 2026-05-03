from __future__ import annotations

from typing import Any

from .config import Config
from .dat import DatIndex
from .inventory import Inventory
from .report import ReportManager

class Auditor:
    def __init__(self, cfg: Config, report: ReportManager):
        self.cfg = cfg
        self.report = report

    def audit_roms(self, index: DatIndex, inventory: Inventory) -> dict[str, list[str]]:
        arcade = self._audit_targets(index.arcade_targets, inventory)
        software = self._audit_targets(index.software_targets, inventory)
        self.report.write("arcade_missing_roms.txt", arcade["missing_entries"])
        self.report.write("software_missing_roms.txt", software["missing_entries"])
        self.report.write("arcade_complete_sets.txt", arcade["complete_sets"])
        self.report.write("software_complete_sets.txt", software["complete_sets"])
        self.report.write("arcade_incomplete_sets.txt", arcade["incomplete_sets"])
        self.report.write("software_incomplete_sets.txt", software["incomplete_sets"])
        self.report.write("archive_errors.txt", inventory.bad_archives)
        self.report.summary["rom_sets"] = {
            "arcade": {
                "total": arcade["total_sets"],
                "complete": len(arcade["complete_sets"]),
                "incomplete": len(arcade["incomplete_sets"]),
            },
            "software": {
                "total": software["total_sets"],
                "complete": len(software["complete_sets"]),
                "incomplete": len(software["incomplete_sets"]),
            },
            "combined": {
                "total": arcade["total_sets"] + software["total_sets"],
                "complete": len(arcade["complete_sets"]) + len(software["complete_sets"]),
                "incomplete": len(arcade["incomplete_sets"]) + len(software["incomplete_sets"]),
            },
        }
        self.report.summary["rom_file_entries"] = {
            "arcade": {
                "total": arcade["total_entries"],
                "present": arcade["present_entries"],
                "missing": len(arcade["missing_entries"]),
            },
            "software": {
                "total": software["total_entries"],
                "present": software["present_entries"],
                "missing": len(software["missing_entries"]),
            },
            "combined": {
                "total": arcade["total_entries"] + software["total_entries"],
                "present": arcade["present_entries"] + software["present_entries"],
                "missing": len(arcade["missing_entries"]) + len(software["missing_entries"]),
            },
        }
        self.report.summary["missing_rom_entries"] = {
            "arcade": len(arcade["missing_entries"]),
            "software": len(software["missing_entries"]),
        }
        self.report.summary["archive_errors"] = len(inventory.bad_archives)
        return {"arcade": arcade["missing_entries"], "software": software["missing_entries"]}

    def _audit_targets(self, targets: dict[str, dict[str, Any]], inventory: Inventory) -> dict[str, Any]:
        missing_entries = []
        complete_sets = []
        incomplete_sets = []
        total_entries = 0
        present_entries = 0
        for rel, target in sorted(targets.items()):
            target_missing = []
            for entry in target["entries"]:
                total_entries += 1
                if not inventory.candidates(entry):
                    line = f"{rel}: {entry['name']} size={entry['size']} crc={entry['crc']}"
                    missing_entries.append(line)
                    target_missing.append(line)
                else:
                    present_entries += 1
            if target_missing:
                incomplete_sets.append(f"{rel}: missing {len(target_missing)}/{len(target['entries'])}")
            else:
                complete_sets.append(rel)
        return {
            "total_sets": len(targets),
            "total_entries": total_entries,
            "present_entries": present_entries,
            "missing_entries": missing_entries,
            "complete_sets": complete_sets,
            "incomplete_sets": incomplete_sets,
        }

