from __future__ import annotations

import sys

from .options import parse_run_config
from .config import RunConfig
from .app import MameRebuildApp


def parse_args(argv: list[str]) -> RunConfig:
    return parse_run_config(argv)


def main(argv: list[str] | None = None) -> int:
    return MameRebuildApp(parse_run_config(argv if argv is not None else sys.argv[1:])).run()


if __name__ == "__main__":
    raise SystemExit(main())
