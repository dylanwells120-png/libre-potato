"""Keep every file operation inside the configured folder."""

from __future__ import annotations

import stat
from pathlib import Path


class UnsafePath(Exception):
    """The requested path is not a file inside the folder we serve."""


class InvalidName(Exception):
    """A new file or folder name the user typed is not allowed."""


def validate_entry_name(name: str) -> str:
    cleaned = name.strip()
    if (
        not cleaned
        or cleaned in {".", ".."}
        or cleaned.startswith(".")
        or len(cleaned) > 255
        or "/" in cleaned
        or "\\" in cleaned
        or "\x00" in cleaned
    ):
        raise InvalidName("Use a plain name without slashes or a leading dot.")
    return cleaned


def safe_path(root: Path, relative: str) -> Path:
    """Resolve `relative` and require it to stay inside `root`.

    Dotfiles are refused so a wide folder cannot expose `.ssh` or `.env`.
    Symlinks are followed, then rejected if they land outside `root`.
    """
    if not isinstance(relative, str) or len(relative) > 4096 or "\x00" in relative:
        raise UnsafePath()
    raw = relative.strip().replace("\\", "/")
    if raw.startswith("/"):
        raise UnsafePath()
    path = Path(raw)
    if path.is_absolute():
        raise UnsafePath()
    parts = path.parts
    for part in parts:
        if part in {".", ".."} or part.startswith("."):
            raise UnsafePath()
    root_resolved = root.resolve()
    candidate = root_resolved.joinpath(*parts).resolve() if parts else root_resolved
    try:
        candidate.relative_to(root_resolved)
    except ValueError as exc:
        raise UnsafePath() from exc
    return candidate


def is_regular_file(path: Path) -> bool:
    try:
        mode = path.stat().st_mode
    except OSError:
        return False
    return stat.S_ISREG(mode)


def is_directory(path: Path) -> bool:
    try:
        mode = path.stat().st_mode
    except OSError:
        return False
    return stat.S_ISDIR(mode)
