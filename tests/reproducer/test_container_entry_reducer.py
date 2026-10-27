"""Tests for conservative module-dictionary entry reduction."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from pyrepro.reproducer.container_entry_reducer import (
    GreedyContainerEntryReducer,
    _remove_entries,
    discover_container_entries,
)
from pyrepro.reproducer.reducer import GreedyFileReducer
from pyrepro.reproducer.runner import CommandRunner
from pyrepro.reproducer.workspace import ReductionWorkspace, tree_digest


def test_discovery_supports_static_strings_integers_and_direct_static_constructor(
    tmp_path: Path,
):
    """Only supported module dictionaries become candidates."""
    source = tmp_path / "data.py"
    source.write_text(
        """CODES = {
    """
        + '    "中文": "value",\n'
        + "    'plain': 'text',\n"
        "}\n"
        "SPECS: dict[str, object] = {\n"
        "    'solid': MarkingSpec('solid', ('white', 1)),\n"
        "}\n"
        "DYNAMIC = {'nope': factory()}\n"
        "NUMBERS = {\n    'one': 1,\n    'two': 2,\n}\n"
        "BOOLEAN = {\n    'no': False,\n}\n"
        "FLOATS = {\n    'half': 0.5,\n}\n"
        "COMMENTED = {\n    # keep\n    'x': 'y',\n}\n"
        "SEMICOLON = {'x': 'y'}; OTHER = 1\n"
        "prefix, REBOUND = ('old', 'old')\n"
        "REBOUND = {\n    'x': 'y',\n}\n",
        encoding="utf-8",
    )

    discovered = discover_container_entries(source, tmp_path)

    assert not discovered.skipped
    assert [(item.container_name, item.keys) for item in discovered.containers] == [
        ("CODES", ("中文", "plain")),
        ("SPECS", ("solid",)),
        ("NUMBERS", ("one", "two")),
    ]


def test_removal_preserves_crlf_binding_and_parsable_source(tmp_path: Path):
    """Exact byte edits retain CRLF while removing selected dictionary entries."""
    source = tmp_path / "data.py"
    source.write_bytes(
        b"ANSI_COLOR_NAMES = {\r\n"
        b"    'black': 0,\r\n"
        b"    'keep': 1,\r\n"
        b"}\r\n"
        b"OTHER = {'unchanged': 1}\r\n"
    )

    _remove_entries(source, "ANSI_COLOR_NAMES", ("black",))

    data = source.read_bytes()
    assert b"'black': 0" not in data
    assert b"ANSI_COLOR_NAMES = {" in data
    assert b"'keep': 1" in data
    assert b"OTHER = {'unchanged': 1}" in data
    assert b"\n" not in data.replace(b"\r\n", b"")
    ast.parse(data.decode("utf-8"))


def test_batch_split_keeps_required_entry_and_rolls_back_rejections(tmp_path: Path):
    """A rejected whole dictionary is split until only its needed entry remains."""
    project = tmp_path / "project"
    project.mkdir()
    (project / "config.py").write_text(
        """ANSI_COLOR_NAMES = {
    'solid': 1,
    'dashed': 2,
    'double': 3,
}
""",
        encoding="utf-8",
    )
    (project / "reproduce.py").write_text(
        """from config import ANSI_COLOR_NAMES

ANSI_COLOR_NAMES['solid']
raise ValueError('container reduction failure')
""",
        encoding="utf-8",
    )
    source_digest = tree_digest(project)
    runner = CommandRunner((sys.executable, "reproduce.py"), timeout_seconds=2)

    with ReductionWorkspace(project) as workspace:
        baseline = GreedyFileReducer(runner).reduce(workspace).baseline_signature
        result = GreedyContainerEntryReducer(runner, max_probes=8).reduce(
            workspace, baseline
        )
        content = (workspace.root / "config.py").read_text(encoding="utf-8")

    assert result.candidate_attempts >= 3
    assert result.accepted_batches >= 1
    assert result.rejected_probes >= 1
    assert result.removed_entries == 2
    assert "'solid'" in content
    assert "'dashed'" not in content
    assert "'double'" not in content
    assert "ANSI_COLOR_NAMES = {" in content
    assert any(record.candidate_rolled_back for record in result.probe_records)
    assert result.source_unchanged
    assert tree_digest(project) == source_digest
