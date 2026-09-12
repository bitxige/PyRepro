"""Tests for repository-root path validation."""

from pathlib import Path

import pytest
from reposentinel.path_utils import resolve_repository_file


def test_resolve_repository_file_allows_internal_file_and_symlink(tmp_path: Path):
    """Allow files and symlinks whose resolved targets stay inside the root."""
    root = tmp_path / "repo"
    root.mkdir()
    source = root / "source.txt"
    source.write_text("content", encoding="utf-8")
    link = root / "link.txt"
    link.symlink_to(source)

    resolved, relative = resolve_repository_file(root, "link.txt")

    assert resolved == source
    assert relative == "source.txt"


@pytest.mark.parametrize("path", ["../secret.txt", "/etc/passwd"])
def test_resolve_repository_file_rejects_escape_paths(tmp_path: Path, path: str):
    """Reject absolute paths and parent traversal."""
    root = tmp_path / "repo"
    root.mkdir()
    (tmp_path / "secret.txt").write_text("secret", encoding="utf-8")

    with pytest.raises(ValueError):
        resolve_repository_file(root, path)


def test_resolve_repository_file_rejects_external_symlink(tmp_path: Path):
    """Reject symlinks that resolve outside the repository root."""
    root = tmp_path / "repo"
    root.mkdir()
    secret = tmp_path / "secret.txt"
    secret.write_text("secret", encoding="utf-8")
    (root / "secret-link.txt").symlink_to(secret)

    with pytest.raises(ValueError, match="escapes"):
        resolve_repository_file(root, "secret-link.txt")


@pytest.mark.parametrize("path", ["missing.txt", "."])
def test_resolve_repository_file_rejects_missing_file_or_directory(
    tmp_path: Path, path: str
):
    """Reject missing paths and directories instead of regular files."""
    root = tmp_path / "repo"
    root.mkdir()

    with pytest.raises(FileNotFoundError):
        resolve_repository_file(root, path)


def test_resolve_repository_file_validates_root(tmp_path: Path):
    """Reject a repository root that is not an existing directory."""
    with pytest.raises(NotADirectoryError):
        resolve_repository_file(tmp_path / "missing-repo", "file.txt")
