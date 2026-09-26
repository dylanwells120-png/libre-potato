import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from potato_client.remote import PotatoClient, PotatoError, normalize_base


class Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        if self.path == "/api/login":
            data = json.loads(body.decode())
            if data.get("password") != "correct horse battery":
                self._json(401, {"error": "That username or password is wrong."})
                return
            self._json(200, {"token": "signed-token", "token_type": "bearer"})
            return
        if self.headers.get("Authorization") != "Bearer signed-token":
            self._json(401, {"error": "Sign in required."})
            return
        if self.path == "/mkdir":
            self._json(200, {"ok": True, "message": "Created Notes."})
            return
        if self.path == "/upload":
            self._json(200, {"ok": True, "message": "Saved note.txt."})
            return
        self._json(404, {"error": "missing"})

    def do_GET(self) -> None:
        if self.headers.get("Authorization") != "Bearer signed-token":
            self._json(401, {"error": "Sign in required."})
            return
        if self.path.startswith("/api/files"):
            self._json(
                200,
                {
                    "path": "",
                    "parent": "",
                    "entries": [{"name": "readme.txt", "kind": "file", "size": 5, "modified": "today"}],
                },
            )
            return
        if self.path == "/download/readme.txt":
            payload = b"hello"
            self.send_response(200)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        self._json(404, {"error": "That file is not in your folder."})

    def _json(self, status: int, payload: dict) -> None:
        raw = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, fmt: str, *args) -> None:
        return


@pytest.fixture()
def server() -> str:
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    host, port = httpd.server_address
    try:
        yield f"http://{host}:{port}"
    finally:
        httpd.shutdown()


def test_rejects_a_bare_hostname() -> None:
    with pytest.raises(PotatoError):
        normalize_base("potato")


def test_sign_in_list_download_and_upload(server: str, tmp_path: Path) -> None:
    client = PotatoClient(server)
    with pytest.raises(PotatoError):
        client.login("dylan", "wrong password!!")
    client.login("dylan", "correct horse battery")
    listing = client.list_files()
    assert listing["entries"][0]["name"] == "readme.txt"
    saved = client.download("readme.txt", tmp_path)
    assert saved.read_bytes() == b"hello"
    note = tmp_path / "note.txt"
    note.write_text("hi", encoding="utf-8")
    client.upload("", note)
    client.mkdir("", "Notes")


def test_missing_file_reports_the_server_message(server: str, tmp_path: Path) -> None:
    client = PotatoClient(server, token="signed-token")
    with pytest.raises(PotatoError, match="not in your folder"):
        client.download("missing.txt", tmp_path)
