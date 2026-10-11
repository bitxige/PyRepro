"""Tests for independent Fast-Mode staging verification and publication."""

from __future__ import annotations

import errno
import shutil
import sys
from pathlib import Path

import pytest
from pyrepro.reproducer.budget import ExecutionBudget, OracleExecutionKind
from pyrepro.reproducer.failure import (
    FailureMatchMode,
    FailureSignature,
    ReductionOutcome,
    classify_result,
)
from pyrepro.reproducer.publisher import (
    FastModeTerminalState,
    _publish_staging,
    verify_and_publish,
)
from pyrepro.reproducer.runner import CommandRunner
from pyrepro.reproducer.workspace import ReductionWorkspace, tree_digest


def test_publishes_only_after_three_independent_matching_runs(tmp_path: Path):
    """A completed staging verification atomically creates the output directory."""
    source = _project(tmp_path / "source")
    destination = tmp_path / "output"
    runner = CommandRunner([sys.executable, "reproduce.py"], timeout_seconds=2)
    budget = ExecutionBudget(6)

    with ReductionWorkspace(source) as workspace:
        baseline = _establish_budgeted_baseline(runner, workspace.root, budget)
        result = verify_and_publish(
            workspace,
            runner,
            baseline,
            FailureMatchMode.STRICT,
            destination,
            budget,
            search_budget_exhausted=False,
        )

    assert result.state is FastModeTerminalState.COMPLETED
    assert result.verified
    assert result.output_path == destination.resolve()
    assert len(result.verification_attempts) == 3
    assert all(
        attempt.outcome is not None and attempt.outcome.value == "same_failure"
        for attempt in result.verification_attempts
    )
    assert result.budget.executions_started == 6
    assert (destination / "reproduce.py").is_file()
    published = runner.run(destination)
    assert (
        classify_result(published, baseline, destination, FailureMatchMode.STRICT)
        is ReductionOutcome.SAME_FAILURE
    )


def test_existing_output_is_rejected_without_changing_its_contents(tmp_path: Path):
    """An existing user output is never replaced or removed."""
    source = _project(tmp_path / "source")
    destination = tmp_path / "output"
    destination.mkdir()
    marker = destination / "existing.txt"
    marker.write_text("keep me\n", encoding="utf-8")
    runner = CommandRunner([sys.executable, "reproduce.py"], timeout_seconds=2)
    budget = ExecutionBudget(6)

    with ReductionWorkspace(source) as workspace:
        baseline = _establish_budgeted_baseline(runner, workspace.root, budget)
        with pytest.raises(ValueError, match="already exists"):
            verify_and_publish(
                workspace,
                runner,
                baseline,
                FailureMatchMode.STRICT,
                destination,
                budget,
                search_budget_exhausted=False,
            )

    assert marker.read_text(encoding="utf-8") == "keep me\n"
    assert not list(tmp_path.glob(".output.staging-*"))


def test_final_mismatch_does_not_create_output_or_leave_staging(tmp_path: Path):
    """A nonmatching staging run is not published as an official output."""
    source = _project(tmp_path / "source")
    destination = tmp_path / "output"
    runner = CommandRunner([sys.executable, "reproduce.py"], timeout_seconds=2)
    budget = ExecutionBudget(6)

    with ReductionWorkspace(source) as workspace:
        baseline = _establish_budgeted_baseline(runner, workspace.root, budget)
        (workspace.root / "reproduce.py").write_text("raise RuntimeError('other')\n")
        result = verify_and_publish(
            workspace,
            runner,
            baseline,
            FailureMatchMode.STRICT,
            destination,
            budget,
            search_budget_exhausted=False,
        )

    assert result.state is FastModeTerminalState.FINAL_VERIFICATION_FAILED
    assert not result.verified
    assert result.output_path is None
    assert len(result.verification_attempts) == 1
    assert not destination.exists()
    assert not list(tmp_path.glob(".output.staging-*"))


def test_missing_final_slot_returns_unverified_without_output(tmp_path: Path):
    """Incomplete independent verification never creates an official output."""
    source = _project(tmp_path / "source")
    destination = tmp_path / "output"
    runner = CommandRunner([sys.executable, "reproduce.py"], timeout_seconds=2)
    budget = ExecutionBudget(7)

    with ReductionWorkspace(source) as workspace:
        baseline = _establish_budgeted_baseline(runner, workspace.root, budget)
        budget.run_oracle(
            runner, workspace.root, kind=OracleExecutionKind.FINAL_VERIFICATION
        )
        result = verify_and_publish(
            workspace,
            runner,
            baseline,
            FailureMatchMode.STRICT,
            destination,
            budget,
            search_budget_exhausted=True,
        )

    assert result.state is FastModeTerminalState.BUDGET_EXHAUSTED_UNVERIFIED
    assert not result.verified
    assert result.output_path is None
    assert len(result.verification_attempts) == 2
    assert not destination.exists()
    assert not list(tmp_path.glob(".output.staging-*"))


def test_verified_output_reports_budget_exhaustion_after_early_stop(tmp_path: Path):
    """A successful final 3/3 can publish the best budget-stopped workspace."""
    source = _project(tmp_path / "source")
    destination = tmp_path / "output"
    runner = CommandRunner([sys.executable, "reproduce.py"], timeout_seconds=2)
    budget = ExecutionBudget(6)

    with ReductionWorkspace(source) as workspace:
        baseline = _establish_budgeted_baseline(runner, workspace.root, budget)
        result = verify_and_publish(
            workspace,
            runner,
            baseline,
            FailureMatchMode.STRICT,
            destination,
            budget,
            search_budget_exhausted=True,
        )

    assert result.state is FastModeTerminalState.BUDGET_EXHAUSTED_VERIFIED
    assert result.verified
    assert result.output_path == destination.resolve()
    assert len(result.verification_attempts) == 3


def test_source_change_takes_precedence_and_prevents_staging(tmp_path: Path):
    """A protected-source change prevents output publication before execution."""
    source = _project(tmp_path / "source")
    destination = tmp_path / "output"
    runner = CommandRunner([sys.executable, "reproduce.py"], timeout_seconds=2)
    budget = ExecutionBudget(6)
    original_digest = tree_digest(source)

    with ReductionWorkspace(source) as workspace:
        baseline = _establish_budgeted_baseline(runner, workspace.root, budget)
        (source / "source_change.py").write_text("changed = True\n", encoding="utf-8")
        result = verify_and_publish(
            workspace,
            runner,
            baseline,
            FailureMatchMode.STRICT,
            destination,
            budget,
            search_budget_exhausted=False,
        )

    assert result.state is FastModeTerminalState.SOURCE_CHANGED
    assert not result.verified
    assert result.output_path is None
    assert not result.verification_attempts
    assert not destination.exists()
    assert tree_digest(source) != original_digest


def test_source_change_during_final_verification_prevents_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Source integrity takes precedence even after matching staged runs."""
    source = _project(tmp_path / "source")
    destination = tmp_path / "output"
    runner = CommandRunner([sys.executable, "reproduce.py"], timeout_seconds=2)
    budget = ExecutionBudget(6)

    with ReductionWorkspace(source) as workspace:
        baseline = _establish_budgeted_baseline(runner, workspace.root, budget)
        original_run = runner.run

        def modify_source(
            working_directory: Path, *, timeout_seconds: float | None = None
        ):
            (source / "external_change.py").write_text(
                "changed = True\n", encoding="utf-8"
            )
            return original_run(working_directory, timeout_seconds=timeout_seconds)

        monkeypatch.setattr(runner, "run", modify_source)
        result = verify_and_publish(
            workspace,
            runner,
            baseline,
            FailureMatchMode.STRICT,
            destination,
            budget,
            search_budget_exhausted=False,
        )

    assert result.state is FastModeTerminalState.SOURCE_CHANGED
    assert not result.verified
    assert result.output_path is None
    assert len(result.verification_attempts) == 3
    assert not destination.exists()
    assert not list(tmp_path.glob(".output.staging-*"))


def test_publish_failure_removes_staging_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """An atomic-publish error does not expose staging as a verified output."""
    source = _project(tmp_path / "source")
    destination = tmp_path / "output"
    runner = CommandRunner([sys.executable, "reproduce.py"], timeout_seconds=2)
    budget = ExecutionBudget(6)

    def fail_publish(source_path: Path, target_path: Path) -> None:
        del source_path, target_path
        raise OSError("simulated publish failure")

    monkeypatch.setattr("pyrepro.reproducer.publisher._publish_staging", fail_publish)
    with ReductionWorkspace(source) as workspace:
        baseline = _establish_budgeted_baseline(runner, workspace.root, budget)
        result = verify_and_publish(
            workspace,
            runner,
            baseline,
            FailureMatchMode.STRICT,
            destination,
            budget,
            search_budget_exhausted=False,
        )

    assert result.state is FastModeTerminalState.RUNTIME_ERROR
    assert not result.verified
    assert result.output_path is None
    assert "simulated publish failure" in (result.error_message or "")
    assert not destination.exists()
    assert not list(tmp_path.glob(".output.staging-*"))


def test_publish_conflict_preserves_concurrently_created_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """A destination created after validation is not overwritten or removed."""
    source = _project(tmp_path / "source")
    destination = tmp_path / "output"
    runner = CommandRunner([sys.executable, "reproduce.py"], timeout_seconds=2)
    budget = ExecutionBudget(6)

    def create_competing_output(source_path: Path, target_path: Path) -> None:
        del source_path
        target_path.mkdir()
        (target_path / "other-process.txt").write_text("preserve\n", encoding="utf-8")
        raise FileExistsError(errno.EEXIST, "File exists", target_path)

    monkeypatch.setattr(
        "pyrepro.reproducer.publisher._publish_staging", create_competing_output
    )
    with ReductionWorkspace(source) as workspace:
        baseline = _establish_budgeted_baseline(runner, workspace.root, budget)
        result = verify_and_publish(
            workspace,
            runner,
            baseline,
            FailureMatchMode.STRICT,
            destination,
            budget,
            search_budget_exhausted=False,
        )

    assert result.state is FastModeTerminalState.RUNTIME_ERROR
    assert not result.verified
    assert result.output_path is None
    assert (destination / "other-process.txt").read_text(
        encoding="utf-8"
    ) == "preserve\n"
    assert not list(tmp_path.glob(".output.staging-*"))


def test_kernel_no_replace_publish_refuses_an_existing_empty_directory(tmp_path: Path):
    """The Linux publication primitive itself never replaces an empty output."""
    staging = tmp_path / "staging"
    staging.mkdir()
    (staging / "verified.txt").write_text("staged\n", encoding="utf-8")
    output = tmp_path / "output"
    output.mkdir()

    with pytest.raises(FileExistsError):
        _publish_staging(staging, output)

    assert (staging / "verified.txt").read_text(encoding="utf-8") == "staged\n"
    assert output.is_dir()
    assert not list(output.iterdir())


def test_unsupported_platform_fails_without_rename_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Fast Mode refuses to publish where atomic no-clobber is unavailable."""
    staging = tmp_path / "staging"
    staging.mkdir()
    output = tmp_path / "output"
    monkeypatch.setattr("pyrepro.reproducer.publisher.sys.platform", "darwin")

    with pytest.raises(OSError) as error:
        _publish_staging(staging, output)

    assert error.value.errno == errno.ENOTSUP
    assert staging.is_dir()
    assert not output.exists()


def test_staging_copy_failure_returns_runtime_error_and_cleans_up(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """A failed staging copy cannot leave an unverified output behind."""
    source = _project(tmp_path / "source")
    destination = tmp_path / "output"
    runner = CommandRunner([sys.executable, "reproduce.py"], timeout_seconds=2)
    budget = ExecutionBudget(6)

    def fail_copytree(source_path: Path, target_path: Path, **kwargs: object) -> None:
        del source_path, target_path, kwargs
        raise OSError("simulated staging failure")

    with ReductionWorkspace(source) as workspace:
        baseline = _establish_budgeted_baseline(runner, workspace.root, budget)
        monkeypatch.setattr(
            "pyrepro.reproducer.publisher.shutil.copytree", fail_copytree
        )
        result = verify_and_publish(
            workspace,
            runner,
            baseline,
            FailureMatchMode.STRICT,
            destination,
            budget,
            search_budget_exhausted=False,
        )

    assert result.state is FastModeTerminalState.RUNTIME_ERROR
    assert not result.verified
    assert result.output_path is None
    assert "simulated staging failure" in (result.error_message or "")
    assert not destination.exists()
    assert not list(tmp_path.glob(".output.staging-*"))


def test_staging_shutil_error_is_reported_as_runtime_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """The standard-library aggregated copy error is covered by ``OSError``."""
    source = _project(tmp_path / "source")
    destination = tmp_path / "output"
    runner = CommandRunner([sys.executable, "reproduce.py"], timeout_seconds=2)
    budget = ExecutionBudget(6)

    def fail_copytree(source_path: Path, target_path: Path, **kwargs: object) -> None:
        del source_path, target_path, kwargs
        raise shutil.Error([("source", "target", "simulated copy failure")])

    with ReductionWorkspace(source) as workspace:
        baseline = _establish_budgeted_baseline(runner, workspace.root, budget)
        monkeypatch.setattr(
            "pyrepro.reproducer.publisher.shutil.copytree", fail_copytree
        )
        result = verify_and_publish(
            workspace,
            runner,
            baseline,
            FailureMatchMode.STRICT,
            destination,
            budget,
            search_budget_exhausted=False,
        )

    assert result.state is FastModeTerminalState.RUNTIME_ERROR
    assert not result.verified
    assert result.output_path is None
    assert "simulated copy failure" in (result.error_message or "")
    assert not destination.exists()
    assert not list(tmp_path.glob(".output.staging-*"))


def _establish_budgeted_baseline(
    runner: CommandRunner, root: Path, budget: ExecutionBudget
) -> FailureSignature:
    """Create a deterministic three-run baseline through the shared budget."""
    signatures = []
    for _ in range(3):
        result = budget.run_oracle(runner, root, kind=OracleExecutionKind.BASELINE)
        signature = FailureSignature.from_result(result, root)
        assert signature is not None
        signatures.append(signature)
    assert len(set(signatures)) == 1
    return signatures[0]


def _project(root: Path) -> Path:
    """Create one small project with a strict, deterministic failure."""
    root.mkdir()
    (root / "reproduce.py").write_text(
        "def fail():\n    raise ValueError('target failure')\n\nfail()\n",
        encoding="utf-8",
    )
    return root
