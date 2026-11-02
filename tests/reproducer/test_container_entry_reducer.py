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
        "COMPUTED = {\n    'sum': 1 + 2,\n}\n"
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
    assert all(item.container_name != "COMPUTED" for item in discovered.containers)


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


def test_partial_discovery_keeps_unsupported_entries_and_comments(tmp_path: Path):
    """A mixed dictionary yields only independently source-safe candidates."""
    source = tmp_path / "styles.py"
    source.write_text(
        """DEFAULT_STYLES = {
    'safe': Style(color='green'),
    'null': Style.null(),
    'commented': Style(bold=True),  # retain this comment
    'after_comment': Style(italic=True),
    'dynamic': Style(color=factory()),
    '中文': Style(color='cyan'),
}
""",
        encoding="utf-8",
    )

    discovered = discover_container_entries(source, tmp_path)

    assert not discovered.skipped
    assert [(item.container_name, item.keys) for item in discovered.containers] == [
        ("DEFAULT_STYLES", ("safe", "after_comment", "中文"))
    ]


def test_partial_removal_preserves_crlf_utf8_and_comment_adjacent_entries(
    tmp_path: Path,
):
    """Exact edits keep unsupported and comment-adjacent source unchanged."""
    source = tmp_path / "styles.py"
    source.write_bytes(
        b"".join(
            (
                b"DEFAULT_STYLES = {\r\n",
                "    '中文': Style(color='cyan'),\r\n".encode(),
                b"    'null': Style.null(),\r\n",
                b"    'commented': Style(bold=True),  # retain this comment\r\n",
                b"}\r\n",
                b"OTHER = 1\r\n",
            )
        )
    )

    _remove_entries(source, "DEFAULT_STYLES", ("中文",))

    data = source.read_bytes()
    assert "'中文'".encode() not in data
    assert b"DEFAULT_STYLES = {" in data
    assert b"Style.null()" in data
    assert b"# retain this comment" in data
    assert b"OTHER = 1" in data
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
    assert result.initial_python_lines > result.remaining_python_lines
    assert "'solid'" in content
    assert "'dashed'" not in content
    assert "'double'" not in content
    assert "ANSI_COLOR_NAMES = {" in content
    assert any(record.candidate_rolled_back for record in result.probe_records)
    assert result.source_unchanged
    assert tree_digest(project) == source_digest


def test_partial_batch_split_preserves_excluded_and_required_entries(tmp_path: Path):
    """Mixed supported dictionaries split and retain unsafe or required entries."""
    project = tmp_path / "project"
    project.mkdir()
    (project / "styles.py").write_text(
        """class Style:
    def __init__(self, **kwargs):
        self.kwargs = kwargs

    @classmethod
    def null(cls):
        return cls()


DEFAULT_STYLES = {
    'solid': Style(color='green'),
    'dashed': Style(color='yellow'),
    'commented': Style(bold=True),  # preserve
    'null': Style.null(),
}
""",
        encoding="utf-8",
    )
    (project / "reproduce.py").write_text(
        """from styles import DEFAULT_STYLES

DEFAULT_STYLES['solid']
raise ValueError('partial container reduction failure')
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
        content = (workspace.root / "styles.py").read_text(encoding="utf-8")

    assert result.initial_candidates == 2
    assert result.candidate_attempts >= 3
    assert result.accepted_batches >= 1
    assert result.rejected_probes >= 1
    assert result.removed_entries == 1
    assert result.initial_python_lines > result.remaining_python_lines
    assert "'solid'" in content
    assert "'dashed'" not in content
    assert "'commented'" in content
    assert "# preserve" in content
    assert "Style.null()" in content
    assert any(record.candidate_rolled_back for record in result.probe_records)
    assert result.source_unchanged
    assert tree_digest(project) == source_digest
