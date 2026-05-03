from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from .common import FatalError, quote_cmd

class Shell:
    def capture(self, cmd: list[str | os.PathLike[str]], cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(x) for x in cmd],
            cwd=str(cwd) if cwd else None,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=check,
        )

    def run(self, cmd: list[str | os.PathLike[str]], cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
        print("$ " + quote_cmd(cmd), flush=True)
        return self.capture(cmd, cwd=cwd, check=check)

    def run_to_log(self, cmd: list[str | os.PathLike[str]], log: Path, cwd: Path | None = None, check: bool = True) -> int:
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("w", encoding="utf-8") as f:
            f.write("$ " + quote_cmd(cmd) + "\n\n")
            proc = subprocess.run([str(x) for x in cmd], cwd=str(cwd) if cwd else None, text=True, stdout=f, stderr=subprocess.STDOUT)
        if check and proc.returncode != 0:
            raise FatalError(f"command failed ({proc.returncode}); see {log}")
        return proc.returncode

    @staticmethod
    def executable_exists(name: str | Path) -> bool:
        s = str(name)
        if "/" in s:
            return Path(s).exists() and os.access(s, os.X_OK)
        return shutil.which(s) is not None

