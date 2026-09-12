"""Tests for safe read-only repository tools."""

import pytest
from reposentinel.tools.repository_tools import RepositoryTools


def test_tools_are_read_only_and_return_evidence(fixture_repo):
    """Expose repository facts and source evidence through the tool facade."""
    tools = RepositoryTools(fixture_repo)

    assert "src/mod.py" in tools.list_tree()
    assert "class Thing" in tools.read_file("src/mod.py")
    assert tools.search_code("assert")[0]["path"] == "tests/test_mod.py"
    assert len(tools.get_ast_summary("src/mod.py")["functions"]) == 2
    summary = tools.get_project_summary()
    assert summary["classes"] == 1
    assert summary["functions"] == 3
    assert "ast_summaries" not in summary
    assert "classes" not in tools.scanner.scan().to_dict()


def test_tools_reject_unsafe_reads(fixture_repo):
    """Reject unsafe file reads and empty search queries."""
    tools = RepositoryTools(fixture_repo)
    with pytest.raises(ValueError):
        tools.read_file("../secret.txt")
    with pytest.raises(ValueError):
        tools.search_code("")
