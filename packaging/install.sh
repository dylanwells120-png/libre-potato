#!/bin/sh
# Install Libre Potato for the current user and start it on boot.
# Run this on the Debian machine after you download the repo. Do not use sudo.
set -eu

ROOT=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
SKIP_SERVICE=0
if [ "${1:-}" = "--skip-service" ]; then
  SKIP_SERVICE=1
fi

if [ "$(id -u)" -eq 0 ]; then
  echo "Run this as your normal user, not with sudo."
  echo "It installs a background service for your account so it can read your files."
  exit 1
fi

if ! python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)'; then
  echo "Libre Potato needs Python 3.11 or newer."
  echo "On Debian: sudo apt install python3 python3-venv python3-pip"
  exit 1
fi

CONFIG_DIR=${XDG_CONFIG_HOME:-$HOME/.config}/libre-potato
ENV_FILE=$CONFIG_DIR/env
PY=$ROOT/.venv/bin/python

if [ ! -x "$PY" ]; then
  python3 -m venv "$ROOT/.venv"
fi
"$PY" -m pip install --upgrade pip
"$PY" -m pip install -r "$ROOT/requirements.txt"

if [ -f "$ENV_FILE" ] && [ -z "${LIBRE_POTATO_RECONFIGURE:-}" ]; then
  echo "Keeping the existing settings in $ENV_FILE"
else
  if [ -n "${LIBRE_POTATO_INSTALL_NONINTERACTIVE:-}" ]; then
    : "${LIBRE_POTATO_FILES_ROOT:?Set LIBRE_POTATO_FILES_ROOT}"
    : "${LIBRE_POTATO_USERNAME:?Set LIBRE_POTATO_USERNAME}"
    : "${LIBRE_POTATO_PASSWORD:?Set LIBRE_POTATO_PASSWORD}"
    FILES_ROOT=$LIBRE_POTATO_FILES_ROOT
    USERNAME=$LIBRE_POTATO_USERNAME
    PASSWORD=$LIBRE_POTATO_PASSWORD
  else
    DEFAULT_ROOT=$HOME/Potato
    printf 'Folder to share [%s]: ' "$DEFAULT_ROOT"
    read -r FILES_ROOT
    FILES_ROOT=${FILES_ROOT:-$DEFAULT_ROOT}
    printf 'Username [%s]: ' "$USER"
    read -r USERNAME
    USERNAME=${USERNAME:-$USER}
    PASSWORD=${LIBRE_POTATO_PASSWORD:-}
  fi

  mkdir -p "$FILES_ROOT"
  FILES_ROOT=$(CDPATH= cd -- "$FILES_ROOT" && pwd)
  case $FILES_ROOT in
    *\"*|*\'*)
      echo "Use a folder path without quotes."
      exit 1
      ;;
  esac
  if [ "$FILES_ROOT" = "/" ] || [ "$FILES_ROOT" = "$ROOT" ]; then
    echo "Pick a dedicated folder, not / and not the Libre Potato program folder."
    exit 1
  fi

  if [ -z "$PASSWORD" ]; then
    HASH=$("$PY" -m app.hash_password)
  else
    HASH=$(LIBRE_POTATO_PASSWORD="$PASSWORD" "$PY" -m app.hash_password)
  fi
  SECRET=$("$PY" -c 'import secrets; print(secrets.token_urlsafe(32))')
  mkdir -p "$CONFIG_DIR"
  umask 077
  cat > "$ENV_FILE" <<EOF
LIBRE_POTATO_FILES_ROOT=$FILES_ROOT
LIBRE_POTATO_USERNAME=$USERNAME
LIBRE_POTATO_PASSWORD_HASH=$HASH
LIBRE_POTATO_SECRET_KEY=$SECRET
LIBRE_POTATO_HOST=127.0.0.1
LIBRE_POTATO_PORT=8787
LIBRE_POTATO_HTTPS_ONLY=0
LIBRE_POTATO_MAX_UPLOAD_MB=512
EOF
  chmod 600 "$ENV_FILE"
  unset PASSWORD HASH SECRET || true
  echo "Saved settings in $ENV_FILE"
fi

install_service() {
  UNIT_DIR=$HOME/.config/systemd/user
  mkdir -p "$UNIT_DIR"
  cat > "$UNIT_DIR/libre-potato.service" <<EOF
[Unit]
Description=Libre Potato file server
After=network-online.target

[Service]
WorkingDirectory=$ROOT
EnvironmentFile=$ENV_FILE
ExecStart=$PY -m app
Restart=on-failure
RestartSec=3
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=default.target
EOF
  systemctl --user daemon-reload
  systemctl --user enable --now libre-potato.service
  if command -v loginctl >/dev/null 2>&1; then
    if ! loginctl enable-linger "$USER" >/dev/null 2>&1; then
      echo "So it keeps running after you log out of GNOME, run:"
      echo "  sudo loginctl enable-linger $USER"
    fi
  fi
}

if [ "$SKIP_SERVICE" -eq 0 ] && command -v systemctl >/dev/null 2>&1; then
  install_service
  echo "Libre Potato is running on this machine at http://127.0.0.1:8787"
else
  echo "Start it in this folder with:"
  echo "  $PY -m app"
fi

cat <<EOF

From another device, install Tailscale on this machine and on that device, then run:
  sudo tailscale serve --bg 8787
Use the HTTPS address it prints in the Libre Potato client, or open it in a browser.
EOF
