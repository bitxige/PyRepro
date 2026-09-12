"""Shared pytest fixtures for RepoSentinel tests."""

from pathlib import Path

import pytest


@pytest.fixture
def fixture_repo(tmp_path: Path) -> Path:
    """Create a small repository fixture with source and test files."""
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "README.md").write_text("# Fixture\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='fixture'\n", encoding="utf-8"
    )
    (tmp_path / "src" / "mod.py").write_text(
        '"""Module docs."""\n\nclass Thing:\n    """Thing docs."""\n\n'
        "    def run(self, value):\n        return value\n\n\ndef helper(value):\n"
        "    return value\n",
        encoding="utf-8",
    )
    (tmp_path / "tests" / "test_mod.py").write_text(
        "from src.mod import helper\n\ndef test_helper():\n    assert helper(1) == 1\n",
        encoding="utf-8",
    )
    return tmp_path
