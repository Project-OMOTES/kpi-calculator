#!/usr/bin/env sh

. .venv/bin/activate

# Install the package in development mode with dev dependencies
pip install -e ".[dev]"

python -m mypy ./src/kpicalculator ./unit_test/
