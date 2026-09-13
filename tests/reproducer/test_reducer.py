"""End-to-end tests for greedy and grouped file reduction."""

import shutil
import sys
from pathlib import Path

import pytest
from pyrepro.reproducer.failure import (
    FailureSignature,
    ReductionOutcome,
    classify_result,
)
from pyrepro.reproducer.reducer import (
    DdminFileReducer,
    GreedyFileReducer,
    UnstableBaselineError,
    _partition,
)
from pyrepro.reproducer.runner import CommandRunner, ExecutionResult
from pyrepro.reproducer.workspace import ReductionWorkspace, tree_digest

FAILING_PROJECT = Path(__file__).parents[2] / "examples" / "failing_project"
TRAINING_PROJECT = Path(__file__).parents[2] / "examples" / "training_failure"
GROUPED_PROJECT = Path(__file__).parents[2] / "examples" / "grouped_failure"


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


def test_reducer_skips_project_data_directories_and_honors_expectation(
    tmp_path: Path,
):
    """Preserve the training failure without deleting protected data candidates."""
    source_digest = tree_digest(TRAINING_PROJECT)
    runner = CommandRunner((sys.executable, "train.py"), timeout_seconds=2)
    output = tmp_path / "reduced-training-project"

    with ReductionWorkspace(TRAINING_PROJECT) as workspace:
        result = GreedyFileReducer(
            runner, expected_text="operands could not be broadcast"
        ).reduce(workspace)
        destination = workspace.copy_reduced_to(output)

    remaining_python_files = {
        path.relative_to(destination).as_posix() for path in destination.rglob("*.py")
    }

    assert result.initial_python_files == 12
    assert result.remaining_python_files == 4
    assert result.source_unchanged
    assert all(not decision.path.startswith("data/") for decision in result.decisions)
    assert remaining_python_files == {
        "agent/trainer.py",
        "data/sample_batch.py",
        "environment/road_env.py",
        "reward/shaping.py",
        "train.py",
    }
    assert tree_digest(TRAINING_PROJECT) == source_digest


def test_reducer_rejects_a_nonmatching_expected_failure():
    """Require the optional expectation to match the established baseline."""
    runner = CommandRunner((sys.executable, "train.py"), timeout_seconds=2)

    with ReductionWorkspace(TRAINING_PROJECT) as workspace:
        reducer = GreedyFileReducer(runner, expected_text="IndexError")

        with pytest.raises(UnstableBaselineError, match="expected text"):
            reducer.reduce(workspace)


def test_ddmin_reducer_preserves_p0_failure_and_counts_minimality_probes(
    tmp_path: Path,
):
    """Verify ddmin accounting and 1-minimal verification on the P0 fixture."""
    runner = CommandRunner((sys.executable, "reproduce.py"), timeout_seconds=2)
    output = tmp_path / "ddmin-reduced-project"

    with ReductionWorkspace(FAILING_PROJECT) as workspace:
        result = DdminFileReducer(runner).reduce(workspace)
        destination = workspace.copy_reduced_to(output)

    final_result = runner.run(destination)
    final_signature = FailureSignature.from_result(final_result, destination)
    minimality_probes = [
        probe for probe in result.probes if probe.phase == "minimality"
    ]

    assert result.strategy == "ddmin"
    assert result.baseline_signature == final_signature
    assert result.executions == result.baseline_runs + result.candidate_attempts + 1
    assert result.candidate_attempts == len(result.probes)
    assert result.initial_python_lines > result.remaining_python_lines
    assert result.removed_candidate_files == (
        result.initial_python_files - result.remaining_python_files
    )
    assert result.wall_clock_seconds >= 0
    assert len(minimality_probes) == result.remaining_python_files
    assert all(
        probe.outcome is not ReductionOutcome.SAME_FAILURE
        for probe in minimality_probes
    )
    assert result.source_unchanged


def test_partition_uses_deterministic_balanced_groups():
    """Split ordered paths into stable non-empty groups for grouped probes."""
    paths = tuple(Path(f"module_{index}.py") for index in range(5))

    groups = _partition(paths, 3)

    assert groups == (
        (Path("module_0.py"), Path("module_1.py")),
        (Path("module_2.py"), Path("module_3.py")),
        (Path("module_4.py"),),
    )


def test_grouped_fixture_requires_optional_pair_to_be_removed_together():
    """Establish the benchmark's single-delete versus grouped-delete contract."""
    runner = CommandRunner((sys.executable, "reproduce.py"), timeout_seconds=2)

    with ReductionWorkspace(GROUPED_PROJECT) as workspace:
        baseline_result = runner.run(workspace.root)
        baseline = FailureSignature.from_result(baseline_result, workspace.root)

        assert baseline is not None
        assert (
            _outcome_after_removing(
                runner, workspace.root, baseline, "optional/optional_a.py"
            )
            is ReductionOutcome.DIFFERENT_FAILURE
        )
        assert (
            _outcome_after_removing(
                runner, workspace.root, baseline, "optional/optional_b.py"
            )
            is ReductionOutcome.DIFFERENT_FAILURE
        )
        assert (
            _outcome_after_removing(
                runner,
                workspace.root,
                baseline,
                "optional/optional_a.py",
                "optional/optional_b.py",
            )
            is ReductionOutcome.SAME_FAILURE
        )


def test_ddmin_removes_the_coupled_pair_that_greedy_retains(tmp_path: Path):
    """Compare reduction quality and execution accounting on grouped failure."""
    runner = CommandRunner((sys.executable, "reproduce.py"), timeout_seconds=2)

    with ReductionWorkspace(GROUPED_PROJECT) as workspace:
        greedy_result = GreedyFileReducer(runner).reduce(workspace)
        greedy_output = workspace.copy_reduced_to(tmp_path / "greedy-output")

    with ReductionWorkspace(GROUPED_PROJECT) as workspace:
        ddmin_result = DdminFileReducer(runner).reduce(workspace)
        ddmin_output = workspace.copy_reduced_to(tmp_path / "ddmin-output")

    ddmin_minimality_probes = [
        probe for probe in ddmin_result.probes if probe.phase == "minimality"
    ]

    assert greedy_result.initial_python_files == 33
    assert greedy_result.remaining_python_files == 7
    assert ddmin_result.initial_python_files == 33
    assert ddmin_result.remaining_python_files == 5
    assert ddmin_result.removed_candidate_files > greedy_result.removed_candidate_files
    assert greedy_result.initial_python_lines > greedy_result.remaining_python_lines
    assert ddmin_result.initial_python_lines > ddmin_result.remaining_python_lines
    assert greedy_result.wall_clock_seconds >= 0
    assert ddmin_result.wall_clock_seconds >= 0
    assert (greedy_output / "optional" / "optional_a.py").is_file()
    assert (greedy_output / "optional" / "optional_b.py").is_file()
    assert not (ddmin_output / "optional" / "optional_a.py").exists()
    assert not (ddmin_output / "optional" / "optional_b.py").exists()
    assert ddmin_result.executions == (
        ddmin_result.baseline_runs + ddmin_result.candidate_attempts + 1
    )
    assert len(ddmin_minimality_probes) == ddmin_result.remaining_python_files
    assert all(
        probe.outcome is not ReductionOutcome.SAME_FAILURE
        for probe in ddmin_minimality_probes
    )
    assert ddmin_result.source_unchanged
    assert greedy_result.source_unchanged


def _outcome_after_removing(
    runner: CommandRunner,
    workspace_root: Path,
    baseline: FailureSignature,
    *relative_paths: str,
) -> ReductionOutcome:
    removed_paths = [workspace_root / relative_path for relative_path in relative_paths]
    backup_root = workspace_root.parent / "pair-backup"
    backup_root.mkdir()
    try:
        for path in removed_paths:
            shutil.copy2(path, backup_root / path.name)
            path.unlink()
        return classify_result(runner.run(workspace_root), baseline, workspace_root)
    finally:
        for path in removed_paths:
            backup = backup_root / path.name
            if backup.exists():
                shutil.copy2(backup, path)
        shutil.rmtree(backup_root)


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
