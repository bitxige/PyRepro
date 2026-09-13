"""Execution-verified greedy and grouped file reducers."""

from __future__ import annotations

import shutil
import tempfile
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter

from pyrepro.reproducer.failure import (
    FailureSignature,
    ReductionOutcome,
    classify_result,
)
from pyrepro.reproducer.runner import CommandRunner
from pyrepro.reproducer.workspace import ReductionWorkspace

DEFAULT_IGNORED_DIRECTORY_NAMES = frozenset(
    {
        ".git",
        ".pytest_cache",
        ".venv",
        "__pycache__",
        "build",
        "checkpoints",
        "data",
        "dist",
        "env",
        "models",
        "node_modules",
        "output",
        "outputs",
        "venv",
    }
)


class UnstableBaselineError(RuntimeError):
    """Raised when reduction cannot preserve a stable baseline failure."""


@dataclass(frozen=True)
class FileDecision:
    """Record one greedy candidate-file deletion decision.

    Attributes:
        path: Repository-relative Python file considered for deletion.
        outcome: Result produced after temporarily deleting the file.
        removed: Whether the deletion preserved the baseline failure.
    """

    path: str
    outcome: ReductionOutcome
    removed: bool


@dataclass(frozen=True)
class ProbeDecision:
    """Record one grouped, cleanup, or minimality oracle probe.

    Attributes:
        phase: Reduction phase that issued the probe.
        retained_paths: Candidate paths retained for the probe.
        outcome: Oracle result for the probe workspace.
        accepted: Whether the result changed the retained candidate set.
    """

    phase: str
    retained_paths: tuple[str, ...]
    outcome: ReductionOutcome
    accepted: bool


@dataclass(frozen=True)
class ReductionResult:
    """Verified result of one file-reduction run.

    Attributes:
        strategy: Name of the reduction strategy used.
        baseline_signature: Stable failure required throughout reduction.
        baseline_runs: Number of successful baseline executions.
        initial_python_files: Eligible Python-file count before reduction.
        remaining_python_files: Eligible Python-file count after reduction.
        initial_python_lines: Physical eligible Python-source lines before reduction.
        remaining_python_lines: Physical eligible Python-source lines after reduction.
        executions: All oracle executions, including baseline and final checks.
        candidate_attempts: Candidate probes excluding baseline and final checks.
        accepted_probes: Candidate probes that changed the retained set.
        rejected_probes: Candidate probes that did not preserve the failure.
        removed_candidate_files: Eligible files absent from the final workspace.
        wall_clock_seconds: Duration from first baseline run through final check.
        decisions: Per-file greedy decisions, when the strategy emits them.
        probes: Grouped, cleanup, and minimality probe decisions.
        source_unchanged: Whether the protected source tree retained its digest.
    """

    strategy: str
    baseline_signature: FailureSignature
    baseline_runs: int
    initial_python_files: int
    remaining_python_files: int
    initial_python_lines: int
    remaining_python_lines: int
    executions: int
    candidate_attempts: int
    accepted_probes: int
    rejected_probes: int
    removed_candidate_files: int
    wall_clock_seconds: float
    decisions: tuple[FileDecision, ...]
    probes: tuple[ProbeDecision, ...]
    source_unchanged: bool


class GreedyFileReducer:
    """Remove individual Python files when the complete baseline failure remains.

    Args:
        runner: Command runner used for all baseline and candidate executions.
        baseline_runs: Number of equal baseline signatures required before deletion.
        expected_text: Optional text that must occur in the baseline signature.
        ignored_directory_names: Directory names excluded from deletion candidates.
    """

    def __init__(
        self,
        runner: CommandRunner,
        baseline_runs: int = 3,
        expected_text: str | None = None,
        ignored_directory_names: Collection[str] = DEFAULT_IGNORED_DIRECTORY_NAMES,
    ) -> None:
        """Initialize the greedy reducer.

        Raises:
            ValueError: If baseline_runs is not positive or expected_text is blank.
        """
        self.runner = runner
        self.baseline_runs = _validate_baseline_runs(baseline_runs)
        self.expected_text = _normalize_expected_text(expected_text)
        self.ignored_directory_names = frozenset(ignored_directory_names)

    def reduce(self, workspace: ReductionWorkspace) -> ReductionResult:
        """Run greedy file reduction in an active disposable workspace.

        Args:
            workspace: Active disposable project copy to mutate.

        Returns:
            Verified greedy reduction result.

        Raises:
            UnstableBaselineError: If baseline or final verification is unstable.
        """
        started_at = perf_counter()
        baseline_signature, executions = _establish_baseline(
            self.runner,
            workspace.root,
            self.baseline_runs,
            self.expected_text,
        )
        candidates = _python_files(workspace.root, self.ignored_directory_names)
        initial_lines = _python_line_count(candidates)
        decisions: list[FileDecision] = []
        probes: list[ProbeDecision] = []
        accepted_probes = 0

        with tempfile.TemporaryDirectory(prefix="pyrepro-reducer-backups-") as name:
            backup_root = Path(name)
            for candidate in candidates:
                decision, candidate_executions = self._try_remove(
                    workspace.root, candidate, backup_root, baseline_signature
                )
                decisions.append(decision)
                executions += candidate_executions
                accepted_probes += int(decision.removed)
                probes.append(
                    ProbeDecision(
                        phase="greedy",
                        retained_paths=(),
                        outcome=decision.outcome,
                        accepted=decision.removed,
                    )
                )

        final_outcome = _verify_final_workspace(
            self.runner, workspace.root, baseline_signature
        )
        executions += 1
        if final_outcome is not ReductionOutcome.SAME_FAILURE:
            raise UnstableBaselineError(
                "final reduction verification did not match baseline"
            )
        remaining = _python_files(workspace.root, self.ignored_directory_names)

        return ReductionResult(
            strategy="greedy",
            baseline_signature=baseline_signature,
            baseline_runs=self.baseline_runs,
            initial_python_files=len(candidates),
            remaining_python_files=len(remaining),
            initial_python_lines=initial_lines,
            remaining_python_lines=_python_line_count(remaining),
            executions=executions,
            candidate_attempts=len(decisions),
            accepted_probes=accepted_probes,
            rejected_probes=len(decisions) - accepted_probes,
            removed_candidate_files=len(candidates) - len(remaining),
            wall_clock_seconds=perf_counter() - started_at,
            decisions=tuple(decisions),
            probes=tuple(probes),
            source_unchanged=workspace.source_is_unchanged(),
        )

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


class DdminFileReducer:
    """Use grouped ddmin-style probes before 1-minimal file cleanup.

    Args:
        runner: Command runner used for every baseline and candidate execution.
        baseline_runs: Number of equal baseline signatures required before search.
        expected_text: Optional text that must occur in the baseline signature.
        ignored_directory_names: Directory names excluded from deletion candidates.
    """

    def __init__(
        self,
        runner: CommandRunner,
        baseline_runs: int = 3,
        expected_text: str | None = None,
        ignored_directory_names: Collection[str] = DEFAULT_IGNORED_DIRECTORY_NAMES,
    ) -> None:
        """Initialize the grouped reducer.

        Raises:
            ValueError: If baseline_runs is not positive or expected_text is blank.
        """
        self.runner = runner
        self.baseline_runs = _validate_baseline_runs(baseline_runs)
        self.expected_text = _normalize_expected_text(expected_text)
        self.ignored_directory_names = frozenset(ignored_directory_names)

    def reduce(self, workspace: ReductionWorkspace) -> ReductionResult:
        """Run grouped search, greedy cleanup, and 1-minimal verification.

        Args:
            workspace: Active disposable source copy used as the clean probe base.

        Returns:
            Verified grouped reduction result.

        Raises:
            UnstableBaselineError: If baseline or final verification is unstable.
        """
        started_at = perf_counter()
        with tempfile.TemporaryDirectory(prefix="pyrepro-ddmin-template-") as name:
            template_root = Path(name) / "project"
            shutil.copytree(workspace.root, template_root)
            baseline_signature, executions = _establish_baseline(
                self.runner,
                workspace.root,
                self.baseline_runs,
                self.expected_text,
            )
            candidates = _python_files(template_root, self.ignored_directory_names)
            initial_lines = _python_line_count(candidates)
            retained = tuple(candidates)
            probes: list[ProbeDecision] = []

            retained, grouped_probes = self._grouped_search(
                template_root, candidates, retained, baseline_signature
            )
            probes.extend(grouped_probes)
            retained, cleanup_probes = self._greedy_cleanup(
                template_root, candidates, retained, baseline_signature
            )
            probes.extend(cleanup_probes)
            minimality_probes = self._verify_one_minimal(
                template_root, candidates, retained, baseline_signature
            )
            probes.extend(minimality_probes)

            _restore_workspace_from_template(workspace.root, template_root)
            _apply_retained_candidates(
                workspace.root, candidates, retained, template_root
            )
            final_outcome = _verify_final_workspace(
                self.runner, workspace.root, baseline_signature
            )
            if final_outcome is not ReductionOutcome.SAME_FAILURE:
                raise UnstableBaselineError(
                    "final reduction verification did not match baseline"
                )
            executions += len(probes) + 1
            remaining = _python_files(workspace.root, self.ignored_directory_names)
            accepted_probes = sum(probe.accepted for probe in probes)

        return ReductionResult(
            strategy="ddmin",
            baseline_signature=baseline_signature,
            baseline_runs=self.baseline_runs,
            initial_python_files=len(candidates),
            remaining_python_files=len(remaining),
            initial_python_lines=initial_lines,
            remaining_python_lines=_python_line_count(remaining),
            executions=executions,
            candidate_attempts=len(probes),
            accepted_probes=accepted_probes,
            rejected_probes=len(probes) - accepted_probes,
            removed_candidate_files=len(candidates) - len(remaining),
            wall_clock_seconds=perf_counter() - started_at,
            decisions=(),
            probes=tuple(probes),
            source_unchanged=workspace.source_is_unchanged(),
        )

    def _grouped_search(
        self,
        workspace_root: Path,
        candidates: Sequence[Path],
        retained: tuple[Path, ...],
        baseline_signature: FailureSignature,
    ) -> tuple[tuple[Path, ...], list[ProbeDecision]]:
        granularity = 2
        probes: list[ProbeDecision] = []
        while len(retained) >= 2:
            groups = _partition(retained, granularity)
            accepted_retained: tuple[Path, ...] | None = None
            for group in groups:
                outcome = self._probe_retained(
                    workspace_root, candidates, group, baseline_signature
                )
                accepted = outcome is ReductionOutcome.SAME_FAILURE
                probes.append(_probe_decision("subset", group, outcome, accepted))
                if accepted:
                    accepted_retained = group
                    break
            if accepted_retained is None:
                for group in groups:
                    complement = tuple(path for path in retained if path not in group)
                    outcome = self._probe_retained(
                        workspace_root, candidates, complement, baseline_signature
                    )
                    accepted = outcome is ReductionOutcome.SAME_FAILURE
                    probes.append(
                        _probe_decision("complement", complement, outcome, accepted)
                    )
                    if accepted:
                        accepted_retained = complement
                        break
            if accepted_retained is not None:
                retained = accepted_retained
                granularity = max(2, granularity - 1)
            elif granularity >= len(retained):
                break
            else:
                granularity = min(len(retained), granularity * 2)
        return retained, probes

    def _greedy_cleanup(
        self,
        workspace_root: Path,
        candidates: Sequence[Path],
        retained: tuple[Path, ...],
        baseline_signature: FailureSignature,
    ) -> tuple[tuple[Path, ...], list[ProbeDecision]]:
        probes: list[ProbeDecision] = []
        for candidate in tuple(retained):
            if candidate not in retained:
                continue
            proposed = tuple(path for path in retained if path != candidate)
            outcome = self._probe_retained(
                workspace_root, candidates, proposed, baseline_signature
            )
            accepted = outcome is ReductionOutcome.SAME_FAILURE
            probes.append(_probe_decision("cleanup", proposed, outcome, accepted))
            if accepted:
                retained = proposed
        return retained, probes

    def _verify_one_minimal(
        self,
        workspace_root: Path,
        candidates: Sequence[Path],
        retained: tuple[Path, ...],
        baseline_signature: FailureSignature,
    ) -> list[ProbeDecision]:
        probes: list[ProbeDecision] = []
        for candidate in retained:
            proposed = tuple(path for path in retained if path != candidate)
            outcome = self._probe_retained(
                workspace_root, candidates, proposed, baseline_signature
            )
            probe = _probe_decision("minimality", proposed, outcome, False)
            probes.append(probe)
            if outcome is ReductionOutcome.SAME_FAILURE:
                raise UnstableBaselineError("final grouped reduction is not 1-minimal")
        return probes

    def _probe_retained(
        self,
        workspace_root: Path,
        candidates: Sequence[Path],
        retained: Sequence[Path],
        baseline_signature: FailureSignature,
    ) -> ReductionOutcome:
        retained_set = set(retained)
        with tempfile.TemporaryDirectory(prefix="pyrepro-ddmin-probe-") as name:
            probe_root = Path(name) / "project"
            shutil.copytree(workspace_root, probe_root)
            _apply_retained_candidates(
                probe_root, candidates, retained_set, workspace_root
            )
            result = self.runner.run(probe_root)
            return classify_result(result, baseline_signature, probe_root)


def format_reduction_summary(result: ReductionResult) -> str:
    """Format a concise human-readable reduction report.

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
        f"Strategy: {result.strategy}",
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
            f"Python LOC: {result.initial_python_lines} -> "
            f"{result.remaining_python_lines}",
            f"Oracle executions: {result.executions}",
            f"Candidate attempts: {result.candidate_attempts}",
            f"Accepted probes: {result.accepted_probes}",
            f"Rejected probes: {result.rejected_probes}",
            f"Removed candidate files: {result.removed_candidate_files}",
            f"Wall-clock seconds: {result.wall_clock_seconds:.3f}",
            f"Original modified: {'no' if result.source_unchanged else 'yes'}",
            "Final verification: SAME_FAILURE",
        ]
    )
    return "\n".join(lines)


def _validate_baseline_runs(baseline_runs: int) -> int:
    if baseline_runs <= 0:
        raise ValueError("baseline_runs must be positive")
    return baseline_runs


def _normalize_expected_text(expected_text: str | None) -> str | None:
    if expected_text is None:
        return None
    normalized = " ".join(expected_text.split())
    if not normalized:
        raise ValueError("expected_text must not be blank")
    return normalized


def _establish_baseline(
    runner: CommandRunner,
    workspace_root: Path,
    baseline_runs: int,
    expected_text: str | None,
) -> tuple[FailureSignature, int]:
    signatures: list[FailureSignature] = []
    for _ in range(baseline_runs):
        result = runner.run(workspace_root)
        signature = FailureSignature.from_result(result, workspace_root)
        if signature is None:
            raise UnstableBaselineError("baseline is not an uncaught Python failure")
        signatures.append(signature)
    if len(set(signatures)) != 1:
        raise UnstableBaselineError("baseline failure signature is unstable")
    baseline = signatures[0]
    if expected_text is not None and expected_text not in baseline.describe():
        raise UnstableBaselineError(
            f"baseline failure does not contain expected text: {expected_text!r}"
        )
    return baseline, baseline_runs


def _verify_final_workspace(
    runner: CommandRunner,
    workspace_root: Path,
    baseline_signature: FailureSignature,
) -> ReductionOutcome:
    result = runner.run(workspace_root)
    return classify_result(result, baseline_signature, workspace_root)


def _apply_retained_candidates(
    target_root: Path,
    candidates: Sequence[Path],
    retained: Collection[Path],
    candidate_root: Path | None = None,
) -> None:
    source_root = candidate_root or target_root
    retained_set = set(retained)
    for candidate in candidates:
        if candidate in retained_set:
            continue
        relative = candidate.relative_to(source_root)
        target = target_root / relative
        if target.exists():
            target.unlink()


def _restore_workspace_from_template(workspace_root: Path, template_root: Path) -> None:
    shutil.rmtree(workspace_root)
    shutil.copytree(template_root, workspace_root)


def _probe_decision(
    phase: str,
    retained: Sequence[Path],
    outcome: ReductionOutcome,
    accepted: bool,
) -> ProbeDecision:
    return ProbeDecision(
        phase=phase,
        retained_paths=tuple(path.as_posix() for path in retained),
        outcome=outcome,
        accepted=accepted,
    )


def _partition(paths: Sequence[Path], granularity: int) -> tuple[tuple[Path, ...], ...]:
    group_count = min(granularity, len(paths))
    base_size, remainder = divmod(len(paths), group_count)
    groups: list[tuple[Path, ...]] = []
    start = 0
    for index in range(group_count):
        size = base_size + int(index < remainder)
        groups.append(tuple(paths[start : start + size]))
        start += size
    return tuple(groups)


def _python_files(
    root: Path, ignored_directory_names: Collection[str]
) -> tuple[Path, ...]:
    return tuple(
        sorted(
            (
                path
                for path in root.rglob("*.py")
                if path.is_file()
                and not path.is_symlink()
                and not _is_in_ignored_directory(path, root, ignored_directory_names)
            ),
            key=lambda path: path.relative_to(root).as_posix(),
        )
    )


def _python_line_count(paths: Collection[Path]) -> int:
    return sum(_physical_line_count(path.read_bytes()) for path in paths)


def _physical_line_count(content: bytes) -> int:
    if not content:
        return 0
    return content.count(b"\n") + int(not content.endswith(b"\n"))


def _is_in_ignored_directory(
    path: Path, root: Path, ignored_directory_names: Collection[str]
) -> bool:
    relative_parts = path.relative_to(root).parts[:-1]
    return any(part in ignored_directory_names for part in relative_parts)
