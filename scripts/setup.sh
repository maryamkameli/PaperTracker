#!/bin/bash
# Make a virtual environment, install the two dependencies, and copy the example topics file.
set -euo pipefail
cd "$(dirname "$0")/.."

if command -v uv >/dev/null 2>&1; then
  uv venv --python 3.12 .venv
  uv pip install --python .venv/bin/python -r requirements.txt
else
  PY=""
  for candidate in python3.13 python3.12 python3.11 python3.10 python3; do
    if command -v "$candidate" >/dev/null 2>&1; then PY="$candidate"; break; fi
  done
  [ -n "$PY" ] || { echo "No python3 found. Install one with: brew install python@3.12"; exit 1; }
  "$PY" -c 'import sys; sys.exit(sys.version_info < (3, 9))' || { echo "$PY is too old, PaperTracker needs 3.9 or newer"; exit 1; }
  "$PY" -m venv .venv
  .venv/bin/python -m pip install --quiet --upgrade pip
  .venv/bin/python -m pip install --quiet -r requirements.txt
fi

if [ ! -f topics.toml ]; then
  cp topics.example.toml topics.toml
  echo "Created topics.toml from the example. Edit it, then run: .venv/bin/python -m papertracker check"
else
  .venv/bin/python -m papertracker check
fi
