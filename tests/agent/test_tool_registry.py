"""Tests for the read-only Agent tool registry."""

import pytest
from reposentinel.agent.tool_registry import build_tool_schemas, execute_tool
from reposentinel.tools.repository_tools import RepositoryTools


def test_build_tool_schemas_selects_requested_tools():
    """Return schemas only for explicitly selected tools."""
    schemas = build_tool_schemas(("get_project_summary", "read_file"))

    assert [item["function"]["name"] for item in schemas] == [
        "get_project_summary",
        "read_file",
    ]


def test_build_tool_schemas_rejects_unknown_tool():
    """Reject schemas that would expose an unsupported operation."""
    with pytest.raises(ValueError, match="Unsupported"):
        build_tool_schemas(("run_shell",))


def test_execute_tool_uses_existing_repository_tools(fixture_repo):
    """Delegate supported calls to the existing read-only tool surface."""
    repository_tools = RepositoryTools(fixture_repo)

    summary = execute_tool(repository_tools, "get_project_summary", {})
    source = execute_tool(repository_tools, "read_file", {"path": "src/mod.py"})

    assert summary["functions"] == 3
    assert "class Thing" in source


@pytest.mark.parametrize(
    ("tool_name", "arguments"),
    [
        ("get_project_summary", {"unexpected": "value"}),
        ("read_file", {}),
        ("search_code", {"keyword": "", "extra": "value"}),
        ("unknown_tool", {}),
    ],
)
def test_execute_tool_rejects_invalid_model_arguments(
    fixture_repo, tool_name, arguments
):
    """Validate model arguments before calling repository operations."""
    with pytest.raises(ValueError):
        execute_tool(RepositoryTools(fixture_repo), tool_name, arguments)
