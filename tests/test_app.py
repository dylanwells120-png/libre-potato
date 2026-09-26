import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.passwords import hash_password, verify_password

PASSWORD = "correct horse battery"


@pytest.fixture(scope="module")
def password_hash() -> str:
    return hash_password(PASSWORD)


def make_client(root: Path, password_hash: str) -> TestClient:
    settings = Settings(
        username="dylan",
        password_hash=password_hash,
        secret_key="test-secret-key-must-be-32-characters-min",
        files_root=root,
        host="127.0.0.1",
        port=8787,
        https_only=False,
        max_upload_bytes=1024,
    )
    return TestClient(create_app(settings))


def csrf_from(html: str) -> str:
    match = re.search(r'name="csrf" value="([^"]+)"', html)
    assert match is not None
    return match.group(1)


def sign_in(client: TestClient) -> None:
    page = client.get("/login")
    response = client.post(
        "/login",
        data={"username": "dylan", "password": PASSWORD, "csrf": csrf_from(page.text)},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/files"


def test_password_roundtrip(password_hash: str) -> None:
    assert verify_password(PASSWORD, password_hash)
    assert not verify_password("wrong password!!", password_hash)


def test_login_and_listing(tmp_path: Path, password_hash: str) -> None:
    (tmp_path / "notes.txt").write_text("hello from potato", encoding="utf-8")
    (tmp_path / ".hidden").write_text("nope", encoding="utf-8")
    with make_client(tmp_path, password_hash) as client:
        hidden = client.get("/files", follow_redirects=False)
        assert hidden.status_code == 303
        assert hidden.headers["location"] == "/login"

        bad = client.get("/login")
        wrong = client.post(
            "/login",
            data={"username": "dylan", "password": "not the password", "csrf": csrf_from(bad.text)},
        )
        assert wrong.status_code == 401
        assert "wrong" in wrong.text

        sign_in(client)
        page = client.get("/files")
        assert "notes.txt" in page.text
        assert ".hidden" not in page.text

        preview = client.get("/view/notes.txt")
        assert "hello from potato" in preview.text
        download = client.get("/download/notes.txt")
        assert download.content == b"hello from potato"
        assert "attachment" in download.headers["content-disposition"]


def test_blocks_escape_and_html(tmp_path: Path, password_hash: str) -> None:
    root = tmp_path / "files"
    root.mkdir()
    outside = tmp_path / "secret.txt"
    outside.write_text("outside", encoding="utf-8")
    (root / "link.txt").symlink_to(outside)
    (root / "page.html").write_text("<script>alert(1)</script>", encoding="utf-8")
    with make_client(root, password_hash) as client:
        sign_in(client)
        assert client.get("/download/../secret.txt").status_code == 404
        assert client.get("/download/link.txt").status_code == 404
        assert client.get("/download/.hidden").status_code == 404
        raw = client.get("/raw/page.html")
        assert raw.status_code == 404
        assert "text/html" not in raw.headers.get("content-type", "") or "Not available" in raw.text
        saved = client.get("/download/page.html")
        assert saved.status_code == 200
        assert "attachment" in saved.headers["content-disposition"]


def test_upload_and_mkdir(tmp_path: Path, password_hash: str) -> None:
    with make_client(tmp_path, password_hash) as client:
        sign_in(client)
        page = client.get("/files")
        token = csrf_from(page.text)
        created = client.post(
            "/mkdir",
            data={"directory": "", "name": "Photos", "csrf": token},
            follow_redirects=False,
        )
        assert created.status_code == 303
        assert (tmp_path / "Photos").is_dir()

        page = client.get("/files")
        uploaded = client.post(
            "/upload",
            data={"directory": "", "csrf": csrf_from(page.text)},
            files={"upload_file": ("trip.txt", b"on the road", "text/plain")},
            follow_redirects=True,
        )
        assert uploaded.status_code == 200
        assert (tmp_path / "trip.txt").read_text(encoding="utf-8") == "on the road"
        assert "Saved trip.txt" in uploaded.text

        page = client.get("/files")
        rejected = client.post(
            "/upload",
            data={"directory": "", "csrf": csrf_from(page.text)},
            files={"upload_file": ("../escape.txt", b"nope", "text/plain")},
            follow_redirects=True,
        )
        assert rejected.status_code == 200
        assert not (tmp_path.parent / "escape.txt").exists()
        assert not (tmp_path / "escape.txt").exists()


def test_upload_over_the_limit_removes_the_partial_file(tmp_path: Path, password_hash: str) -> None:
    with make_client(tmp_path, password_hash) as client:
        sign_in(client)
        page = client.get("/files")
        response = client.post(
            "/upload",
            data={"directory": "", "csrf": csrf_from(page.text)},
            files={"upload_file": ("big.bin", b"x" * 2048, "application/octet-stream")},
            follow_redirects=True,
        )
        assert response.status_code == 200
        assert "larger than the upload limit" in response.text
        assert not (tmp_path / "big.bin").exists()


def test_settings_refuse_the_filesystem_root(password_hash: str) -> None:
    with pytest.raises(ValueError):
        Settings(
            username="dylan",
            password_hash=password_hash,
            secret_key="test-secret-key-must-be-32-characters-min",
            files_root=Path("/"),
            host="127.0.0.1",
            port=8787,
            https_only=False,
            max_upload_bytes=1024,
        )
