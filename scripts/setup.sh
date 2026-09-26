#!/bin/sh
# Create the virtualenv and a private .env on the Debian machine.
set -eu
cd "$(dirname "$0")/.."
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
if [ ! -f .env ]; then
  cp .env.example .env
  chmod 600 .env
  echo "Created .env. Edit LIBRE_POTATO_FILES_ROOT, then generate the password hash and secret."
else
  chmod 600 .env
fi
