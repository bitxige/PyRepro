"""Tests for the restricted Codex reviewer runner."""

import json
import subprocess
import sys

import pytest
from reposentinel.agent import codex_reviewer
from reposentinel.agent.codex_reviewer import (
    DEFAULT_MODEL,
    DEFAULT_REASONING_EFFORT,
    CodexReviewer,
)
from reposentinel.agent.mcp_server import SERVER_NAME, TARGET_ROOT_ENV


def _event(item_type, **fields):
    return json.dumps({"type": "item.completed", "item": {"type": item_type, **fields}})


def _successful_trace():
    return "\n".join(
        (
            _event(
                "mcp_tool_call",
                server=SERVER_NAME,
                tool="get_project_summary",
            ),
            _event("agent_message", text="## Final review\n\nEvidence-backed finding."),
        )
    )


def test_reviewer_builds_a_restricted_luna_command(fixture_repo):
    """Keep Codex in a temporary cwd with only the required MCP server."""
    calls = []

    def fake_runner(command, **kwargs):
        """Record the configured subprocess call without running Codex."""
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, _successful_trace(), "")

    result = CodexReviewer(fixture_repo, process_runner=fake_runner).review()

    command, kwargs = calls[0]
    overrides = [
        command[index + 1]
        for index, value in enumerate(command[:-1])
        if value == "--config"
    ]
    assert result.tool_calls == ("get_project_summary",)
    assert "--json" in command
    assert "--ephemeral" in command
    assert "--ignore-user-config" in command
    assert "--ignore-rules" in command
    assert "--skip-git-repo-check" in command
    assert command[command.index("--model") + 1] == DEFAULT_MODEL
    assert kwargs["cwd"] != fixture_repo
    assert kwargs["cwd"] != CodexReviewer(fixture_repo).root
    assert kwargs["env"].get(TARGET_ROOT_ENV) is None
    assert f'model_reasoning_effort="{DEFAULT_REASONING_EFFORT}"' in overrides
    assert 'approval_policy="never"' in overrides
    assert 'sandbox_mode="read-only"' in overrides
    assert "features.shell_tool=false" in overrides
    assert 'web_search="disabled"' in overrides
    assert "agents.enabled=false" in overrides
    assert "features.apps=false" in overrides
    assert "features.plugins=false" in overrides
    assert f"mcp_servers.{SERVER_NAME}.required=true" in overrides
    assert (
        f'mcp_servers.{SERVER_NAME}.default_tools_approval_mode="writes"' in overrides
    )


def test_reviewer_requires_repository_evidence_before_final_response(fixture_repo):
    """Reject a final answer that does not include a RepoSentinel MCP call."""

    def fake_runner(command, **kwargs):
        return subprocess.CompletedProcess(
            command,
            0,
            _event("agent_message", text="Unsupported review."),
            "",
        )

    reviewer = CodexReviewer(fixture_repo, process_runner=fake_runner)

    with pytest.raises(RuntimeError, match="at least one RepoSentinel evidence tool"):
        reviewer.review()


def test_reviewer_counts_only_successful_completed_tool_calls(fixture_repo):
    """Do not treat a started or failed MCP call as repository evidence."""

    def fake_runner(command, **kwargs):
        trace = "\n".join(
            (
                json.dumps(
                    {
                        "type": "item.started",
                        "item": {
                            "type": "mcp_tool_call",
                            "server": SERVER_NAME,
                            "tool": "read_file",
                        },
                    }
                ),
                _event(
                    "mcp_tool_call",
                    server=SERVER_NAME,
                    tool="read_file",
                    error="unsafe path",
                ),
                _event(
                    "mcp_tool_call",
                    server=SERVER_NAME,
                    tool="get_project_summary",
                    error=None,
                ),
                _event("agent_message", text="Evidence-backed review."),
            )
        )
        return subprocess.CompletedProcess(command, 0, trace, "")

    result = CodexReviewer(fixture_repo, process_runner=fake_runner).review()

    assert result.tool_calls == ("get_project_summary",)


def test_reviewer_rejects_an_unexpected_mcp_tool(fixture_repo):
    """Do not accept evidence from a server or tool outside the allowlist."""

    def fake_runner(command, **kwargs):
        trace = "\n".join(
            (
                _event("mcp_tool_call", server="other", tool="read_file"),
                _event("agent_message", text="Unsupported review."),
            )
        )
        return subprocess.CompletedProcess(command, 0, trace, "")

    reviewer = CodexReviewer(fixture_repo, process_runner=fake_runner)

    with pytest.raises(RuntimeError, match="unexpected MCP server"):
        reviewer.review()


def test_reviewer_rejects_invalid_jsonl(fixture_repo):
    """Do not infer a review from malformed Codex event output."""

    def fake_runner(command, **kwargs):
        return subprocess.CompletedProcess(command, 0, "not json", "")

    reviewer = CodexReviewer(fixture_repo, process_runner=fake_runner)

    with pytest.raises(RuntimeError, match="invalid JSONL"):
        reviewer.review()


def test_reviewer_reports_subprocess_failures(fixture_repo):
    """Include Codex stderr when the restricted process fails."""

    def fake_runner(command, **kwargs):
        return subprocess.CompletedProcess(command, 1, "", "MCP startup failed")

    reviewer = CodexReviewer(fixture_repo, process_runner=fake_runner)

    with pytest.raises(RuntimeError, match="MCP startup failed"):
        reviewer.review()


def test_cli_rejects_outputs_inside_the_inspected_repository(fixture_repo, monkeypatch):
    """Keep final reviews and raw traces outside the inspected repository."""
    output = fixture_repo / "review.md"
    monkeypatch.setattr(
        sys,
        "argv",
        ["codex_reviewer", str(fixture_repo), "--trace-output", str(output)],
    )

    with pytest.raises(SystemExit) as error:
        codex_reviewer.main()

    assert error.value.code == 2
    assert not output.exists()
