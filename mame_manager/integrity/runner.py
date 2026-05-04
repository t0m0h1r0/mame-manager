from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .cache import IntegrityCache
from .targets import IntegrityTarget
from ..config import RunConfig
from ..system import Shell, now_iso


class IntegrityRunner:
    def __init__(self, cfg: RunConfig, shell: Shell, cache: IntegrityCache):
        self.cfg = cfg
        self.shell = shell
        self.cache = cache

    def check(self, target: IntegrityTarget) -> dict[str, Any]:
        try:
            st = target.path.stat()
        except FileNotFoundError:
            return self._record(
                target=target,
                size=0,
                mtime_ns=0,
                status="broken",
                ok=False,
                error="file disappeared before integrity check",
            )

        cached = self.cache.lookup(target, st.st_size, st.st_mtime_ns)
        if cached:
            return cached
        if not target.checker:
            return self._record(
                target=target,
                size=st.st_size,
                mtime_ns=st.st_mtime_ns,
                status="skipped",
                ok=None,
                error="chdman not available",
            )

        self.cache.mark_miss()
        proc = self.shell.capture(self._command(target), check=False)
        status = "ok" if proc.returncode == 0 else "broken"
        record = self._record(
            target=target,
            size=st.st_size,
            mtime_ns=st.st_mtime_ns,
            status=status,
            ok=proc.returncode == 0,
            error=None if proc.returncode == 0 else proc.stdout[-4000:],
        )
        self.cache.store(record)
        return record

    def _command(self, target: IntegrityTarget) -> list[str | os.PathLike[str]]:
        if target.kind == "archive":
            return [self.cfg.sevenz_bin, "t", "-bd", target.path]
        if not target.checker:
            raise ValueError("CHD target has no checker")
        return [target.checker, "verify", "-i", target.path]

    @staticmethod
    def _record(
        target: IntegrityTarget,
        size: int,
        mtime_ns: int,
        status: str,
        ok: bool | None,
        error: str | None,
    ) -> dict[str, Any]:
        return {
            "path": target.key,
            "kind": target.kind,
            "size": size,
            "mtime_ns": mtime_ns,
            "checker": target.checker,
            "status": status,
            "ok": ok,
            "error": error,
            "checked_at": now_iso(),
        }
