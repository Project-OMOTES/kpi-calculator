"""Run pre-commit hooks and optionally deeper analysis tools.

Usage:
    uv run check.py           # pre-commit run --all-files (ruff, mypy, pytest)
    uv run check.py --full    # above + pylint code analysis (duplicates, complexity, locals)
"""

import subprocess
import sys


def _run(cmd: list[str], *, header: str) -> int:
    print(f"\n{'=' * 60}")  # noqa: T201
    print(f"  {header}")  # noqa: T201
    print(f"{'=' * 60}")  # noqa: T201
    return subprocess.run(cmd, check=False).returncode  # noqa: S603 - all commands are hardcoded literals in this file; no user input reaches subprocess


def main() -> int:
    full = "--full" in sys.argv

    rc = _run(
        ["uv", "run", "pre-commit", "run", "--all-files"],
        header="pre-commit (ruff, mypy, pytest, file checks)",
    )

    if not full:
        return rc

    # Analysis tools — produce findings that require human judgement, not hard failures.
    # Exit code is the worst non-zero RC across all tools, but analysis failures
    # do not override a pre-commit failure.
    analysis_rc = 0

    analysis_rc |= _run(
        [
            "uv",
            "run",
            "pylint",
            "src/",
            "--disable=all",
            "--enable=similarities,R0914,R0912,R0915",
            "--min-similarity-lines=6",
            "--max-locals=16",
            # xml_time_series_adapter.py is testing-only and excluded from all linting
            "--ignore=xml_time_series_adapter.py",
        ],
        header="pylint — code analysis (duplicates, complexity, locals)",
    )

    return rc or analysis_rc


if __name__ == "__main__":
    sys.exit(main())
