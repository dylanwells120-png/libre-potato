from pathlib import Path

import pytest

from app.paths import InvalidName, UnsafePath, safe_path, validate_entry_name


def test_rejects_parent_segments(tmp_path: Path) -> None:
    (tmp_path / "notes.txt").write_text("hello", encoding="utf-8")
    with pytest.raises(UnsafePath):
        safe_path(tmp_path, "../notes.txt")
    with pytest.raises(UnsafePath):
        safe_path(tmp_path, "folder/../../notes.txt")


def test_rejects_dotfiles_and_absolute_paths(tmp_path: Path) -> None:
    with pytest.raises(UnsafePath):
        safe_path(tmp_path, ".env")
    with pytest.raises(UnsafePath):
        safe_path(tmp_path, "docs/.secret")
    with pytest.raises(UnsafePath):
        safe_path(tmp_path, "/etc/passwd")


def test_rejects_symlink_that_leaves_the_folder(tmp_path: Path) -> None:
    root = tmp_path / "files"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    (root / "link.txt").symlink_to(outside)
    with pytest.raises(UnsafePath):
        safe_path(root, "link.txt")


def test_allows_a_normal_file(tmp_path: Path) -> None:
    target = tmp_path / "photo.jpg"
    target.write_bytes(b"123")
    assert safe_path(tmp_path, "photo.jpg") == target.resolve()


def test_entry_names() -> None:
    assert validate_entry_name("  notes.txt ") == "notes.txt"
    with pytest.raises(InvalidName):
        validate_entry_name("../x")
    with pytest.raises(InvalidName):
        validate_entry_name(".ssh")
    with pytest.raises(InvalidName):
        validate_entry_name("")
