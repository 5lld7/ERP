#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
umask 077
if [ ! -x .venv/bin/python ]; then
  printf 'Run bash scripts/install.sh first.\n' >&2
  exit 1
fi
exec .venv/bin/python server.py "$@"
