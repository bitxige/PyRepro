"""Tests for bounded direct module-level main-guard reduction."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from pyrepro.reproducer.failure import ReductionOutcome
from pyrepro.reproducer.main_guard_reducer import (
    GreedyMainGuardReducer,
    _remove_main_guard_batch,
    discover_main_guards,
)
from pyrepro.reproducer.reducer import GreedyFileReducer
from pyrepro.reproducer.runner import CommandRunner
from pyrepro.reproducer.workspace import ReductionWorkspace, tree_digest


def test_discovery_accepts_only_direct_exact_main_guard_orders(tmp_path: Path):
    """Discovery excludes ordinary, nested, and non-exact module conditions."""
    source = tmp_path / "module.py"
    source.write_text(
        """if __name__ == "__main__":  # pragma: no cover
    first = 1

if "__main__" == __name__:
    second = 2

if __name__ != "__main__":
    third = 3

if __name__ == "__main__" and enabled:
    fourth = 4

def nested() -> None:
    if __name__ == "__main__":
        fifth = 5
""",
        encoding="utf-8",
    )

    discovery = discover_main_guards(source, tmp_path)

    assert not discovery.skipped
    assert [(item.start_line, item.end_line) for item in discovery.candidates] == [
        (1, 2),
        (4, 5),
    ]


def test_main_guard_removal_preserves_leading_comment_crlf_and_syntax(tmp_path: Path):
    """Removal consumes a header comment but preserves an independent one."""
    source = tmp_path / "module.py"
    source.write_bytes(
        (
            "# Keep this independent explanation.\r\n"
            'if __name__ == "__main__":  # pragma: no cover\r\n'
            '    label = "中文"\r\n'
            "    print(label)\r\n"
            "after = 1\r\n"
        ).encode()
    )
    candidate = discover_main_guards(source, tmp_path).candidates[0]

    _remove_main_guard_batch(tmp_path, (candidate,))

    data = source.read_bytes()
    assert b"Keep this independent explanation" in data
    assert b"pragma: no cover" not in data
    assert "中文".encode() not in data
    assert b"after = 1\r\n" in data
    assert b"\n" not in data.replace(b"\r\n", b"")
    ast.parse(data.decode("utf-8"))


def test_reducer_rolls_back_rejections_and_rediscovers_after_acceptance(
    tmp_path: Path,
):
    """A rejected batch splits and accepted edits do not leave stale ranges."""
    project = tmp_path / "project"
    project.mkdir()
    (project / "module.py").write_text(
        """if __name__ == "__main__":
    unused_value = 1

if "__main__" == __name__:  # pragma: no cover
    raise ValueError("main guard reduction failure")
""",
        encoding="utf-8",
    )
    (project / "reproduce.py").write_text(
        """import runpy

runpy.run_module("module", run_name="__main__")
""",
        encoding="utf-8",
    )
    source_digest = tree_digest(project)
    runner = CommandRunner((sys.executable, "reproduce.py"), timeout_seconds=2)

    with ReductionWorkspace(project) as workspace:
        baseline = GreedyFileReducer(runner).reduce(workspace).baseline_signature
        result = GreedyMainGuardReducer(runner, max_probes=5).reduce(
            workspace, baseline
        )
        content = (workspace.root / "module.py").read_text(encoding="utf-8")

    assert result.initial_candidates == 2
    assert result.candidate_attempts == 3
    assert result.accepted_batches == 1
    assert result.rejected_probes == 2
    assert result.removed_guards == 1
    assert result.initial_python_lines - result.remaining_python_lines == 2
    assert "unused_value" not in content
    assert "main guard reduction failure" in content
    assert any(record.candidate_rolled_back for record in result.probe_records)
    assert any(
        record.outcome is not ReductionOutcome.SAME_FAILURE
        for record in result.probe_records
    )
    assert result.source_unchanged
    assert tree_digest(project) == source_digest


def test_recursive_splitting_does_not_exceed_probe_limit(tmp_path: Path):
    """A rejected split tree never starts more probes than its configured cap."""
    project = tmp_path / "project"
    project.mkdir()
    (project / "module.py").write_text(
        """if __name__ == "__main__":
    first = True

if __name__ == "__main__":
    second = True

if __name__ == "__main__":
    third = True

if __name__ == "__main__":
    fourth = True

if not all((
    globals().get("first"),
    globals().get("second"),
    globals().get("third"),
    globals().get("fourth"),
)):
    raise RuntimeError("guard was removed")
raise ValueError("main guard reduction failure")
""",
        encoding="utf-8",
    )
    (project / "reproduce.py").write_text(
        """import runpy

runpy.run_module("module", run_name="__main__")
""",
        encoding="utf-8",
    )
    runner = CommandRunner((sys.executable, "reproduce.py"), timeout_seconds=2)

    with ReductionWorkspace(project) as workspace:
        baseline = GreedyFileReducer(runner).reduce(workspace).baseline_signature
        result = GreedyMainGuardReducer(runner, max_probes=2).reduce(
            workspace, baseline, verify_final=False
        )

    assert result.initial_candidates == 4
    assert result.candidate_attempts == 2
    assert result.accepted_batches == 0
    assert result.rejected_probes == 2
    assert result.initial_python_lines == result.remaining_python_lines
