"""Global execution and deadline accounting for opt-in Fast Mode."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from time import monotonic

from pyrepro.reproducer.runner import CommandRunner, ExecutionResult


class OracleExecutionKind(str, Enum):
    """Classify a budgeted Oracle command by its reserved purpose."""

    BASELINE = "baseline"
    PROBE = "probe"
    FINAL_VERIFICATION = "final_verification"


class BudgetStopReason(str, Enum):
    """Explain why a new budgeted Oracle command cannot start."""

    EXECUTION_RESERVE = "execution_reserve"
    EXECUTION_LIMIT = "execution_limit"
    FINAL_VERIFICATION_LIMIT = "final_verification_limit"
    TIME_LIMIT = "time_limit"


class BudgetExhaustedError(RuntimeError):
    """Raised when Fast Mode must stop before starting an Oracle command."""

    def __init__(self, reason: BudgetStopReason) -> None:
        """Store the structured reason for the controlled stop."""
        self.reason = reason
        super().__init__(f"execution budget exhausted: {reason.value}")


@dataclass(frozen=True)
class BudgetSnapshot:
    """Immutable observable state of an `ExecutionBudget`.

    Attributes:
        max_oracle_executions: Configured global command-start limit.
        executions_started: Commands already started through the budget.
        final_verifications_started: Started commands using reserved final slots.
        remaining_executions: Unused command-start slots.
        remaining_seconds: Remaining deadline time, or `None` when unbounded.
    """

    max_oracle_executions: int
    executions_started: int
    final_verifications_started: int
    remaining_executions: int
    remaining_seconds: float | None


class ExecutionBudget:
    """Control Fast-Mode Oracle starts with shared count and time limits.

    Three command slots are reserved for final independent verification. The
    class deliberately does not decide whether a reducer accepts a candidate;
    callers use it only at the single Oracle-command boundary.

    Args:
        max_oracle_executions: Global maximum number of commands that may start.
        time_budget_seconds: Optional monotonic wall-clock deadline from creation.
        baseline_runs: Commands required to establish a stable baseline.
        final_verification_reserve: Command slots held for final verification.
        clock: Monotonic clock injection point used by tests.

    Raises:
        ValueError: If a configured limit is not meaningful.
    """

    def __init__(
        self,
        max_oracle_executions: int,
        *,
        time_budget_seconds: float | None = None,
        baseline_runs: int = 3,
        final_verification_reserve: int = 3,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        """Create one shared budget for a complete Fast-Mode run."""
        if baseline_runs <= 0:
            raise ValueError("baseline_runs must be positive")
        if final_verification_reserve <= 0:
            raise ValueError("final_verification_reserve must be positive")
        minimum_executions = baseline_runs + final_verification_reserve
        if max_oracle_executions < minimum_executions:
            raise ValueError(
                "max_oracle_executions must cover baseline and final verification"
            )
        if time_budget_seconds is not None and time_budget_seconds <= 0:
            raise ValueError("time_budget_seconds must be positive when supplied")
        self.max_oracle_executions = max_oracle_executions
        self.time_budget_seconds = time_budget_seconds
        self.baseline_runs = baseline_runs
        self.final_verification_reserve = final_verification_reserve
        self._clock = clock
        self._started_at = clock()
        self._executions_started = 0
        self._final_verifications_started = 0

    def remaining_executions(self) -> int:
        """Return unused command-start slots."""
        return self.max_oracle_executions - self._executions_started

    def remaining_seconds(self) -> float | None:
        """Return remaining monotonic deadline time, if configured."""
        if self.time_budget_seconds is None:
            return None
        return max(0.0, self.time_budget_seconds - (self._clock() - self._started_at))

    def snapshot(self) -> BudgetSnapshot:
        """Return current counters without changing budget state."""
        return BudgetSnapshot(
            max_oracle_executions=self.max_oracle_executions,
            executions_started=self._executions_started,
            final_verifications_started=self._final_verifications_started,
            remaining_executions=self.remaining_executions(),
            remaining_seconds=self.remaining_seconds(),
        )

    def can_start_probe(self) -> bool:
        """Return whether an ordinary probe can retain final reserved slots."""
        return self._start_reason(OracleExecutionKind.PROBE) is None

    def can_start_final_verification(self) -> bool:
        """Return whether one reserved final-verification command can start."""
        return self._start_reason(OracleExecutionKind.FINAL_VERIFICATION) is None

    def ensure_can_start(self, kind: OracleExecutionKind) -> None:
        """Raise a structured stop before a caller mutates a probe workspace."""
        reason = self._start_reason(kind)
        if reason is not None:
            raise BudgetExhaustedError(reason)

    def run_oracle(
        self,
        runner: CommandRunner,
        working_directory: Path,
        *,
        kind: OracleExecutionKind,
    ) -> ExecutionResult:
        """Start one Oracle command under this budget.

        The count is consumed immediately before invoking the runner, so a
        command that times out or otherwise fails still consumes one execution.
        """
        self.ensure_can_start(kind)
        effective_timeout = self._effective_timeout(runner.timeout_seconds)
        if effective_timeout <= 0:
            raise BudgetExhaustedError(BudgetStopReason.TIME_LIMIT)
        self._executions_started += 1
        if kind is OracleExecutionKind.FINAL_VERIFICATION:
            self._final_verifications_started += 1
        return runner.run(working_directory, timeout_seconds=effective_timeout)

    def _start_reason(self, kind: OracleExecutionKind) -> BudgetStopReason | None:
        if self.remaining_seconds() == 0.0:
            return BudgetStopReason.TIME_LIMIT
        remaining = self.remaining_executions()
        if kind in (OracleExecutionKind.BASELINE, OracleExecutionKind.PROBE):
            if remaining <= self.final_verification_reserve:
                return BudgetStopReason.EXECUTION_RESERVE
        else:
            if remaining <= 0:
                return BudgetStopReason.EXECUTION_LIMIT
            if self._final_verifications_started >= self.final_verification_reserve:
                return BudgetStopReason.FINAL_VERIFICATION_LIMIT
        return None

    def _effective_timeout(self, runner_timeout: float) -> float:
        remaining = self.remaining_seconds()
        if remaining is None:
            return runner_timeout
        return min(runner_timeout, remaining)
