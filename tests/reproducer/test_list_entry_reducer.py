"""Tests for conservative module-list entry reduction."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from pyrepro.reproducer.budget import ExecutionBudget
from pyrepro.reproducer.list_entry_reducer import (
    GreedyListEntryReducer,
    _remove_entries,
    discover_list_entries,
)
from pyrepro.reproducer.reducer import GreedyFileReducer
from pyrepro.reproducer.runner import CommandRunner
from pyrepro.reproducer.workspace import ReductionWorkspace, tree_digest


def test_discovery_supports_only_unique_multiline_integer_tuple_lists(
    tmp_path: Path,
):
    """Only the deliberately narrow module-list source form becomes a candidate."""
    source = tmp_path / "data.py"
    source.write_text(
        "CELL_WIDTHS = [\n"
        "    (1, 2, -1),\n"
        "    (3, 4, 0),\n"
        "]\n"
        "ONE_LINE = [(1, 2, 3)]\n"
        "DUPLICATE = [\n    (1, 1),\n    (1, 1),\n]\n"
        "DYNAMIC = [\n    (value, 2),\n]\n"
        "COMMENTED = [\n    # preserve\n    (9, 9),\n]\n",
        encoding="utf-8",
    )

    discovery = discover_list_entries(source, tmp_path)

    assert not discovery.skipped
    assert [(item.container_name, item.values) for item in discovery.containers] == [
        ("CELL_WIDTHS", ((1, 2, -1), (3, 4, 0)))
    ]


def test_removal_preserves_crlf_and_parsable_source(tmp_path: Path):
    """Exact source ranges retain CRLF and leave an empty list valid."""
    source = tmp_path / "data.py"
    source.write_bytes(b"CELL_WIDTHS = [\r\n    (1, 2, -1),\r\n    (3, 4, 0),\r\n]\r\n")

    _remove_entries(source, "CELL_WIDTHS", ((1, 2, -1), (3, 4, 0)))

    data = source.read_bytes()
    assert b"(1, 2, -1)" not in data
    assert b"(3, 4, 0)" not in data
    assert b"\n" not in data.replace(b"\r\n", b"")
    ast.parse(data.decode("utf-8"))


def test_batch_split_preserves_required_entry_and_rolls_back(tmp_path: Path):
    """A rejected list batch splits and retains a runtime-required tuple."""
    project = tmp_path / "project"
    project.mkdir()
    (project / "data.py").write_text(
        "CELL_WIDTHS = [\n    (1, 2, -1),\n    (3, 4, 0),\n    (5, 6, 0),\n]\n",
        encoding="utf-8",
    )
    (project / "reproduce.py").write_text(
        "from data import CELL_WIDTHS\n"
        "assert (1, 2, -1) in CELL_WIDTHS\n"
        "raise ValueError('list reduction failure')\n",
        encoding="utf-8",
    )
    source_digest = tree_digest(project)
    runner = CommandRunner((sys.executable, "reproduce.py"), timeout_seconds=2)

    with ReductionWorkspace(project) as workspace:
        baseline = GreedyFileReducer(runner).reduce(workspace).baseline_signature
        result = GreedyListEntryReducer(runner, max_probes=8).reduce(
            workspace, baseline
        )
        content = (workspace.root / "data.py").read_text(encoding="utf-8")

    assert result.candidate_attempts >= 3
    assert result.accepted_batches >= 1
    assert result.rejected_probes >= 1
    assert result.removed_entries == 2
    assert "(1, 2, -1)" in content
    assert "(3, 4, 0)" not in content
    assert "(5, 6, 0)" not in content
    assert any(record.candidate_rolled_back for record in result.probe_records)
    assert result.source_unchanged
    assert tree_digest(project) == source_digest


def test_shared_budget_stops_before_another_rejected_list_split(tmp_path: Path):
    """The reducer preserves final-verification slots when a batch splits."""
    project = tmp_path / "project"
    project.mkdir()
    (project / "data.py").write_text(
        "CELL_WIDTHS = [\n    (1, 2),\n    (3, 4),\n    (5, 6),\n    (7, 8),\n]\n",
        encoding="utf-8",
    )
    (project / "reproduce.py").write_text(
        "from data import CELL_WIDTHS\n"
        "assert (1, 2) in CELL_WIDTHS\n"
        "raise ValueError('list reduction failure')\n",
        encoding="utf-8",
    )
    runner = CommandRunner((sys.executable, "reproduce.py"), timeout_seconds=2)
    budget = ExecutionBudget(6)

    with ReductionWorkspace(project) as workspace:
        baseline = GreedyFileReducer(runner).reduce(workspace).baseline_signature
        result = GreedyListEntryReducer(runner, max_probes=8).reduce(
            workspace, baseline, budget=budget
        )

    assert result.budget_exhausted
    assert result.candidate_attempts == 3
    assert budget.snapshot().executions_started == 3
