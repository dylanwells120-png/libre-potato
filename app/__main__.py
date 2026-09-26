"""Start the file server: python -m app"""

from __future__ import annotations

import os
from pathlib import Path

import uvicorn

from app.config import Settings, load_env_file
from app.main import create_app


def main() -> None:
    config_home = Path(os.environ["XDG_CONFIG_HOME"]) if os.environ.get("XDG_CONFIG_HOME") else Path.home() / ".config"
    load_env_file(config_home / "libre-potato" / "env")
    load_env_file(Path.cwd() / ".env")
    settings = Settings.from_env()
    uvicorn.run(
        create_app(settings),
        host=settings.host,
        port=settings.port,
        log_level="info",
        proxy_headers=False,
        forwarded_allow_ips="127.0.0.1",
    )


if __name__ == "__main__":
    main()
