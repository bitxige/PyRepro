"""Tests for repository file inventory and metadata detection."""

import pytest
from reposentinel.scanner.repository_scanner import RepositoryScanner


def test_scanner_builds_profile(fixture_repo):
    """Build a file-level profile without AST-derived totals."""
    profile = RepositoryScanner(fixture_repo).scan()

    assert profile.python_files == 2
    assert profile.test_files == 1
    assert "classes" not in profile.to_dict()
    assert "functions" not in profile.to_dict()
    assert profile.has_readme is True
    assert profile.has_pyproject is True
    assert profile.has_github_actions is False
    assert "src/mod.py" in profile.python_paths


def test_scanner_skips_generated_directories(fixture_repo):
    """Skip generated cache directories from the file inventory."""
    cache = fixture_repo / "__pycache__"
    cache.mkdir()
    (cache / "ignored.pyc").write_bytes(b"not source")

    assert "__pycache__/ignored.pyc" not in RepositoryScanner(fixture_repo).list_files()


def test_scanner_handles_internal_and_external_symlinks(fixture_repo):
    """Include internal symlinks and exclude symlinks leaving the root."""
    inside = fixture_repo / "inside.py"
    inside.write_text("value = 1\n", encoding="utf-8")
    (fixture_repo / "inside-link.py").symlink_to(inside)
    outside = fixture_repo.parent / "outside.py"
    outside.write_text("value = 2\n", encoding="utf-8")
    (fixture_repo / "outside-link.py").symlink_to(outside)

    files = RepositoryScanner(fixture_repo).list_files()

    assert "inside-link.py" in files
    assert "outside-link.py" not in files


@pytest.mark.parametrize(
    ("relative_path", "is_test_file"),
    [("test_extra.py", True), ("foo_test.py", True), ("tests/helpers.py", False)],
)
def test_scanner_uses_pytest_filename_patterns(
    fixture_repo, relative_path, is_test_file
):
    """Recognize pytest filename patterns without using the directory name."""
    path = fixture_repo / relative_path
    path.write_text("value = 1\n", encoding="utf-8")

    profile = RepositoryScanner(fixture_repo).scan()

    assert (relative_path in profile.test_paths) is is_test_file
