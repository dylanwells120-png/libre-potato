"""The desktop client against a real Libre Potato server."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

SERVER_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SERVER_ROOT))

from app.passwords import hash_password  # noqa: E402
from potato_client.remote import PotatoClient  # noqa: E402

PASSWORD = "correct horse battery"


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _wait_until_ready(port: int, process: subprocess.Popen) -> None:
    for _ in range(50):
        if process.poll() is not None:
            output = process.stdout.read().decode() if process.stdout else ""
            raise RuntimeError(output or "Libre Potato stopped before it was ready.")
        try:
            with urlopen(f"http://127.0.0.1:{port}/health", timeout=0.2) as response:
                if response.status == 200:
                    return
        except URLError:
            time.sleep(0.1)
    raise RuntimeError("Libre Potato did not start.")


def test_client_round_trip(tmp_path: Path) -> None:
    files = tmp_path / "files"
    files.mkdir()
    (files / "readme.txt").write_text("hello from potato", encoding="utf-8")
    port = _free_port()
    env = os.environ.copy()
    env.update(
        {
            "LIBRE_POTATO_USERNAME": "dylan",
            "LIBRE_POTATO_PASSWORD_HASH": hash_password(PASSWORD),
            "LIBRE_POTATO_SECRET_KEY": "test-secret-key-must-be-32-characters-min",
            "LIBRE_POTATO_FILES_ROOT": str(files),
            "LIBRE_POTATO_HOST": "127.0.0.1",
            "LIBRE_POTATO_PORT": str(port),
            "LIBRE_POTATO_HTTPS_ONLY": "0",
        }
    )
    process = subprocess.Popen(
        [sys.executable, "-m", "app"],
        cwd=SERVER_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    try:
        _wait_until_ready(port, process)
        client = PotatoClient(f"http://127.0.0.1:{port}")
        client.login("dylan", PASSWORD)
        listing = client.list_files()
        assert [entry["name"] for entry in listing["entries"]] == ["readme.txt"]
        saved = client.download("readme.txt", tmp_path / "out")
        assert saved.read_text(encoding="utf-8") == "hello from potato"
        client.mkdir("", "Notes")
        note = tmp_path / "note.txt"
        note.write_text("from the client", encoding="utf-8")
        client.upload("Notes", note)
        nested = client.list_files("Notes")
        assert nested["parent"] == ""
        assert nested["entries"][0]["name"] == "note.txt"
        assert (files / "Notes" / "note.txt").read_text(encoding="utf-8") == "from the client"
    finally:
        process.terminate()
        process.wait(timeout=5)
