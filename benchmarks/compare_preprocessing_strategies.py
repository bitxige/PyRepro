"""Compare blind and preprocessing-first reduction on one trusted project.

Run from the PyRepro repository root, for example:

    python benchmarks/compare_preprocessing_strategies.py PROJECT \
      --pytest-node tests/test_example.py::test_failure -- \
      python run_target.py

The driver writes its machine-readable comparison to stdout. It runs trusted
developer-selected argv commands in disposable workspaces only; it is not an
execution sandbox and does not modify the supplied source project.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from time import perf_counter

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from pyrepro.reproducer.failure import (  # noqa: E402
    FailureMatchMode,
    FailureSignature,
    ReductionOutcome,
    classify_result,
)
from pyrepro.reproducer.preprocessing import PreprocessingFirstReducer  # noqa: E402
from pyrepro.reproducer.reducer import (  # noqa: E402
    DEFAULT_IGNORED_DIRECTORY_NAMES,
    GreedyFileReducer,
    _python_files,
    _python_line_count,
)
from pyrepro.reproducer.runner import CommandRunner  # noqa: E402
from pyrepro.reproducer.workspace import ReductionWorkspace, tree_digest  # noqa: E402


@dataclass(frozen=True)
class GitProvenance:
    """Best-effort Git identity for a benchmark input or the PyRepro checkout."""

    commit: str | None
    dirty: bool | None


@dataclass(frozen=True)
class IndependentVerification:
    """One observed post-reduction command result."""

    outcome: str
    failure_signature: dict[str, str] | None
    return_code: int | None
    timed_out: bool


@dataclass(frozen=True)
class StrategyComparison:
    """Metrics and observed outcome for one benchmark strategy."""

    name: str
    status: str
    error_type: str | None
    error_message: str | None
    max_import_probes: int | None
    max_coarse_probes: int | None
    initial_python_files: int | None
    initial_python_lines: int | None
    remaining_python_files: int | None
    remaining_python_lines: int | None
    baseline_failure_signature: dict[str, str] | None
    phase_executions: dict[str, int]
    phase_probe_counts: dict[str, int]
    phase_accepted_probes: dict[str, int]
    reducer_oracle_executions: int | None
    independent_verification_executions: int
    total_oracle_executions: int | None
    reducer_wall_clock_seconds: float | None
    complete_wall_clock_seconds: float
    independent_verifications: tuple[IndependentVerification, ...]
    final_verification_passed: bool
    source_unchanged: bool


def main(argv: list[str] | None = None) -> int:
    """Run the three fixed comparison configurations and print JSON metrics."""
    args, command = _parse_args(argv)
    source = args.source.expanduser().resolve()
    if not source.is_dir():
        raise ValueError(f"source project is not a directory: {source}")
    if not command:
        raise ValueError("a reproduction argv command is required after --")

    runner = CommandRunner(command, timeout_seconds=args.timeout_seconds)
    source_provenance = _git_provenance(source)
    pyrepro_provenance = _git_provenance(REPOSITORY_ROOT)
    source_snapshot = tree_digest(source)
    comparisons: list[StrategyComparison] = []
    snapshot_valid = True
    for name in (
        "blind_greedy",
        "import_then_greedy",
        "import_coarse_then_greedy",
    ):
        if not snapshot_valid:
            comparisons.append(
                _skipped_strategy(
                    name,
                    args,
                    "source snapshot changed during an earlier strategy",
                )
            )
            continue
        comparison = _run_strategy(name, source, runner, args, source_snapshot)
        comparisons.append(comparison)
        snapshot_valid = comparison.source_unchanged
    print(
        json.dumps(
            {
                "provenance": {
                    "source": {
                        "path": str(source),
                        **asdict(source_provenance),
                    },
                    "pyrepro": {
                        "path": str(REPOSITORY_ROOT),
                        **asdict(pyrepro_provenance),
                    },
                    "python_executable": sys.executable,
                    "python_version": sys.version,
                    "failure_match_mode": FailureMatchMode.STRICT.value,
                    "reproduction_command": list(command),
                    "timeout_seconds": args.timeout_seconds,
                },
                "pytest_node": args.pytest_node,
                "strategies": [asdict(comparison) for comparison in comparisons],
                "all_strategies_passed": all(
                    comparison.status == "passed" for comparison in comparisons
                ),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return int(any(comparison.status != "passed" for comparison in comparisons))


def _parse_args(argv: list[str] | None) -> tuple[argparse.Namespace, tuple[str, ...]]:
    """Parse the intentionally narrow, developer-facing benchmark interface."""
    values = tuple(sys.argv[1:] if argv is None else argv)
    try:
        separator = values.index("--")
    except ValueError as error:
        raise ValueError("a reproduction argv command is required after --") from error
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--pytest-node", required=True)
    parser.add_argument("--expect")
    parser.add_argument("--timeout-seconds", type=float, default=15.0)
    parser.add_argument("--import-probes", type=int, default=16)
    parser.add_argument("--coarse-probes", type=int, default=16)
    return parser.parse_args(values[:separator]), values[separator + 1 :]


def _run_strategy(
    name: str,
    source: Path,
    runner: CommandRunner,
    args: argparse.Namespace,
    source_snapshot: str,
) -> StrategyComparison:
    """Reduce one disposable workspace and verify the final failure three times."""
    started = perf_counter()
    import_budget, coarse_budget = _strategy_budgets(name, args)
    if not _source_matches(source, source_snapshot):
        return _failed_strategy(
            name,
            import_budget,
            coarse_budget,
            (),
            None,
            source,
            source_snapshot,
            started,
            RuntimeError("source snapshot mismatch before strategy execution"),
        )
    initial_files = _python_files(source, DEFAULT_IGNORED_DIRECTORY_NAMES)
    initial_lines = _python_line_count(initial_files)
    try:
        with ReductionWorkspace(source) as workspace:
            if name == "blind_greedy":
                result = GreedyFileReducer(
                    runner,
                    expected_text=args.expect,
                    match_mode=FailureMatchMode.STRICT,
                ).reduce(workspace)
                baseline = result.baseline_signature
                phase_executions = {"greedy": result.executions}
                records = result.probe_records
                reducer_executions = result.executions
                reducer_wall_clock = result.wall_clock_seconds
            else:
                result = PreprocessingFirstReducer(
                    runner,
                    args.pytest_node,
                    expected_text=args.expect,
                    match_mode=FailureMatchMode.STRICT,
                    max_import_probes=import_budget,
                    max_coarse_probes=coarse_budget,
                ).reduce(workspace)
                baseline = result.import_pruning.baseline_signature
                phase_executions = {
                    "import_pruning": result.import_pruning.executions,
                    "greedy": result.file_reduction.executions,
                }
                if result.coarse_reduction is not None:
                    phase_executions.update(
                        Counter(
                            record.phase
                            for record in result.coarse_reduction.probe_records
                        )
                    )
                records = result.probe_records
                reducer_executions = result.executions
                reducer_wall_clock = result.wall_clock_seconds

            if sum(phase_executions.values()) != reducer_executions:
                raise RuntimeError("phase execution counts do not match reducer total")
            verifications = _independent_verifications(runner, workspace.root, baseline)
            remaining_files = _python_files(
                workspace.root, DEFAULT_IGNORED_DIRECTORY_NAMES
            )
            remaining_lines = _python_line_count(remaining_files)
            verification_passed = all(
                verification.outcome == ReductionOutcome.SAME_FAILURE.value
                for verification in verifications
            )
            source_unchanged = workspace.source_is_unchanged() and _source_matches(
                source, source_snapshot
            )
    except Exception as error:  # Benchmark failure must be emitted as data.
        return _failed_strategy(
            name,
            import_budget,
            coarse_budget,
            initial_files,
            initial_lines,
            source,
            source_snapshot,
            started,
            error,
        )

    phase_counts = Counter(record.phase for record in records)
    accepted_counts = Counter(record.phase for record in records if record.accepted)
    status = "passed" if verification_passed and source_unchanged else "failed"
    error_message = None
    if not verification_passed:
        error_message = "independent final verification did not match baseline"
    elif not source_unchanged:
        error_message = "source project changed during benchmark strategy"
    return StrategyComparison(
        name=name,
        status=status,
        error_type=None if status == "passed" else "VerificationError",
        error_message=error_message,
        max_import_probes=import_budget,
        max_coarse_probes=coarse_budget,
        initial_python_files=len(initial_files),
        initial_python_lines=initial_lines,
        remaining_python_files=len(remaining_files),
        remaining_python_lines=remaining_lines,
        baseline_failure_signature=asdict(baseline),
        phase_executions=dict(sorted(phase_executions.items())),
        phase_probe_counts=dict(sorted(phase_counts.items())),
        phase_accepted_probes=dict(sorted(accepted_counts.items())),
        reducer_oracle_executions=reducer_executions,
        independent_verification_executions=len(verifications),
        total_oracle_executions=reducer_executions + len(verifications),
        reducer_wall_clock_seconds=reducer_wall_clock,
        complete_wall_clock_seconds=perf_counter() - started,
        independent_verifications=verifications,
        final_verification_passed=verification_passed,
        source_unchanged=source_unchanged,
    )


def _strategy_budgets(
    name: str, args: argparse.Namespace
) -> tuple[int | None, int | None]:
    """Return the actual preprocessing budgets for one fixed strategy."""
    if name == "blind_greedy":
        return None, None
    if name == "import_then_greedy":
        return args.import_probes, 0
    if name == "import_coarse_then_greedy":
        return args.import_probes, args.coarse_probes
    raise ValueError(f"unknown benchmark strategy: {name}")


def _independent_verifications(
    runner: CommandRunner,
    workspace_root: Path,
    baseline: FailureSignature,
) -> tuple[IndependentVerification, ...]:
    """Observe three independent final executions without altering reducer metrics."""
    observations: list[IndependentVerification] = []
    for _ in range(3):
        execution = runner.run(workspace_root)
        outcome = classify_result(
            execution,
            baseline,
            workspace_root,
            FailureMatchMode.STRICT,
        )
        signature = FailureSignature.from_result(execution, workspace_root)
        observations.append(
            IndependentVerification(
                outcome=outcome.value,
                failure_signature=None if signature is None else asdict(signature),
                return_code=execution.return_code,
                timed_out=execution.timed_out,
            )
        )
    return tuple(observations)


def _failed_strategy(
    name: str,
    import_budget: int | None,
    coarse_budget: int | None,
    initial_files: tuple[Path, ...],
    initial_lines: int | None,
    source: Path,
    source_snapshot: str,
    started: float,
    error: Exception,
) -> StrategyComparison:
    """Return a structured failed strategy result without fabricating metrics."""
    source_unchanged = _source_matches(source, source_snapshot)
    return StrategyComparison(
        name=name,
        status="failed",
        error_type=type(error).__name__,
        error_message=str(error),
        max_import_probes=import_budget,
        max_coarse_probes=coarse_budget,
        initial_python_files=None if initial_lines is None else len(initial_files),
        initial_python_lines=initial_lines,
        remaining_python_files=None,
        remaining_python_lines=None,
        baseline_failure_signature=None,
        phase_executions={},
        phase_probe_counts={},
        phase_accepted_probes={},
        reducer_oracle_executions=None,
        independent_verification_executions=0,
        total_oracle_executions=None,
        reducer_wall_clock_seconds=None,
        complete_wall_clock_seconds=perf_counter() - started,
        independent_verifications=(),
        final_verification_passed=False,
        source_unchanged=source_unchanged,
    )


def _skipped_strategy(
    name: str,
    args: argparse.Namespace,
    reason: str,
) -> StrategyComparison:
    """Record a strategy skipped after the shared source snapshot became invalid."""
    import_budget, coarse_budget = _strategy_budgets(name, args)
    return StrategyComparison(
        name=name,
        status="skipped",
        error_type="SourceSnapshotMismatch",
        error_message=reason,
        max_import_probes=import_budget,
        max_coarse_probes=coarse_budget,
        initial_python_files=None,
        initial_python_lines=None,
        remaining_python_files=None,
        remaining_python_lines=None,
        baseline_failure_signature=None,
        phase_executions={},
        phase_probe_counts={},
        phase_accepted_probes={},
        reducer_oracle_executions=None,
        independent_verification_executions=0,
        total_oracle_executions=None,
        reducer_wall_clock_seconds=None,
        complete_wall_clock_seconds=0.0,
        independent_verifications=(),
        final_verification_passed=False,
        source_unchanged=False,
    )


def _source_matches(source: Path, source_snapshot: str) -> bool:
    """Return whether ``source`` still has the benchmark's initial digest."""
    try:
        return source.is_dir() and tree_digest(source) == source_snapshot
    except OSError:
        return False


def _git_provenance(path: Path) -> GitProvenance:
    """Return commit and dirty state when ``path`` belongs to a Git worktree."""
    commit = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"],
        capture_output=True,
        check=False,
        text=True,
    )
    if commit.returncode != 0:
        return GitProvenance(commit=None, dirty=None)
    status = subprocess.run(
        ["git", "-C", str(path), "status", "--porcelain"],
        capture_output=True,
        check=False,
        text=True,
    )
    return GitProvenance(
        commit=commit.stdout.strip(),
        dirty=None if status.returncode != 0 else bool(status.stdout.strip()),
    )


if __name__ == "__main__":
    raise SystemExit(main())
