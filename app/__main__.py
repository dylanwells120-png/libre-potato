"""Start the file server: python -m app"""

from __future__ import annotations

from pathlib import Path

import uvicorn

from app.config import Settings, load_env_file
from app.main import create_app


def main() -> None:
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
