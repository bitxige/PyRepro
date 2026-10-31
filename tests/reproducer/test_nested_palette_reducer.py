"""Tests for conservative nested ``Palette([...])`` entry reduction."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from pyrepro.reproducer.nested_palette_reducer import (
    GreedyNestedPaletteReducer,
    _remove_palette_entries,
    discover_nested_palette_entries,
)
from pyrepro.reproducer.reducer import GreedyFileReducer
from pyrepro.reproducer.runner import CommandRunner
from pyrepro.reproducer.workspace import ReductionWorkspace, tree_digest


def test_discovery_preserves_duplicate_rgb_entry_identities(tmp_path: Path):
    """Duplicate RGB values remain separate candidates by current position."""
    source = tmp_path / "palette.py"
    source.write_text(
        "EIGHT_BIT_PALETTE = Palette(\n"
        "    [\n"
        "        (1, 2, 3),\n"
        "        (1, 2, 3),\n"
        "        (4, 5, 6),\n"
        "    ],\n"
        "    name='eight-bit',\n"
        ")\n",
        encoding="utf-8",
    )

    discovery = discover_nested_palette_entries(source, tmp_path)

    assert not discovery.skipped
    assert len(discovery.candidates) == 1
    candidate = discovery.candidates[0]
    assert candidate.binding_name == "EIGHT_BIT_PALETTE"
    assert candidate.entry_indices == (0, 1, 2)
    assert candidate.source_span == 5


def test_discovery_excludes_unsupported_nested_lists(tmp_path: Path):
    """Booleans, comments, expressions, and wrong constructors are skipped."""
    source = tmp_path / "palette.py"
    source.write_text(
        "EIGHT_BIT_PALETTE = Palette([\n    (1, 2, True),\n])\n",
        encoding="utf-8",
    )

    assert not discover_nested_palette_entries(source, tmp_path).candidates


def test_discovery_accepts_any_unambiguous_palette_binding(tmp_path: Path):
    """Discovery is structural and does not depend on a Rich-specific name."""
    source = tmp_path / "palette.py"
    source.write_text(
        "CUSTOM_COLORS = Palette(\n"
        "    [\n        (1, 2, 3),\n    ],\n"
        "    label='custom',\n"
        ")\n",
        encoding="utf-8",
    )

    discovery = discover_nested_palette_entries(source, tmp_path)

    assert [item.binding_name for item in discovery.candidates] == ["CUSTOM_COLORS"]

    source.write_text(
        source.read_text(encoding="utf-8") + "CUSTOM_COLORS = None\n",
        encoding="utf-8",
    )
    assert not discover_nested_palette_entries(source, tmp_path).candidates

    source.write_text(
        "EIGHT_BIT_PALETTE = Palette(\n    [(red, 2, 3)]\n)\n",
        encoding="utf-8",
    )
    assert not discover_nested_palette_entries(source, tmp_path).candidates

    source.write_text(
        "EIGHT_BIT_PALETTE = NotPalette(\n    [\n        (1, 2, 3),\n    ]\n)\n",
        encoding="utf-8",
    )
    assert not discover_nested_palette_entries(source, tmp_path).candidates

    source.write_text(
        "EIGHT_BIT_PALETTE = Palette(\n"
        "    [\n        # preserve this boundary\n        (1, 2, 3),\n    ]\n)\n",
        encoding="utf-8",
    )
    assert not discover_nested_palette_entries(source, tmp_path).candidates


def test_exact_removal_preserves_outer_call_arguments_and_crlf(tmp_path: Path):
    """Byte-range deletion keeps the constructor, trailing args, and CRLF."""
    source = tmp_path / "palette.py"
    source.write_bytes(
        (
            "EIGHT_BIT_PALETTE = Palette(\r\n"
            "    [\r\n        (1, 2, 3),\r\n        (4, 5, 6),\r\n    ],\r\n"
            "    background=(7, 8, 9), label='中文',\r\n)\r\n"
        ).encode()
    )
    candidates = discover_nested_palette_entries(source, tmp_path).candidates
    assert len(candidates) == 1
    candidate = candidates[0]

    _remove_palette_entries(tmp_path, candidate)

    data = source.read_bytes()
    assert b"Palette(" in data
    assert b"background=(7, 8, 9)" in data
    assert "label='中文'".encode() in data
    assert b"(1, 2, 3)" not in data
    assert b"(4, 5, 6)" not in data
    assert b"\n" not in data.replace(b"\r\n", b"")
    ast.parse(data.decode("utf-8"))


def test_reducer_accepts_one_complete_palette_batch(tmp_path: Path):
    """A strictly preserved failure accepts deleting a complete RGB list."""
    project = tmp_path / "project"
    project.mkdir()
    (project / "palette.py").write_text(
        "class Palette:\n"
        "    def __init__(self, colors, *, name):\n"
        "        self.colors = colors\n\n"
        "EIGHT_BIT_PALETTE = Palette(\n"
        "    [\n        (1, 2, 3),\n        (4, 5, 6),\n    ],\n"
        "    name='test',\n"
        ")\n",
        encoding="utf-8",
    )
    (project / "reproduce.py").write_text(
        "from palette import EIGHT_BIT_PALETTE\n"
        "assert isinstance(EIGHT_BIT_PALETTE.colors, list)\n"
        "raise ValueError('nested palette failure')\n",
        encoding="utf-8",
    )
    runner = CommandRunner((sys.executable, "reproduce.py"), timeout_seconds=2)

    with ReductionWorkspace(project) as workspace:
        baseline = GreedyFileReducer(runner).reduce(workspace).baseline_signature
        result = GreedyNestedPaletteReducer(runner, max_probes=8).reduce(
            workspace, baseline
        )

    assert result.candidate_attempts == 1
    assert result.accepted_batches == 1
    assert result.rejected_probes == 0
    assert result.removed_entries == 2


def test_batch_split_rolls_back_required_rgb_entry(tmp_path: Path):
    """Rejected batches split while the active workspace retains required RGB."""
    project = tmp_path / "project"
    project.mkdir()
    (project / "palette.py").write_text(
        "class Palette:\n"
        "    def __init__(self, colors, *, name):\n"
        "        self.colors = colors\n"
        "        self.name = name\n\n"
        "EIGHT_BIT_PALETTE = Palette(\n"
        "    [\n        (1, 2, 3),\n        (4, 5, 6),\n        (7, 8, 9),\n    ],\n"
        "    name='test',\n"
        ")\n",
        encoding="utf-8",
    )
    (project / "reproduce.py").write_text(
        "from palette import EIGHT_BIT_PALETTE\n"
        "assert (1, 2, 3) in EIGHT_BIT_PALETTE.colors\n"
        "raise ValueError('nested palette failure')\n",
        encoding="utf-8",
    )
    source_digest = tree_digest(project)
    runner = CommandRunner((sys.executable, "reproduce.py"), timeout_seconds=2)

    with ReductionWorkspace(project) as workspace:
        baseline = GreedyFileReducer(runner).reduce(workspace).baseline_signature
        result = GreedyNestedPaletteReducer(runner, max_probes=8).reduce(
            workspace, baseline
        )
        content = (workspace.root / "palette.py").read_text(encoding="utf-8")

    assert result.initial_candidates == 3
    assert result.candidate_attempts == 4
    assert result.accepted_batches == 1
    assert result.rejected_probes == 3
    assert result.removed_entries == 2
    assert "(1, 2, 3)" in content
    assert "(4, 5, 6)" not in content
    assert "(7, 8, 9)" not in content
    assert any(record.candidate_rolled_back for record in result.probe_records)
    assert result.source_unchanged
    assert tree_digest(project) == source_digest
