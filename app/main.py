"""Web UI for browsing one folder."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from app.config import Settings
from app.passwords import equal_text, verify_password
from app.paths import InvalidName, UnsafePath, is_directory, is_regular_file, safe_path, validate_entry_name

PACKAGE_DIR = Path(__file__).resolve().parent
TEXT_EXTENSIONS = {".txt", ".md", ".json", ".csv", ".log", ".py", ".toml", ".yaml", ".yml", ".css", ".js"}
INLINE_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".pdf": "application/pdf",
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".wav": "audio/wav",
    ".mp4": "video/mp4",
    ".webm": "video/webm",
}
PREVIEW_LIMIT = 200_000
LOCK_AFTER = 8
LOCK_SECONDS = 15 * 60


class NotAuthenticated(Exception):
    pass


@dataclass
class Attempt:
    failures: int = 0
    locked_until: float = 0


@dataclass
class Lockout:
    attempts: dict[str, Attempt] = field(default_factory=dict)

    def locked(self, key: str, now: float) -> bool:
        attempt = self.attempts.get(key)
        return bool(attempt and attempt.locked_until > now)

    def record_failure(self, key: str, now: float) -> None:
        if len(self.attempts) > 1024:
            self.attempts.clear()
        attempt = self.attempts.setdefault(key, Attempt())
        if attempt.locked_until and now >= attempt.locked_until:
            attempt.failures = 0
            attempt.locked_until = 0
        attempt.failures += 1
        if attempt.failures >= LOCK_AFTER:
            attempt.locked_until = now + LOCK_SECONDS

    def clear(self, key: str) -> None:
        self.attempts.pop(key, None)


def create_app(settings: Settings) -> FastAPI:
    app = FastAPI(title="Libre Potato", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.settings = settings
    app.state.lockout = Lockout()
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.secret_key,
        session_cookie="libre_potato",
        max_age=60 * 60 * 24 * 14,
        same_site="lax",
        https_only=settings.https_only,
    )
    templates = Jinja2Templates(directory=PACKAGE_DIR / "templates")
    app.mount("/static", StaticFiles(directory=PACKAGE_DIR / "static"), name="static")

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["X-Robots-Tag"] = "noindex, nofollow"
        path = request.url.path
        if path.startswith("/raw"):
            response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'self'"
        else:
            response.headers["X-Frame-Options"] = "DENY"
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; img-src 'self'; media-src 'self'; "
                "style-src 'self'; frame-src 'self'; frame-ancestors 'none'; "
                "base-uri 'none'; form-action 'self'"
            )
        if not path.startswith("/static"):
            response.headers["Cache-Control"] = "no-store"
        return response

    token_max_age = 60 * 60 * 24 * 30

    def token_serializer() -> URLSafeTimedSerializer:
        return URLSafeTimedSerializer(settings.secret_key, salt="libre-potato-token")

    def issue_token() -> str:
        return token_serializer().dumps({"u": settings.username})

    def read_bearer(request: Request) -> str | None:
        header = request.headers.get("authorization", "")
        if len(header) < 8 or header[:7].lower() != "bearer ":
            return None
        try:
            data = token_serializer().loads(header[7:].strip(), max_age=token_max_age)
        except (BadSignature, SignatureExpired):
            return None
        if not isinstance(data, dict) or data.get("u") != settings.username:
            return None
        return settings.username

    def signed_in(request: Request) -> bool:
        return request.session.get("user") == settings.username or read_bearer(request) == settings.username

    def wants_json(request: Request) -> bool:
        header = request.headers.get("authorization", "")
        return request.url.path.startswith("/api/") or header.lower().startswith("bearer ")

    @app.exception_handler(NotAuthenticated)
    async def redirect_to_login(request: Request, _exc: NotAuthenticated) -> Response:
        if wants_json(request):
            return JSONResponse({"error": "Sign in required."}, status_code=401)
        return RedirectResponse("/login", status_code=303)

    def require_login(request: Request) -> None:
        if not signed_in(request):
            raise NotAuthenticated()

    def ensure_csrf(request: Request) -> str:
        token = request.session.get("csrf")
        if not isinstance(token, str) or not token:
            token = secrets.token_urlsafe(32)
            request.session["csrf"] = token
        return token

    def csrf_ok(request: Request, token: str) -> bool:
        expected = request.session.get("csrf")
        if not isinstance(expected, str) or not expected or not isinstance(token, str) or not token:
            return False
        return hmac.compare_digest(
            hashlib.sha256(token.encode("utf-8")).digest(),
            hashlib.sha256(expected.encode("utf-8")).digest(),
        )

    def client_key(request: Request) -> str:
        if request.client is None:
            return "unknown"
        return request.client.host

    def flash(request: Request, message: str, kind: str = "ok") -> None:
        request.session["flash"] = {"message": message, "kind": kind}

    def pop_flash(request: Request) -> dict | None:
        flashed = request.session.pop("flash", None)
        if isinstance(flashed, dict) and isinstance(flashed.get("message"), str):
            return flashed
        return None

    def relative_from(path: Path) -> str:
        try:
            rel = path.resolve().relative_to(settings.files_root)
        except ValueError:
            return ""
        return rel.as_posix()

    def url_for(*parts: str, view: str = "files") -> str:
        if not parts:
            return "/files" if view == "files" else f"/{view}"
        encoded = "/".join(quote(part, safe="") for part in parts)
        return f"/{view}/{encoded}"

    @app.get("/health")
    async def health() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/robots.txt")
    async def robots_txt() -> Response:
        return Response("User-agent: *\nDisallow: /\n", media_type="text/plain")

    @app.get("/")
    async def root(request: Request) -> RedirectResponse:
        if request.session.get("user") == settings.username:
            return RedirectResponse("/files", status_code=303)
        return RedirectResponse("/login", status_code=303)

    @app.get("/login", response_class=HTMLResponse)
    async def login_page(request: Request, error: str = "") -> HTMLResponse:
        if request.session.get("user") == settings.username:
            return RedirectResponse("/files", status_code=303)
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": error, "csrf": ensure_csrf(request)},
        )

    @app.post("/login")
    async def login(request: Request, username: str = Form(""), password: str = Form(""), csrf: str = Form("")):
        if not csrf_ok(request, csrf):
            return templates.TemplateResponse(
                request,
                "login.html",
                {"error": "That form expired. Try again.", "csrf": ensure_csrf(request)},
                status_code=400,
            )
        key = client_key(request)
        if app.state.lockout.locked(key, time.time()):
            return templates.TemplateResponse(
                request,
                "login.html",
                {
                    "error": "Too many tries. Wait a few minutes, then try again.",
                    "csrf": ensure_csrf(request),
                },
                status_code=429,
            )
        password_ok = await asyncio.to_thread(verify_password, password, settings.password_hash)
        if not (password_ok and equal_text(username, settings.username)):
            app.state.lockout.record_failure(key, time.time())
            return templates.TemplateResponse(
                request,
                "login.html",
                {"error": "That username or password is wrong.", "csrf": ensure_csrf(request)},
                status_code=401,
            )
        app.state.lockout.clear(key)
        request.session.clear()
        request.session["user"] = settings.username
        request.session["csrf"] = secrets.token_urlsafe(32)
        return RedirectResponse("/files", status_code=303)

    @app.post("/logout")
    async def logout(request: Request, csrf: str = Form("")):
        require_login(request)
        if not csrf_ok(request, csrf):
            return RedirectResponse("/files", status_code=303)
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    @app.get("/files", response_class=HTMLResponse)
    async def files_root(request: Request) -> HTMLResponse:
        return await browse(request, "")

    @app.get("/files/{file_path:path}", response_class=HTMLResponse)
    async def files_path(request: Request, file_path: str) -> HTMLResponse:
        return await browse(request, file_path)

    async def browse(request: Request, file_path: str) -> HTMLResponse:
        require_login(request)
        try:
            target = safe_path(settings.files_root, file_path)
        except UnsafePath:
            return missing(request, "That path is not in your folder.")
        if is_regular_file(target):
            return RedirectResponse(url_for(*Path(relative_from(target)).parts, view="view"), status_code=303)
        if not is_directory(target):
            return missing(request, "That folder is not available.")
        try:
            entries = await asyncio.to_thread(list_entries, target)
        except OSError:
            return missing(request, "That folder could not be read.")
        rel = relative_from(target)
        parts = Path(rel).parts if rel else ()
        return templates.TemplateResponse(
            request,
            "browse.html",
            {
                "entries": entries,
                "breadcrumbs": breadcrumbs(parts),
                "csrf": ensure_csrf(request),
                "directory": rel,
                "flash": pop_flash(request),
                "parent_url": url_for(*parts[:-1]) if parts else "",
            },
        )

    def list_entries(directory: Path) -> list[dict]:
        rows = []
        for child in directory.iterdir():
            if child.name.startswith("."):
                continue
            try:
                rel_parts = Path(relative_from(child)).parts
                if is_directory(child):
                    rows.append(
                        {
                            "name": child.name,
                            "kind": "Folder",
                            "size": "",
                            "modified": modified(child),
                            "open_url": url_for(*rel_parts),
                            "download_url": "",
                        }
                    )
                elif is_regular_file(child):
                    rows.append(
                        {
                            "name": child.name,
                            "kind": "File",
                            "size": format_size(child.stat().st_size),
                            "modified": modified(child),
                            "open_url": url_for(*rel_parts, view="view"),
                            "download_url": url_for(*rel_parts, view="download"),
                        }
                    )
            except OSError:
                continue
        rows.sort(key=lambda row: (row["kind"] != "Folder", row["name"].casefold()))
        return rows

    def breadcrumbs(parts: tuple[str, ...] | list[str]) -> list[dict]:
        crumbs = [{"name": "Files", "url": "/files", "current": not parts}]
        acc: list[str] = []
        for index, part in enumerate(parts):
            acc.append(part)
            crumbs.append(
                {
                    "name": part,
                    "url": url_for(*acc),
                    "current": index == len(parts) - 1,
                }
            )
        return crumbs

    def missing(request: Request, message: str) -> HTMLResponse:
        return templates.TemplateResponse(
            request,
            "missing.html",
            {"message": message},
            status_code=404,
        )

    @app.get("/view/{file_path:path}", response_class=HTMLResponse)
    async def view_file(request: Request, file_path: str) -> HTMLResponse:
        require_login(request)
        try:
            target = safe_path(settings.files_root, file_path)
        except UnsafePath:
            return missing(request, "That file is not in your folder.")
        if not is_regular_file(target):
            return missing(request, "That file is not available.")
        rel_parts = Path(relative_from(target)).parts
        suffix = target.suffix.casefold()
        size = target.stat().st_size
        preview = ""
        too_big = suffix in TEXT_EXTENSIONS and size > PREVIEW_LIMIT
        if suffix in TEXT_EXTENSIONS and not too_big:
            preview = await asyncio.to_thread(read_preview, target)
        return templates.TemplateResponse(
            request,
            "view.html",
            {
                "name": target.name,
                "size": format_size(size),
                "modified": modified(target),
                "breadcrumbs": breadcrumbs(rel_parts),
                "download_url": url_for(*rel_parts, view="download"),
                "raw_url": url_for(*rel_parts, view="raw") if suffix in INLINE_TYPES else "",
                "kind": preview_kind(suffix),
                "preview": preview,
                "too_big": too_big,
                "folder_url": url_for(*rel_parts[:-1]),
            },
        )

    @app.get("/download/{file_path:path}")
    async def download_file(request: Request, file_path: str):
        require_login(request)
        target = open_file(file_path)
        return FileResponse(
            target,
            filename=target.name,
            content_disposition_type="attachment",
        )

    @app.get("/raw/{file_path:path}")
    async def raw_file(request: Request, file_path: str):
        require_login(request)
        target = open_file(file_path)
        media_type = INLINE_TYPES.get(target.suffix.casefold())
        if media_type is None:
            return missing(request, "Open this file with download instead.")
        return FileResponse(target, media_type=media_type, content_disposition_type="inline", filename=target.name)

    def open_file(file_path: str) -> Path:
        try:
            target = safe_path(settings.files_root, file_path)
        except UnsafePath as exc:
            raise _NotFound() from exc
        if not is_regular_file(target):
            raise _NotFound()
        return target

    @app.exception_handler(_NotFound)
    async def render_not_found(request: Request, _exc: _NotFound) -> Response:
        if not signed_in(request):
            if wants_json(request):
                return JSONResponse({"error": "Sign in required."}, status_code=401)
            return RedirectResponse("/login", status_code=303)
        if wants_json(request):
            return JSONResponse({"error": "That file is not in your folder."}, status_code=404)
        return missing(request, "That file is not in your folder.")

    @app.post("/upload")
    async def upload(
        request: Request,
        directory: str = Form(""),
        csrf: str = Form(""),
        upload_file: UploadFile = File(...),
    ):
        require_login(request)
        token_auth = read_bearer(request) == settings.username
        if not token_auth and not csrf_ok(request, csrf):
            return reject(request, directory, "That form expired. Reload and try again.", 400)
        try:
            folder = safe_path(settings.files_root, directory)
            filename = validate_entry_name(upload_file.filename or "")
        except (UnsafePath, InvalidName):
            return reject(request, directory, "Choose a plain file name inside your folder.", 400)
        if not is_directory(folder):
            return reject(request, directory, "That folder is not available.", 404)
        destination = folder / filename
        if destination.exists():
            return reject(
                request,
                directory,
                f"{filename} is already there. Rename it on this device and upload again.",
                409,
            )
        try:
            await save_upload(upload_file, destination, settings.max_upload_bytes)
        except UploadTooLarge:
            return reject(request, directory, "That file is larger than the upload limit.", 413)
        except OSError:
            return reject(request, directory, "The file could not be saved.", 500)
        return accept(request, directory, f"Saved {filename}.")

    @app.post("/mkdir")
    async def make_directory(request: Request, directory: str = Form(""), name: str = Form(""), csrf: str = Form("")):
        require_login(request)
        token_auth = read_bearer(request) == settings.username
        if not token_auth and not csrf_ok(request, csrf):
            return reject(request, directory, "That form expired. Reload and try again.", 400)
        try:
            folder = safe_path(settings.files_root, directory)
            folder_name = validate_entry_name(name)
        except (UnsafePath, InvalidName):
            return reject(request, directory, "Use a plain folder name.", 400)
        if not is_directory(folder):
            return reject(request, directory, "That folder is not available.", 404)
        destination = folder / folder_name
        try:
            destination.mkdir(exist_ok=False)
        except FileExistsError:
            return reject(request, directory, "That folder already exists.", 409)
        except OSError:
            return reject(request, directory, "The folder could not be created.", 500)
        return accept(request, directory, f"Created {folder_name}.")

    def reject(request: Request, directory: str, message: str, status: int) -> Response:
        if read_bearer(request):
            return JSONResponse({"error": message}, status_code=status)
        flash(request, message, "error")
        return RedirectResponse(back_to(directory), status_code=303)

    def accept(request: Request, directory: str, message: str) -> Response:
        if read_bearer(request):
            return JSONResponse({"ok": True, "message": message})
        flash(request, message, "ok")
        return RedirectResponse(back_to(directory), status_code=303)

    def back_to(directory: str) -> str:
        try:
            folder = safe_path(settings.files_root, directory)
        except UnsafePath:
            return "/files"
        rel = relative_from(folder)
        return url_for(*Path(rel).parts) if rel else "/files"

    def api_entries(directory: Path) -> list[dict]:
        rows = []
        for child in directory.iterdir():
            if child.name.startswith("."):
                continue
            try:
                if is_directory(child):
                    rows.append(
                        {"name": child.name, "kind": "folder", "size": None, "modified": modified(child)}
                    )
                elif is_regular_file(child):
                    rows.append(
                        {
                            "name": child.name,
                            "kind": "file",
                            "size": child.stat().st_size,
                            "modified": modified(child),
                        }
                    )
            except OSError:
                continue
        rows.sort(key=lambda row: (row["kind"] != "folder", row["name"].casefold()))
        return rows

    @app.post("/api/login")
    async def api_login(request: Request) -> JSONResponse:
        try:
            body = await request.json()
        except Exception:
            body = None
        username = body.get("username") if isinstance(body, dict) else None
        password = body.get("password") if isinstance(body, dict) else None
        if not isinstance(username, str) or not isinstance(password, str):
            return JSONResponse({"error": "Send a username and password."}, status_code=400)
        key = client_key(request)
        if app.state.lockout.locked(key, time.time()):
            return JSONResponse(
                {"error": "Too many tries. Wait a few minutes, then try again."},
                status_code=429,
            )
        password_ok = await asyncio.to_thread(verify_password, password, settings.password_hash)
        if not (password_ok and equal_text(username, settings.username)):
            app.state.lockout.record_failure(key, time.time())
            return JSONResponse({"error": "That username or password is wrong."}, status_code=401)
        app.state.lockout.clear(key)
        return JSONResponse(
            {"token": issue_token(), "token_type": "bearer", "expires_in": token_max_age}
        )

    @app.get("/api/files")
    async def api_files(request: Request, path: str = "") -> JSONResponse:
        require_login(request)
        try:
            target = safe_path(settings.files_root, path)
        except UnsafePath:
            return JSONResponse({"error": "That path is not in your folder."}, status_code=404)
        if not is_directory(target):
            return JSONResponse({"error": "That folder is not available."}, status_code=404)
        try:
            entries = await asyncio.to_thread(api_entries, target)
        except OSError:
            return JSONResponse({"error": "That folder could not be read."}, status_code=404)
        rel = relative_from(target)
        parent = ""
        if rel:
            parent_path = Path(rel).parent.as_posix()
            parent = "" if parent_path == "." else parent_path
        return JSONResponse({"path": rel, "parent": parent, "entries": entries})

    return app


class _NotFound(Exception):
    pass


class UploadTooLarge(Exception):
    pass


async def save_upload(upload: UploadFile, destination: Path, limit: int) -> None:
    written = 0
    created = False
    try:
        handle = destination.open("xb")
        created = True
        with handle:
            while True:
                chunk = await upload.read(1024 * 1024)
                if not chunk:
                    break
                written += len(chunk)
                if written > limit:
                    raise UploadTooLarge()
                handle.write(chunk)
    except Exception:
        if created:
            destination.unlink(missing_ok=True)
        raise
    finally:
        await upload.close()


def read_preview(path: Path) -> str:
    data = path.read_bytes()[:PREVIEW_LIMIT]
    return data.decode("utf-8", errors="replace")


def preview_kind(suffix: str) -> str:
    if suffix in {".png", ".jpg", ".jpeg", ".gif", ".webp"}:
        return "image"
    if suffix == ".pdf":
        return "pdf"
    if suffix in {".mp3", ".m4a", ".wav"}:
        return "audio"
    if suffix in {".mp4", ".webm"}:
        return "video"
    if suffix in TEXT_EXTENSIONS:
        return "text"
    return "file"


def modified(path: Path) -> str:
    try:
        stamp = path.stat().st_mtime
    except OSError:
        return ""
    return datetime.fromtimestamp(stamp).strftime("%Y-%m-%d %H:%M")


def format_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            if unit == "B":
                return f"{int(value)} B"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} B"

