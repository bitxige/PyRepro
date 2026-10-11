"""Verify a staged Fast-Mode workspace before publishing it as a reproducer."""

from __future__ import annotations

import ctypes
import errno
import os
import shutil
import sys
import tempfile
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from pyrepro.reproducer.budget import (
    BudgetExhaustedError,
    BudgetSnapshot,
    ExecutionBudget,
    OracleExecutionKind,
)
from pyrepro.reproducer.failure import (
    FailureMatchMode,
    FailureSignature,
    ReductionOutcome,
    classify_result,
)
from pyrepro.reproducer.runner import CommandRunner
from pyrepro.reproducer.workspace import ReductionWorkspace

_AT_FDCWD = -100
_RENAME_NOREPLACE = 1


class FastModeTerminalState(str, Enum):
    """Terminal outcomes for a Fast-Mode reduction and publication attempt."""

    COMPLETED = "completed"
    BUDGET_EXHAUSTED_VERIFIED = "budget_exhausted_verified"
    BUDGET_EXHAUSTED_UNVERIFIED = "budget_exhausted_unverified"
    FINAL_VERIFICATION_FAILED = "final_verification_failed"
    BASELINE_FAILED = "baseline_failed"
    SOURCE_CHANGED = "source_changed"
    RUNTIME_ERROR = "runtime_error"


@dataclass(frozen=True)
class FinalVerificationAttempt:
    """Observed result of one independent staging verification execution.

    Attributes:
        outcome: Classification against the established baseline, or ``None``
            when an Oracle command did not start.
        signature: Parsed signature from the actual command result, if present.
        return_code: Process exit code, or ``None`` after a timeout.
        timed_out: Whether the command timed out.
    """

    outcome: ReductionOutcome | None
    signature: FailureSignature | None
    return_code: int | None
    timed_out: bool


@dataclass(frozen=True)
class PublishingResult:
    """Structured result of staging verification and optional publication.

    Attributes:
        state: Final Fast-Mode state for this publishing attempt.
        output_path: Published verified output, or ``None`` when no official
            output was created.
        verification_attempts: Actual independent staging executions.
        source_unchanged: Whether the protected source remained unchanged.
        budget: Snapshot after the publishing attempt.
        error_message: Operational failure detail, when applicable.
    """

    state: FastModeTerminalState
    output_path: Path | None
    verification_attempts: tuple[FinalVerificationAttempt, ...]
    source_unchanged: bool
    budget: BudgetSnapshot
    error_message: str | None = None

    @property
    def verified(self) -> bool:
        """Return whether an official, independently verified output exists."""
        return self.state in {
            FastModeTerminalState.COMPLETED,
            FastModeTerminalState.BUDGET_EXHAUSTED_VERIFIED,
        }


def verify_and_publish(
    workspace: ReductionWorkspace,
    runner: CommandRunner,
    baseline_signature: FailureSignature,
    match_mode: FailureMatchMode,
    destination: Path,
    budget: ExecutionBudget,
    *,
    search_budget_exhausted: bool,
) -> PublishingResult:
    """Independently verify a staged workspace and atomically publish it.

    The current workspace is copied to a sibling staging directory. Exactly
    three final-verification commands are attempted through the shared budget.
    A destination is created only after all three retain the baseline failure
    and the source digest remains unchanged. Any unpublished staging directory
    is removed before returning.

    Args:
        workspace: Active workspace containing only already accepted changes.
        runner: Trusted argv runner used for final verification.
        baseline_signature: Stable failure signature established before search.
        match_mode: Failure identity required for final verification.
        destination: New directory to receive the verified reproducer.
        budget: Shared Fast-Mode budget with final slots reserved.
        search_budget_exhausted: Whether earlier reduction stopped for budget.

    Returns:
        Structured terminal state. Only verified states expose ``output_path``.

    Raises:
        ValueError: If the destination is invalid before staging begins.
    """
    output = _validate_destination(destination, workspace.source_root)
    attempts: list[FinalVerificationAttempt] = []
    staging: Path | None = None
    published = False

    try:
        if not workspace.source_is_unchanged():
            return _result(
                FastModeTerminalState.SOURCE_CHANGED,
                None,
                attempts,
                workspace,
                budget,
            )

        try:
            staging = Path(
                tempfile.mkdtemp(prefix=f".{output.name}.staging-", dir=output.parent)
            )
            shutil.copytree(workspace.root, staging, dirs_exist_ok=True)
        except OSError as error:
            return _with_source_precedence(
                FastModeTerminalState.RUNTIME_ERROR,
                attempts,
                workspace,
                budget,
                str(error),
            )

        for _ in range(3):
            try:
                execution = budget.run_oracle(
                    runner, staging, kind=OracleExecutionKind.FINAL_VERIFICATION
                )
            except BudgetExhaustedError as error:
                return _with_source_precedence(
                    FastModeTerminalState.BUDGET_EXHAUSTED_UNVERIFIED,
                    attempts,
                    workspace,
                    budget,
                    str(error),
                )
            except (OSError, ValueError) as error:
                return _with_source_precedence(
                    FastModeTerminalState.RUNTIME_ERROR,
                    attempts,
                    workspace,
                    budget,
                    str(error),
                )

            outcome = classify_result(
                execution, baseline_signature, staging, match_mode
            )
            attempts.append(
                FinalVerificationAttempt(
                    outcome=outcome,
                    signature=FailureSignature.from_result(execution, staging),
                    return_code=execution.return_code,
                    timed_out=execution.timed_out,
                )
            )
            if outcome is not ReductionOutcome.SAME_FAILURE:
                return _with_source_precedence(
                    FastModeTerminalState.FINAL_VERIFICATION_FAILED,
                    attempts,
                    workspace,
                    budget,
                )

        if not workspace.source_is_unchanged():
            return _result(
                FastModeTerminalState.SOURCE_CHANGED,
                None,
                attempts,
                workspace,
                budget,
            )
        try:
            _publish_staging(staging, output)
        except OSError as error:
            return _with_source_precedence(
                FastModeTerminalState.RUNTIME_ERROR,
                attempts,
                workspace,
                budget,
                str(error),
            )
        published = True
        state = (
            FastModeTerminalState.BUDGET_EXHAUSTED_VERIFIED
            if search_budget_exhausted
            else FastModeTerminalState.COMPLETED
        )
        return _result(state, output, attempts, workspace, budget)
    finally:
        if staging is not None and not published:
            shutil.rmtree(staging, ignore_errors=True)


def _validate_destination(destination: Path, source_root: Path) -> Path:
    """Validate one new output directory outside the protected source tree."""
    output = destination.expanduser().resolve()
    try:
        output.relative_to(source_root)
    except ValueError:
        pass
    else:
        raise ValueError("output directory must be outside the source root")
    if output.exists():
        raise ValueError(f"output directory already exists: {output}")
    if not output.parent.is_dir():
        raise ValueError(f"output parent directory does not exist: {output.parent}")
    return output


def _publish_staging(staging: Path, output: Path) -> None:
    """Atomically rename a staged directory without replacing an existing path.

    ``renameat2(..., RENAME_NOREPLACE)`` performs the existence check and
    directory move in one kernel operation. Fast Mode intentionally fails on
    systems that cannot provide this no-clobber guarantee instead of degrading
    to a check-then-``rename`` sequence.

    Args:
        staging: Existing sibling staging directory.
        output: Non-existing final destination in the same parent directory.

    Raises:
        OSError: If the platform or filesystem cannot provide a no-clobber
            atomic move, or if the destination has appeared concurrently.
    """
    if not sys.platform.startswith("linux"):
        raise OSError(
            errno.ENOTSUP,
            "atomic no-clobber directory publication requires Linux renameat2",
            str(output),
        )
    libc = ctypes.CDLL(None, use_errno=True)
    try:
        renameat2 = libc.renameat2
    except AttributeError as error:
        raise OSError(
            errno.ENOSYS,
            "atomic no-clobber directory publication requires renameat2",
            str(output),
        ) from error
    renameat2.argtypes = (
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    )
    renameat2.restype = ctypes.c_int
    if (
        renameat2(
            _AT_FDCWD,
            os.fsencode(staging),
            _AT_FDCWD,
            os.fsencode(output),
            _RENAME_NOREPLACE,
        )
        != 0
    ):
        error_number = ctypes.get_errno()
        raise OSError(error_number, os.strerror(error_number), str(output))


def _with_source_precedence(
    state: FastModeTerminalState,
    attempts: list[FinalVerificationAttempt],
    workspace: ReductionWorkspace,
    budget: ExecutionBudget,
    error_message: str | None = None,
) -> PublishingResult:
    """Return a failure result while preserving source-integrity precedence."""
    if not workspace.source_is_unchanged():
        state = FastModeTerminalState.SOURCE_CHANGED
        error_message = None
    return _result(state, None, attempts, workspace, budget, error_message)


def _result(
    state: FastModeTerminalState,
    output_path: Path | None,
    attempts: list[FinalVerificationAttempt],
    workspace: ReductionWorkspace,
    budget: ExecutionBudget,
    error_message: str | None = None,
) -> PublishingResult:
    """Construct one immutable publishing result from current observations."""
    return PublishingResult(
        state=state,
        output_path=output_path,
        verification_attempts=tuple(attempts),
        source_unchanged=workspace.source_is_unchanged(),
        budget=budget.snapshot(),
        error_message=error_message,
    )
