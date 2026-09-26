"""Settings come from the environment, with .env as a fallback."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from app.passwords import PasswordHashError, parse_password_hash

APP_DIR = Path(__file__).resolve().parent.parent


def load_env_file(path: Path) -> None:
    """Load KEY=VALUE lines. Existing environment variables win."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        if key:
            os.environ.setdefault(key, value)


@dataclass(frozen=True)
class Settings:
    username: str
    password_hash: str
    secret_key: str
    files_root: Path
    host: str
    port: int
    https_only: bool
    max_upload_bytes: int

    def __post_init__(self) -> None:
        root = Path(self.files_root).expanduser().resolve()
        object.__setattr__(self, "files_root", root)
        if len(self.secret_key) < 32:
            raise ValueError("LIBRE_POTATO_SECRET_KEY must be at least 32 characters.")
        try:
            parse_password_hash(self.password_hash)
        except PasswordHashError as exc:
            raise ValueError(str(exc)) from exc
        if not self.username or len(self.username) > 64:
            raise ValueError("LIBRE_POTATO_USERNAME must be 1 to 64 characters.")
        if any(ch.isspace() for ch in self.username):
            raise ValueError("LIBRE_POTATO_USERNAME cannot contain spaces.")
        if root == Path("/"):
            raise ValueError("Refusing to serve the whole filesystem. Pick a folder.")
        if root == APP_DIR:
            raise ValueError("FILES_ROOT cannot be the Libre Potato application folder.")
        if not 1 <= self.port <= 65535:
            raise ValueError("LIBRE_POTATO_PORT must be between 1 and 65535.")
        if self.max_upload_bytes < 1:
            raise ValueError("LIBRE_POTATO_MAX_UPLOAD_MB must be at least 1.")

    @classmethod
    def from_env(cls) -> Settings:
        errors: list[str] = []
        username = os.environ.get("LIBRE_POTATO_USERNAME", "").strip()
        password_hash = os.environ.get("LIBRE_POTATO_PASSWORD_HASH", "").strip()
        secret_key = os.environ.get("LIBRE_POTATO_SECRET_KEY", "").strip()
        root_raw = os.environ.get("LIBRE_POTATO_FILES_ROOT", "").strip()
        host = os.environ.get("LIBRE_POTATO_HOST", "127.0.0.1").strip() or "127.0.0.1"
        https_only = _as_bool(os.environ.get("LIBRE_POTATO_HTTPS_ONLY", "0"))

        if not username:
            errors.append("Set LIBRE_POTATO_USERNAME.")
        if not password_hash or password_hash.startswith("replace-with"):
            errors.append("Set LIBRE_POTATO_PASSWORD_HASH. Run: python -m app.hash_password")
        if not secret_key or secret_key.startswith("replace-with") or len(secret_key) < 32:
            errors.append(
                'Set LIBRE_POTATO_SECRET_KEY. Run: python -c "import secrets; print(secrets.token_urlsafe(32))"'
            )
        if not root_raw:
            errors.append("Set LIBRE_POTATO_FILES_ROOT to the folder you want to reach.")

        try:
            port = int(os.environ.get("LIBRE_POTATO_PORT", "8787"))
        except ValueError:
            port = 0
            errors.append("LIBRE_POTATO_PORT must be a number.")
        try:
            upload_mb = int(os.environ.get("LIBRE_POTATO_MAX_UPLOAD_MB", "512"))
        except ValueError:
            upload_mb = 0
            errors.append("LIBRE_POTATO_MAX_UPLOAD_MB must be a number.")

        root = Path(root_raw).expanduser() if root_raw else Path("/")
        if root_raw and not root.is_dir():
            errors.append(f"Create this folder first, then point FILES_ROOT at it: {root}")

        if errors:
            raise SystemExit("Libre Potato is not configured:\n- " + "\n- ".join(errors))

        settings = cls(
            username=username,
            password_hash=password_hash,
            secret_key=secret_key,
            files_root=root,
            host=host,
            port=port,
            https_only=https_only,
            max_upload_bytes=upload_mb * 1024 * 1024,
        )
        _warn_about_root(settings.files_root)
        if settings.host in {"0.0.0.0", "::"}:
            print(
                "Libre Potato is listening on every interface. Keep the port firewalled, "
                "or use 127.0.0.1 with Tailscale.",
                file=sys.stderr,
            )
        return settings


def _as_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _warn_about_root(root: Path) -> None:
    home = Path.home().resolve()
    if root == home:
        print(
            "Warning: FILES_ROOT is your home directory. A dedicated folder is safer.",
            file=sys.stderr,
        )
    try:
        APP_DIR.relative_to(root)
    except ValueError:
        return
    if APP_DIR != root:
        print(
            "Warning: FILES_ROOT contains the app folder. Keep the app and your files separate.",
            file=sys.stderr,
        )
