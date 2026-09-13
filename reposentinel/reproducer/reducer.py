"""Greedily remove Python files while preserving a stable failure signature."""

from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from reposentinel.reproducer.failure import (
    FailureSignature,
    ReductionOutcome,
    classify_result,
)
from reposentinel.reproducer.runner import CommandRunner
from reposentinel.reproducer.workspace import ReductionWorkspace


class UnstableBaselineError(RuntimeError):
    """Raised when the P0 baseline is not a stable uncaught Python failure."""


@dataclass(frozen=True)
class FileDecision:
    """Record one candidate-file deletion decision.

    Attributes:
        path: Repository-relative Python file considered for deletion.
        outcome: Result produced after temporarily deleting the file.
        removed: Whether the deletion preserved the baseline failure.
    """

    path: str
    outcome: ReductionOutcome
    removed: bool


@dataclass(frozen=True)
class ReductionResult:
    """Verified result of one greedy file-reduction run.

    Attributes:
        baseline_signature: Stable failure required throughout reduction.
        baseline_runs: Number of successful baseline executions.
        initial_python_files: Python-file count before deletion attempts.
        remaining_python_files: Python-file count after accepted deletions.
        executions: Total command executions, including baseline and final checks.
        decisions: Ordered decisions for each considered Python file.
        source_unchanged: Whether the protected source tree retained its digest.
    """

    baseline_signature: FailureSignature
    baseline_runs: int
    initial_python_files: int
    remaining_python_files: int
    executions: int
    decisions: tuple[FileDecision, ...]
    source_unchanged: bool


class GreedyFileReducer:
    """Remove individual Python files when the complete baseline failure remains.

    Args:
        runner: Command runner used for all baseline and candidate executions.
        baseline_runs: Number of equal baseline signatures required before deletion.
    """

    def __init__(self, runner: CommandRunner, baseline_runs: int = 3) -> None:
        """Initialize the reducer.

        Args:
            runner: Command runner used to evaluate candidates.
            baseline_runs: Positive number of matching baseline executions.

        Raises:
            ValueError: If baseline_runs is not positive.
        """
        if baseline_runs <= 0:
            raise ValueError("baseline_runs must be positive")
        self.runner = runner
        self.baseline_runs = baseline_runs

    def reduce(self, workspace: ReductionWorkspace) -> ReductionResult:
        """Run the P0 greedy file-reduction loop in an active workspace.

        Args:
            workspace: Active disposable project copy to mutate.

        Returns:
            Verified reduction result.

        Raises:
            UnstableBaselineError: If baseline or final verification is not stable.
        """
        baseline_signature, executions = self._establish_baseline(workspace.root)
        candidates = _python_files(workspace.root)
        decisions: list[FileDecision] = []

        with tempfile.TemporaryDirectory(
            prefix="reposentinel-reducer-backups-"
        ) as name:
            backup_root = Path(name)
            for candidate in candidates:
                decision, candidate_executions = self._try_remove(
                    workspace.root, candidate, backup_root, baseline_signature
                )
                decisions.append(decision)
                executions += candidate_executions

        final_result = self.runner.run(workspace.root)
        executions += 1
        final_outcome = classify_result(
            final_result, baseline_signature, workspace.root
        )
        if final_outcome is not ReductionOutcome.SAME_FAILURE:
            raise UnstableBaselineError(
                "final reduction verification did not match baseline"
            )

        return ReductionResult(
            baseline_signature=baseline_signature,
            baseline_runs=self.baseline_runs,
            initial_python_files=len(candidates),
            remaining_python_files=len(_python_files(workspace.root)),
            executions=executions,
            decisions=tuple(decisions),
            source_unchanged=workspace.source_is_unchanged(),
        )

    def _establish_baseline(self, workspace_root: Path) -> tuple[FailureSignature, int]:
        signatures: list[FailureSignature] = []
        for _ in range(self.baseline_runs):
            result = self.runner.run(workspace_root)
            signature = FailureSignature.from_result(result, workspace_root)
            if signature is None:
                raise UnstableBaselineError(
                    "baseline is not an uncaught Python failure"
                )
            signatures.append(signature)
        if len(set(signatures)) != 1:
            raise UnstableBaselineError("baseline failure signature is unstable")
        return signatures[0], self.baseline_runs

    def _try_remove(
        self,
        workspace_root: Path,
        candidate: Path,
        backup_root: Path,
        baseline_signature: FailureSignature,
    ) -> tuple[FileDecision, int]:
        relative = candidate.relative_to(workspace_root)
        backup = backup_root / relative
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(candidate, backup)
        candidate.unlink()

        result = self.runner.run(workspace_root)
        outcome = classify_result(result, baseline_signature, workspace_root)
        removed = outcome is ReductionOutcome.SAME_FAILURE
        if not removed:
            shutil.copy2(backup, candidate)
        return FileDecision(relative.as_posix(), outcome, removed), 1


def format_reduction_summary(result: ReductionResult) -> str:
    """Format a concise human-readable P0 reduction report.

    Args:
        result: Verified reduction result.

    Returns:
        Multi-line reduction summary.
    """
    lines = [
        "Baseline",
        "--------",
        result.baseline_signature.describe(),
        f"Stable: {result.baseline_runs}/{result.baseline_runs}",
        "",
        "Reduction",
        "---------",
    ]
    for decision in result.decisions:
        action = "REMOVE" if decision.removed else "KEEP"
        lines.append(f"{decision.path:<30} {action:<6} {decision.outcome.value}")
    lines.extend(
        [
            "",
            "Result",
            "------",
            f"Python files: {result.initial_python_files} -> "
            f"{result.remaining_python_files}",
            f"Executions: {result.executions}",
            f"Original modified: {'no' if result.source_unchanged else 'yes'}",
            "Final verification: SAME_FAILURE",
        ]
    )
    return "\n".join(lines)


def _python_files(root: Path) -> tuple[Path, ...]:
    return tuple(
        sorted(
            (path for path in root.rglob("*.py") if path.is_file()),
            key=lambda path: path.relative_to(root).as_posix(),
        )
    )
