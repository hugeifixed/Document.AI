#!/usr/bin/env python3
"""Run the repository quality gates consistently on Windows, macOS, and Linux."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
CLI = ROOT / "cli"


@dataclass(frozen=True)
class Check:
    label: str
    command: list[str]
    cwd: Path


def executable(candidates: list[Path], fallback_names: tuple[str, ...]) -> str:
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    for name in fallback_names:
        if found := shutil.which(name):
            return found
    checked = [str(path.relative_to(ROOT)) for path in candidates]
    checked.extend(f"PATH:{name}" for name in fallback_names)
    raise SystemExit(f"Missing executable. Checked {', '.join(checked)}.")


def backend_checks(python: str, schema_path: Path) -> list[Check]:
    prefix = [python, "-m"]
    return [
        Check(
            "Repository Python lint",
            [
                *prefix,
                "ruff",
                "check",
                "--config",
                "backend/pyproject.toml",
                "--ignore",
                "T201,S603",
                "scripts",
                "examples",
            ],
            ROOT,
        ),
        Check(
            "Repository Python formatting",
            [
                *prefix,
                "ruff",
                "format",
                "--check",
                "--config",
                "backend/pyproject.toml",
                "scripts",
                "examples",
            ],
            ROOT,
        ),
        Check("Backend lint", [*prefix, "ruff", "check", "."], BACKEND),
        Check("Backend formatting", [*prefix, "ruff", "format", "--check", "."], BACKEND),
        Check("Backend typing", [*prefix, "mypy", "config", "docai"], BACKEND),
        Check(
            "Django system check",
            [python, "manage.py", "check", "--settings=config.settings.test"],
            BACKEND,
        ),
        Check(
            "Migration drift",
            [
                python,
                "manage.py",
                "makemigrations",
                "--check",
                "--dry-run",
                "--settings=config.settings.test",
            ],
            BACKEND,
        ),
        Check(
            "OpenAPI schema",
            [
                python,
                "manage.py",
                "spectacular",
                "--validate",
                "--file",
                str(schema_path),
                "--settings=config.settings.test",
            ],
            BACKEND,
        ),
        Check(
            "Backend tests and coverage",
            [
                python,
                "-m",
                "pytest",
                "--cov=docai",
                "--cov-branch",
                "--cov-report=term-missing",
                "--cov-fail-under=80",
            ],
            BACKEND,
        ),
    ]


def frontend_checks(npm: str, *, browser: bool) -> list[Check]:
    checks = [
        Check("Frontend lint", [npm, "run", "lint"], FRONTEND),
        Check("Frontend typing", [npm, "run", "typecheck"], FRONTEND),
        Check("Frontend tests and coverage", [npm, "run", "test:coverage"], FRONTEND),
        Check("Frontend production build", [npm, "run", "build"], FRONTEND),
    ]
    if browser:
        checks.append(Check("Optional Chromium tests", [npm, "run", "test:browser"], FRONTEND))
    return checks


def cli_checks(python: str, uv: str, wheel_dir: Path) -> list[Check]:
    prefix = [python, "-m"]
    return [
        Check("CLI lint", [*prefix, "ruff", "check", "src", "tests"], CLI),
        Check(
            "CLI formatting",
            [*prefix, "ruff", "format", "--check", "src", "tests"],
            CLI,
        ),
        Check("CLI typing", [*prefix, "mypy", "src/docai_cli"], CLI),
        Check(
            "CLI tests and coverage",
            [
                *prefix,
                "pytest",
                "tests",
                "--cov=docai_cli",
                "--cov-branch",
                "--cov-report=term-missing",
                "--cov-fail-under=80",
            ],
            CLI,
        ),
        Check(
            "Standalone CLI wheel build",
            [
                uv,
                "build",
                "--offline",
                "--wheel",
                "--python",
                python,
                "--out-dir",
                str(wheel_dir),
                "--no-create-gitignore",
                str(CLI),
            ],
            ROOT,
        ),
        Check(
            "CLI remains independent of Django",
            [
                python,
                "-c",
                "import sys, docai_cli; assert 'django' not in sys.modules; print(docai_cli.__version__)",
            ],
            CLI,
        ),
    ]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", action="store_true", help="Run only backend checks.")
    parser.add_argument("--frontend", action="store_true", help="Run only frontend checks.")
    parser.add_argument("--cli", action="store_true", help="Run only standalone CLI checks.")
    parser.add_argument(
        "--browser",
        action="store_true",
        help="Also run the optional Playwright Chromium suite.",
    )
    parser.add_argument(
        "--python",
        help="Backend Python executable; defaults to backend/.venv or PATH.",
    )
    parser.add_argument(
        "--cli-python",
        help="CLI Python executable; defaults to cli/.venv or PATH.",
    )
    args = parser.parse_args()
    selected = sum((args.backend, args.frontend, args.cli))
    if selected > 1:
        parser.error(
            "Choose at most one of --backend, --frontend, or --cli; omit all to run all checks."
        )
    if args.browser and (args.backend or args.cli):
        parser.error("--browser requires frontend checks.")
    return args


def main() -> int:
    args = parse_args()
    selected = args.backend or args.frontend or args.cli
    run_backend = not selected or args.backend
    run_frontend = not selected or args.frontend
    run_cli = not selected or args.cli
    checks: list[Check] = []

    with tempfile.TemporaryDirectory(prefix="docai-verify-") as temporary:
        if run_backend:
            python = args.python or executable(
                [
                    BACKEND / ".venv" / "Scripts" / "python.exe",
                    BACKEND / ".venv" / "bin" / "python",
                ],
                (),
            )
            checks.extend(backend_checks(python, Path(temporary) / "openapi.yaml"))
        if run_frontend:
            npm = executable([], ("npm.cmd", "npm"))
            checks.extend(frontend_checks(npm, browser=args.browser))
        if run_cli:
            cli_python = args.cli_python or executable(
                [
                    CLI / ".venv" / "Scripts" / "python.exe",
                    CLI / ".venv" / "bin" / "python",
                ],
                (),
            )
            uv = executable([], ("uv",))
            checks.extend(cli_checks(cli_python, uv, Path(temporary) / "cli-wheel"))

        for index, check in enumerate(checks, start=1):
            print(f"\n[{index}/{len(checks)}] {check.label}", flush=True)
            result = subprocess.run(check.command, cwd=check.cwd, check=False)
            if result.returncode:
                print(
                    f"\nFAILED: {check.label} (exit {result.returncode})",
                    file=sys.stderr,
                )
                return result.returncode

    print(f"\nAll {len(checks)} checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
