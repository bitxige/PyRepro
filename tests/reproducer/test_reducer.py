"""End-to-end tests for the P0 greedy file reducer."""

import sys
from pathlib import Path

import pytest
from pyrepro.reproducer.failure import FailureSignature, ReductionOutcome
from pyrepro.reproducer.reducer import GreedyFileReducer, UnstableBaselineError
from pyrepro.reproducer.runner import CommandRunner, ExecutionResult
from pyrepro.reproducer.workspace import ReductionWorkspace, tree_digest

FAILING_PROJECT = Path(__file__).parents[2] / "examples" / "failing_project"


def test_reducer_removes_ballast_preserves_failure_and_source(tmp_path: Path):
    """Delete unrelated files while retaining the exact parser KeyError signature."""
    source_digest = tree_digest(FAILING_PROJECT)
    runner = CommandRunner((sys.executable, "reproduce.py"), timeout_seconds=2)
    output = tmp_path / "reduced-project"

    with ReductionWorkspace(FAILING_PROJECT) as workspace:
        result = GreedyFileReducer(runner).reduce(workspace)
        destination = workspace.copy_reduced_to(output)

    final_result = runner.run(destination)
    final_signature = FailureSignature.from_result(final_result, destination)
    model_decision = next(
        decision for decision in result.decisions if decision.path == "app/model.py"
    )

    assert result.baseline_runs == 3
    assert result.baseline_signature == final_signature
    assert result.initial_python_files == 12
    assert result.remaining_python_files == 3
    assert result.source_unchanged
    assert model_decision.outcome is ReductionOutcome.DIFFERENT_FAILURE
    assert not model_decision.removed
    assert tree_digest(FAILING_PROJECT) == source_digest
    remaining_python_files = {
        path.relative_to(destination).as_posix() for path in destination.rglob("*.py")
    }
    assert remaining_python_files == {
        "reproduce.py",
        "app/parser.py",
        "app/model.py",
    }
    assert not list(destination.rglob("__pycache__"))


def test_reducer_rejects_an_unstable_three_run_baseline(tmp_path: Path):
    """Abort before deletion when the baseline traceback frame changes."""
    with ReductionWorkspace(FAILING_PROJECT) as workspace:
        reducer = GreedyFileReducer(_UnstableRunner())

        with pytest.raises(UnstableBaselineError, match="unstable"):
            reducer.reduce(workspace)


class _UnstableRunner:
    """Return two different uncaught Python failures for baseline testing."""

    def __init__(self) -> None:
        """Initialize the alternating result counter."""
        self.calls = 0

    def run(self, working_directory: Path) -> ExecutionResult:
        """Return a failure whose final frame changes after the first call.

        Args:
            working_directory: Workspace root used in generated traceback paths.

        Returns:
            Alternating captured failure result.
        """
        self.calls += 1
        file_name = "app/parser.py" if self.calls == 1 else "app/model.py"
        function = "parse_lane" if self.calls == 1 else "build_lane"
        stderr = f"""Traceback (most recent call last):
  File "{working_directory / file_name}", line 1, in {function}
    raise KeyError("width")
KeyError: 'width'
"""
        return ExecutionResult(("python", "reproduce.py"), 1, "", stderr, False)
