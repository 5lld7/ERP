#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
umask 077
python3 -c 'import sys; assert sys.version_info >= (3,12), "Python 3.12 or newer is required"'
if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv
fi
export PIP_CACHE_DIR="${PIP_CACHE_DIR:-$PWD/.local/pip-cache}"
.venv/bin/python -m pip install --disable-pip-version-check --require-hashes --only-binary=:all: -r requirements.txt
.venv/bin/python server.py --init-only
