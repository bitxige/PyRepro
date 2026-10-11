"""Tests for the P6a shared Fast-Mode execution budget."""

from __future__ import annotations

from pathlib import Path

import pytest
from pyrepro.reproducer.budget import (
    BudgetExhaustedError,
    BudgetStopReason,
    ExecutionBudget,
    OracleExecutionKind,
)
from pyrepro.reproducer.runner import CommandRunner, ExecutionResult


class _FakeRunner:
    """Record budget-provided timeouts without starting a subprocess."""

    timeout_seconds = 10.0

    def __init__(self) -> None:
        """Initialize recorded calls."""
        self.timeouts: list[float | None] = []

    def run(
        self, working_directory: Path, *, timeout_seconds: float | None = None
    ) -> ExecutionResult:
        """Record the effective timeout and return a deterministic result."""
        del working_directory
        self.timeouts.append(timeout_seconds)
        return ExecutionResult((), 1, "", "error", False)


def test_six_execution_budget_reserves_final_three_slots(tmp_path: Path):
    """A six-run budget permits three baseline calls and only final calls after."""
    budget = ExecutionBudget(6)
    runner = _FakeRunner()

    for _ in range(3):
        budget.run_oracle(runner, tmp_path, kind=OracleExecutionKind.BASELINE)

    assert not budget.can_start_probe()
    with pytest.raises(BudgetExhaustedError) as error:
        budget.run_oracle(runner, tmp_path, kind=OracleExecutionKind.PROBE)
    assert error.value.reason is BudgetStopReason.EXECUTION_RESERVE

    for _ in range(3):
        budget.run_oracle(runner, tmp_path, kind=OracleExecutionKind.FINAL_VERIFICATION)

    assert budget.snapshot().executions_started == 6
    assert budget.snapshot().final_verifications_started == 3
    with pytest.raises(BudgetExhaustedError) as error:
        budget.run_oracle(runner, tmp_path, kind=OracleExecutionKind.FINAL_VERIFICATION)
    assert error.value.reason is BudgetStopReason.EXECUTION_LIMIT


def test_budget_does_not_start_more_than_reserved_final_verifications(
    tmp_path: Path,
):
    """Unused ordinary slots cannot turn a 3/3 final check into a fourth run."""
    budget = ExecutionBudget(7)
    runner = _FakeRunner()

    for _ in range(3):
        budget.run_oracle(runner, tmp_path, kind=OracleExecutionKind.FINAL_VERIFICATION)

    with pytest.raises(BudgetExhaustedError) as error:
        budget.run_oracle(runner, tmp_path, kind=OracleExecutionKind.FINAL_VERIFICATION)
    assert error.value.reason is BudgetStopReason.FINAL_VERIFICATION_LIMIT


def test_budget_rejects_limits_below_final_reserve():
    """A budget cannot promise final verification without enough slots."""
    with pytest.raises(ValueError, match="baseline and final verification"):
        ExecutionBudget(5)


def test_budget_counts_oracle_timeout_as_started(tmp_path: Path):
    """A command that returns a timeout result still consumes one execution."""
    budget = ExecutionBudget(6)

    class TimeoutRunner(_FakeRunner):
        def run(
            self, working_directory: Path, *, timeout_seconds: float | None = None
        ) -> ExecutionResult:
            self.timeouts.append(timeout_seconds)
            return ExecutionResult((), None, "", "", True)

    runner = TimeoutRunner()
    result = budget.run_oracle(runner, tmp_path, kind=OracleExecutionKind.PROBE)

    assert result.timed_out
    assert budget.snapshot().executions_started == 1


def test_budget_counts_runner_exception_after_an_oracle_attempt(tmp_path: Path):
    """An execution-path exception consumes the slot it already started."""
    budget = ExecutionBudget(6)

    class ErrorRunner(_FakeRunner):
        def run(
            self, working_directory: Path, *, timeout_seconds: float | None = None
        ) -> ExecutionResult:
            self.timeouts.append(timeout_seconds)
            raise OSError("simulated runner failure")

    runner = ErrorRunner()
    with pytest.raises(OSError, match="simulated runner failure"):
        budget.run_oracle(runner, tmp_path, kind=OracleExecutionKind.BASELINE)

    assert budget.snapshot().executions_started == 1


def test_budget_caps_runner_timeout_to_remaining_deadline(tmp_path: Path):
    """The shared deadline limits every started command's effective timeout."""
    now = [100.0]
    budget = ExecutionBudget(6, time_budget_seconds=2.5, clock=lambda: now[0])
    runner = _FakeRunner()

    budget.run_oracle(runner, tmp_path, kind=OracleExecutionKind.PROBE)

    assert runner.timeouts == [2.5]
    now[0] += 2.5
    with pytest.raises(BudgetExhaustedError) as error:
        budget.run_oracle(runner, tmp_path, kind=OracleExecutionKind.PROBE)
    assert error.value.reason is BudgetStopReason.TIME_LIMIT


def test_budget_does_not_start_when_deadline_passes_at_launch(tmp_path: Path):
    """A deadline crossing after preflight cannot consume an Oracle slot."""
    readings = iter((100.0, 100.0, 101.0, 101.0))
    budget = ExecutionBudget(6, time_budget_seconds=1, clock=lambda: next(readings))
    runner = _FakeRunner()

    with pytest.raises(BudgetExhaustedError) as error:
        budget.run_oracle(runner, tmp_path, kind=OracleExecutionKind.PROBE)

    assert error.value.reason is BudgetStopReason.TIME_LIMIT
    assert budget.snapshot().executions_started == 0
    assert runner.timeouts == []


def test_command_runner_allows_a_shorter_per_invocation_timeout(
    tmp_path: Path,
):
    """An optional call timeout preserves the runner default for older callers."""
    runner = CommandRunner(
        ("python", "-c", "import time; time.sleep(0.1)"), timeout_seconds=2
    )

    result = runner.run(tmp_path, timeout_seconds=0.01)

    assert result.timed_out
