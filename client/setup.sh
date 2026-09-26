#!/bin/sh
# Create a virtualenv for the desktop client. The client itself uses only the Python standard library.
set -eu
cd "$(dirname "$0")"
if ! python3 -c 'import tkinter'; then
  echo "This Python has no Tk window toolkit."
  echo "On Debian: sudo apt install python3-tk"
  exit 1
fi
python3 -m venv .venv
echo "Ready. Start the app with ./run.sh"
