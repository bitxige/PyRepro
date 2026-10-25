"""Tests for the bounded complete-if-statement reduction prototype."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from pyrepro.reproducer.failure import ReductionOutcome
from pyrepro.reproducer.if_statement_reducer import (
    GreedyIfStatementReducer,
    IfStatementOrder,
    _remove_if_statement,
    discover_if_statements,
)
from pyrepro.reproducer.reducer import GreedyFileReducer
from pyrepro.reproducer.runner import CommandRunner
from pyrepro.reproducer.workspace import ReductionWorkspace, tree_digest


def test_discovery_handles_if_chains_but_not_elif_source_nodes(tmp_path: Path):
    """One outer if covers its elif/else chain; comments and nested defs skip."""
    source = tmp_path / "module.py"
    source.write_text(
        """def build(value: int) -> int:
    if value == 1:
        return 1
    elif value == 2:
        return 2
    else:
        return 3
    if value:
        if value > 3:
            return 4
    if value:  # preserve this comment
        return 5
    def nested() -> None:
        if value:
            return None
    return 0
""",
        encoding="utf-8",
    )

    discovery = discover_if_statements(source, tmp_path)

    assert not discovery.skipped
    assert [(item.start_line, item.end_line) for item in discovery.candidates] == [
        (2, 7),
        (8, 10),
        (9, 10),
    ]
    assert discovery.candidates[0].control_path == ("if@2",)
    assert all(
        "elif" not in "/".join(item.control_path) for item in discovery.candidates
    )


def test_if_statement_mutation_preserves_crlf_and_inserts_pass_if_needed(
    tmp_path: Path,
):
    """A sole if statement is replaced with pass without normalizing CRLF bytes."""
    source = tmp_path / "module.py"
    source.write_bytes(
        (
            "def build(value: int) -> int:\r\n"
            "    if value:\r\n"
            '        label = "中文"\r\n'
            "        return len(label)\r\n"
        ).encode()
    )
    candidate = discover_if_statements(source, tmp_path).candidates[0]
    assert candidate.requires_pass

    _remove_if_statement(source, candidate)

    data = source.read_bytes()
    assert b"if value" not in data
    assert b"    pass\r\n" in data
    assert b"\r\n" in data
    assert b"\n" not in data.replace(b"\r\n", b"")
    ast.parse(data.decode("utf-8"))


def test_if_statement_reducer_records_acceptance_and_rejection(tmp_path: Path):
    """Accepted deletion changes only the workspace; rejected probe rolls back."""
    project = tmp_path / "project"
    project.mkdir()
    (project / "module.py").write_text(
        """def required() -> int:
    if True:
        required_value = 1
    if True:
        unused_value = 2
    return required_value
""",
        encoding="utf-8",
    )
    (project / "reproduce.py").write_text(
        """from module import required

required()
raise ValueError("if statement reduction failure")
""",
        encoding="utf-8",
    )
    source_digest = tree_digest(project)
    runner = CommandRunner((sys.executable, "reproduce.py"), timeout_seconds=2)

    with ReductionWorkspace(project) as workspace:
        file_result = GreedyFileReducer(runner).reduce(workspace)
        result = GreedyIfStatementReducer(
            runner, max_probes=2, candidate_order=IfStatementOrder.DISCOVERY
        ).reduce(workspace, file_result.baseline_signature)
        content = (workspace.root / "module.py").read_text(encoding="utf-8")

    assert result.candidate_attempts == 2
    assert result.accepted_removals == 1
    assert result.rejected_probes == 1
    assert not result.probe_records[0].accepted
    assert result.probe_records[0].candidate_rolled_back
    assert result.probe_records[0].outcome is ReductionOutcome.DIFFERENT_FAILURE
    assert result.probe_records[1].accepted
    assert "required_value = 1" in content
    assert "unused_value = 2" not in content
    assert ast.parse(content)
    assert result.source_unchanged
    assert tree_digest(project) == source_digest


def test_if_statement_reducer_rediscovery_skips_inner_candidate_after_outer_removal(
    tmp_path: Path,
):
    """An accepted outer deletion makes its nested candidate unavailable."""
    project = tmp_path / "project"
    project.mkdir()
    (project / "module.py").write_text(
        """def required() -> None:
    if True:
        if True:
            ballast = 2
    raise ValueError(\"if statement reduction failure\")
""",
        encoding="utf-8",
    )
    (project / "reproduce.py").write_text(
        """from module import required

required()
""",
        encoding="utf-8",
    )
    runner = CommandRunner((sys.executable, "reproduce.py"), timeout_seconds=2)

    with ReductionWorkspace(project) as workspace:
        file_result = GreedyFileReducer(runner).reduce(workspace)
        result = GreedyIfStatementReducer(
            runner, max_probes=2, candidate_order=IfStatementOrder.SPAN_DESC
        ).reduce(workspace, file_result.baseline_signature)

    assert result.initial_candidates == 2
    assert result.candidate_attempts == 1
    assert result.accepted_removals == 1
    assert result.remaining_candidates == 0
