"""Shorthand for common dev commands.

Usage: uv run run.py {lint|format|check|test|pre-commit}

Commands:
    lint        uv run ruff check ./src/ ./unit_test/
    format      uv run ruff format --check ./src/ ./unit_test/
    check       lint + format + uv run mypy ./src/
    test        uv run pytest unit_test/ -v
    pre-commit  uv run pre-commit run --all-files
"""

import subprocess
import sys

COMMANDS = {
    "lint": ["uv", "run", "ruff", "check", "./src/", "./unit_test/"],
    "format": ["uv", "run", "ruff", "format", "--check", "./src/", "./unit_test/"],
    "mypy": ["uv", "run", "mypy", "./src/"],
    "test": ["uv", "run", "pytest", "unit_test/", "-v"],
    "pre-commit": ["uv", "run", "pre-commit", "run", "--all-files"],
}


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] not in (*COMMANDS, "check"):
        if __doc__:
            sys.stderr.write(__doc__)
        return 1

    task = sys.argv[1]

    if task == "check":
        for name in ("lint", "format", "mypy"):
            rc = subprocess.run(COMMANDS[name], check=False).returncode  # noqa: S603 - literal command arrays, no user input
            if rc != 0:
                return rc
        return 0

    return subprocess.run(COMMANDS[task], check=False).returncode  # noqa: S603 - literal command arrays, no user input


if __name__ == "__main__":
    sys.exit(main())
