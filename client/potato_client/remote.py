"""Talk to a Libre Potato server with a saved sign-in token."""

from __future__ import annotations

import json
import secrets
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlparse
from urllib.request import Request, urlopen


class PotatoError(Exception):
    def __init__(self, message: str, status: int = 0) -> None:
        super().__init__(message)
        self.status = status


class PotatoClient:
    def __init__(self, base_url: str, token: str = "") -> None:
        self.base_url = normalize_base(base_url)
        self.token = token

    def login(self, username: str, password: str) -> str:
        payload = self._json(
            "POST",
            "/api/login",
            {"username": username, "password": password},
            auth=False,
        )
        token = payload.get("token")
        if not isinstance(token, str) or not token:
            raise PotatoError("The server did not return a sign-in token.")
        self.token = token
        return token

    def list_files(self, path: str = "") -> dict:
        query = urlencode({"path": path})
        payload = self._json("GET", f"/api/files?{query}")
        if not isinstance(payload.get("entries"), list):
            raise PotatoError("The server returned an unexpected folder listing.")
        return payload

    def download(self, remote_path: str, dest: Path) -> Path:
        target = dest / Path(remote_path).name if dest.is_dir() else dest
        target.parent.mkdir(parents=True, exist_ok=True)
        status, body, _headers = self._open("GET", file_path("download", remote_path))
        if status != 200:
            raise PotatoError(error_message(status, body), status)
        target.write_bytes(body)
        return target

    def upload(self, directory: str, file_path: Path) -> None:
        content = file_path.read_bytes()
        body, content_type = encode_multipart(
            {"directory": directory},
            "upload_file",
            file_path.name,
            content,
        )
        status, response, _headers = self._open(
            "POST",
            "/upload",
            body=body,
            content_type=content_type,
        )
        if status != 200:
            raise PotatoError(error_message(status, response), status)

    def mkdir(self, directory: str, name: str) -> None:
        encoded = urlencode({"directory": directory, "name": name}).encode("utf-8")
        status, response, _headers = self._open(
            "POST",
            "/mkdir",
            body=encoded,
            content_type="application/x-www-form-urlencoded",
        )
        if status != 200:
            raise PotatoError(error_message(status, response), status)

    def _json(self, method: str, path: str, payload: dict | None = None, *, auth: bool = True) -> dict:
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        content_type = None if payload is None else "application/json"
        status, raw, _headers = self._open(method, path, body=body, content_type=content_type, auth=auth)
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PotatoError(error_message(status, raw), status) from exc
        if status >= 400:
            message = data.get("error") if isinstance(data, dict) else None
            raise PotatoError(message if isinstance(message, str) else error_message(status, raw), status)
        if not isinstance(data, dict):
            raise PotatoError("The server returned an unexpected response.")
        return data

    def _open(
        self,
        method: str,
        path: str,
        *,
        body: bytes | None = None,
        content_type: str | None = None,
        auth: bool = True,
    ) -> tuple[int, bytes, dict]:
        request = Request(self.base_url + path, data=body, method=method)
        request.add_header("Accept", "application/json")
        request.add_header("User-Agent", "LibrePotatoClient")
        if content_type:
            request.add_header("Content-Type", content_type)
        if auth:
            if not self.token:
                raise PotatoError("Sign in first.")
            request.add_header("Authorization", f"Bearer {self.token}")
        try:
            with urlopen(request, timeout=60) as response:
                return response.status, response.read(), dict(response.headers)
        except HTTPError as exc:
            return exc.code, exc.read(), dict(exc.headers)
        except URLError as exc:
            raise PotatoError(f"Could not reach the server. {exc.reason}") from exc


def normalize_base(url: str) -> str:
    cleaned = url.strip().rstrip("/")
    parsed = urlparse(cleaned)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise PotatoError("Enter an address like http://100.x.x.x:8787 or your Tailscale HTTPS address.")
    return cleaned


def file_path(kind: str, remote_path: str) -> str:
    parts = [quote(part, safe="") for part in remote_path.split("/") if part not in {"", "."}]
    if any(part in {"..", "%2e%2e"} for part in remote_path.split("/")):
        raise PotatoError("That path is not in your folder.")
    return "/" + kind + ("/" + "/".join(parts) if parts else "")


def encode_multipart(fields: dict[str, str], file_field: str, filename: str, content: bytes) -> tuple[bytes, str]:
    if not filename or "/" in filename or "\\" in filename or '"' in filename:
        raise PotatoError("Use a plain file name.")
    boundary = "----LibrePotato" + secrets.token_hex(16)
    chunks: list[bytes] = []
    for key, value in fields.items():
        chunks.append(f"--{boundary}\r\n".encode())
        chunks.append(f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode())
        chunks.append(value.encode("utf-8"))
        chunks.append(b"\r\n")
    chunks.append(f"--{boundary}\r\n".encode())
    chunks.append(
        f'Content-Disposition: form-data; name="{file_field}"; filename="{filename}"\r\n'.encode()
    )
    chunks.append(b"Content-Type: application/octet-stream\r\n\r\n")
    chunks.append(content)
    chunks.append(b"\r\n")
    chunks.append(f"--{boundary}--\r\n".encode())
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def error_message(status: int, body: bytes) -> str:
    try:
        data = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        data = None
    if isinstance(data, dict) and isinstance(data.get("error"), str):
        return data["error"]
    return f"The server returned {status}."
