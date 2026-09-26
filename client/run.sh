#!/bin/sh
set -eu
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  ./setup.sh
fi
exec .venv/bin/python -m potato_client
