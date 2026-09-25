"""Thin source-checkout launcher for any installed DocAI CLI command."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    command = ["uv", "run", "--project", str(root / "cli"), "docai", *sys.argv[1:]]
    try:
        return subprocess.run(command, cwd=root, check=False).returncode
    except FileNotFoundError:
        print(
            "uv is required. Install uv, or use `uv run --project cli docai ...`.",
            file=sys.stderr,
        )
        return 127


if __name__ == "__main__":
    raise SystemExit(main())
