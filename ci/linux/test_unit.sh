#!/usr/bin/env sh

. .venv/bin/activate

# Install the package in development mode
pip install -e .

PYTHONPATH='$PYTHONPATH:src/' pytest --junit-xml=test-results.xml unit_test/
