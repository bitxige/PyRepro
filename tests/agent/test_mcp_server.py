"""Tests for the read-only RepoSentinel MCP server."""

import asyncio

import pytest
from mcp.server.fastmcp.exceptions import ToolError
from reposentinel.agent.mcp_server import (
    TARGET_ROOT_ENV,
    TOOL_NAMES,
    create_server,
    create_server_from_environment,
)
from reposentinel.tools.repository_tools import RepositoryTools


def test_server_exposes_only_read_only_repository_tools(fixture_repo):
    """Expose the existing RepositoryTools surface with read-only metadata."""
    server = create_server(RepositoryTools(fixture_repo))

    tools = asyncio.run(server.list_tools())

    assert tuple(tool.name for tool in tools) == TOOL_NAMES
    for tool in tools:
        assert tool.annotations.readOnlyHint is True
        assert tool.annotations.destructiveHint is False
        assert tool.annotations.openWorldHint is False


def test_server_delegates_to_existing_repository_tools(fixture_repo):
    """Return source evidence through the existing safe tool implementation."""
    server = create_server(RepositoryTools(fixture_repo))

    _, result = asyncio.run(server.call_tool("read_file", {"path": "src/mod.py"}))

    assert "class Thing" in result["result"]


def test_server_preserves_repository_path_boundary(fixture_repo):
    """Reject unsafe paths through the MCP wrapper as well."""
    server = create_server(RepositoryTools(fixture_repo))

    with pytest.raises(ToolError, match="escapes the repository root"):
        asyncio.run(server.call_tool("read_file", {"path": "../secret.txt"}))


def test_server_reads_its_target_only_from_the_runtime_environment(
    fixture_repo, monkeypatch
):
    """Bind the MCP process to the reviewer-selected target root."""
    monkeypatch.setenv(TARGET_ROOT_ENV, str(fixture_repo))

    server = create_server_from_environment()
    _, result = asyncio.run(server.call_tool("list_tree", {}))

    assert "src/mod.py" in result["result"]


def test_server_requires_a_runtime_target_root(monkeypatch):
    """Do not infer a target repository from the MCP server cwd."""
    monkeypatch.delenv(TARGET_ROOT_ENV, raising=False)

    with pytest.raises(RuntimeError, match=TARGET_ROOT_ENV):
        create_server_from_environment()
