"""Execution-verified reduction of direct module-level ``__main__`` guards."""

from __future__ import annotations

import ast
import hashlib
import io
import shutil
import tempfile
import tokenize
from collections import deque
from collections.abc import Collection
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter

from pyrepro.reproducer.budget import (
    BudgetExhaustedError,
    ExecutionBudget,
    OracleExecutionKind,
)
from pyrepro.reproducer.failure import (
    FailureMatchMode,
    FailureSignature,
    ReductionOutcome,
    classify_result,
)
from pyrepro.reproducer.reducer import (
    DEFAULT_IGNORED_DIRECTORY_NAMES,
    ProbeRecord,
    UnstableBaselineError,
    _probe_record,
    _python_files,
    _python_line_count,
    _run_oracle,
    _verify_final_workspace,
)
from pyrepro.reproducer.runner import CommandRunner
from pyrepro.reproducer.workspace import ReductionWorkspace


@dataclass(frozen=True)
class MainGuardCandidate:
    """One exact direct module-level main-guard source range."""

    file_path: str
    start_line: int
    end_line: int
    source_digest: str

    @property
    def source_span(self) -> int:
        """Return the inclusive physical source span."""
        return self.end_line - self.start_line + 1


@dataclass(frozen=True)
class MainGuardDiscovery:
    """Main-guard candidates discovered in one source file."""

    candidates: tuple[MainGuardCandidate, ...]
    skipped: bool


@dataclass(frozen=True)
class MainGuardReductionResult:
    """Verified metrics from bounded module-level main-guard reduction."""

    baseline_signature: FailureSignature
    initial_python_lines: int
    remaining_python_lines: int
    initial_candidates: int
    remaining_candidates: int
    candidate_attempts: int
    accepted_batches: int
    rejected_probes: int
    removed_guards: int
    executions: int
    source_unchanged: bool
    probe_records: tuple[ProbeRecord, ...]
    skipped_unparsable_files: tuple[str, ...]
    wall_clock_seconds: float
    budget_exhausted: bool = False


class GreedyMainGuardReducer:
    """Reduce direct module-level main guards using bounded batch splitting.

    The initial batch contains every current candidate. Rejected batches split
    deterministically. Accepted batches are applied to the active disposable
    workspace, then candidates are rediscovered before another probe so stale
    AST positions cannot be reused. A rejected edit exists only in a fresh
    probe copy and is therefore fully rolled back.
    """

    def __init__(
        self,
        runner: CommandRunner,
        match_mode: FailureMatchMode = FailureMatchMode.STRICT,
        ignored_directory_names: Collection[str] = DEFAULT_IGNORED_DIRECTORY_NAMES,
        *,
        max_probes: int | None = None,
    ) -> None:
        """Initialize a bounded main-guard reducer."""
        if max_probes is not None and max_probes < 0:
            raise ValueError("max_probes must not be negative")
        self.runner = runner
        self.match_mode = match_mode
        self.ignored_directory_names = frozenset(ignored_directory_names)
        self.max_probes = max_probes

    def reduce(
        self,
        workspace: ReductionWorkspace,
        baseline_signature: FailureSignature,
        *,
        budget: ExecutionBudget | None = None,
        verify_final: bool = True,
    ) -> MainGuardReductionResult:
        """Run bounded batch-and-split main-guard deletion."""
        started_at = perf_counter()
        initial_files = _python_files(workspace.root, self.ignored_directory_names)
        initial_python_lines = _python_line_count(initial_files)
        initial, skipped_paths = _discover_workspace_guards(
            workspace.root, initial_files
        )
        pending: deque[tuple[MainGuardCandidate, ...]] = deque()
        if initial:
            pending.append(initial)
        records: list[ProbeRecord] = []
        accepted = 0
        budget_exhausted = False

        while pending and (self.max_probes is None or len(records) < self.max_probes):
            if budget is not None and not budget.can_start_probe():
                budget_exhausted = True
                break
            batch = pending.popleft()
            try:
                outcome, record = self._probe_batch(
                    workspace.root, batch, baseline_signature, budget
                )
            except BudgetExhaustedError:
                budget_exhausted = True
                break
            records.append(record)
            if outcome is ReductionOutcome.SAME_FAILURE:
                _remove_main_guard_batch(workspace.root, batch)
                accepted += 1
                pending.clear()
                current, skipped = _discover_workspace_guards(
                    workspace.root,
                    _python_files(workspace.root, self.ignored_directory_names),
                )
                skipped_paths.update(skipped)
                if current:
                    pending.append(current)
            elif len(batch) > 1:
                midpoint = len(batch) // 2
                pending.appendleft(batch[midpoint:])
                pending.appendleft(batch[:midpoint])

        final_executions = 0
        if verify_final and not budget_exhausted:
            outcome = _verify_final_workspace(
                self.runner,
                workspace.root,
                baseline_signature,
                self.match_mode,
                budget,
            )
            final_executions = 1
            if outcome is not ReductionOutcome.SAME_FAILURE:
                raise UnstableBaselineError(
                    "final module-level main-guard verification did not match baseline"
                )
        remaining_files = _python_files(workspace.root, self.ignored_directory_names)
        remaining, skipped = _discover_workspace_guards(workspace.root, remaining_files)
        skipped_paths.update(skipped)
        return MainGuardReductionResult(
            baseline_signature=baseline_signature,
            initial_python_lines=initial_python_lines,
            remaining_python_lines=_python_line_count(remaining_files),
            initial_candidates=len(initial),
            remaining_candidates=len(remaining),
            candidate_attempts=len(records),
            accepted_batches=accepted,
            rejected_probes=len(records) - accepted,
            removed_guards=len(initial) - len(remaining),
            executions=len(records) + final_executions,
            source_unchanged=workspace.source_is_unchanged(),
            probe_records=tuple(records),
            skipped_unparsable_files=tuple(sorted(skipped_paths)),
            wall_clock_seconds=perf_counter() - started_at,
            budget_exhausted=budget_exhausted,
        )

    def _probe_batch(
        self,
        workspace_root: Path,
        batch: tuple[MainGuardCandidate, ...],
        baseline_signature: FailureSignature,
        budget: ExecutionBudget | None,
    ) -> tuple[ReductionOutcome, ProbeRecord]:
        """Run one main-guard batch in an isolated disposable workspace."""
        if budget is not None:
            budget.ensure_can_start(OracleExecutionKind.PROBE)
        with tempfile.TemporaryDirectory(prefix="pyrepro-main-guard-probe-") as name:
            probe_root = Path(name) / "project"
            shutil.copytree(workspace_root, probe_root)
            _remove_main_guard_batch(probe_root, batch)
            started_at = perf_counter()
            result = _run_oracle(
                self.runner, probe_root, budget, OracleExecutionKind.PROBE
            )
            duration = perf_counter() - started_at
            outcome = classify_result(
                result, baseline_signature, probe_root, self.match_mode
            )
            return outcome, _probe_record(
                "main_guard",
                tuple(Path(candidate.file_path) for candidate in batch),
                result,
                outcome,
                outcome is ReductionOutcome.SAME_FAILURE,
                duration,
                probe_root,
                candidate_python_lines=_python_line_count(
                    _python_files(probe_root, self.ignored_directory_names)
                ),
                candidate_descriptions=tuple(
                    f"{candidate.file_path}:{candidate.start_line}-"
                    f"{candidate.end_line}:main_guard:span={candidate.source_span}"
                    for candidate in batch
                ),
                candidate_rolled_back=outcome is not ReductionOutcome.SAME_FAILURE,
            )


def discover_main_guards(path: Path, workspace_root: Path) -> MainGuardDiscovery:
    """Discover direct module-level exact ``__main__`` guard statements."""
    try:
        content, _encoding = _read_source(path)
        tree = ast.parse(content, filename=str(path))
    except (OSError, SyntaxError, UnicodeError):
        return MainGuardDiscovery((), skipped=True)
    relative = path.relative_to(workspace_root).as_posix()
    candidates: list[MainGuardCandidate] = []
    for statement in tree.body:
        if not isinstance(statement, ast.If) or not _is_main_guard_test(statement.test):
            continue
        if statement.end_lineno is None:
            continue
        source = _source_span_text(content, statement.lineno, statement.end_lineno)
        candidates.append(
            MainGuardCandidate(
                file_path=relative,
                start_line=statement.lineno,
                end_line=statement.end_lineno,
                source_digest=hashlib.sha256(source.encode("utf-8")).hexdigest(),
            )
        )
    return MainGuardDiscovery(tuple(candidates), skipped=False)


def _is_main_guard_test(test: ast.expr) -> bool:
    """Return whether a test is one exact ``__name__ == "__main__"`` form."""
    if (
        not isinstance(test, ast.Compare)
        or len(test.ops) != 1
        or not isinstance(test.ops[0], ast.Eq)
        or len(test.comparators) != 1
    ):
        return False
    left = test.left
    right = test.comparators[0]
    return (_is_name_dunder(left) and _is_main_literal(right)) or (
        _is_main_literal(left) and _is_name_dunder(right)
    )


def _is_name_dunder(node: ast.expr) -> bool:
    return isinstance(node, ast.Name) and node.id == "__name__"


def _is_main_literal(node: ast.expr) -> bool:
    return isinstance(node, ast.Constant) and node.value == "__main__"


def _remove_main_guard_batch(root: Path, batch: Collection[MainGuardCandidate]) -> None:
    """Delete whole current guard statements, including header-line comments."""
    by_path: dict[str, list[MainGuardCandidate]] = {}
    for candidate in batch:
        by_path.setdefault(candidate.file_path, []).append(candidate)
    for relative, candidates in by_path.items():
        path = root / relative
        content, encoding = _read_source(path)
        lines = content.splitlines(keepends=True)
        for candidate in sorted(
            candidates, key=lambda item: item.start_line, reverse=True
        ):
            _validate_current_candidate(path, content, candidate)
            del lines[candidate.start_line - 1 : candidate.end_line]
        updated = "".join(lines)
        try:
            ast.parse(updated, filename=str(path))
        except SyntaxError as error:
            raise ValueError(
                f"main-guard edit produced invalid syntax in {path}"
            ) from error
        path.write_bytes(updated.encode(encoding))


def _validate_current_candidate(
    path: Path, content: str, candidate: MainGuardCandidate
) -> None:
    """Reject a stale candidate before applying its recorded source range."""
    tree = ast.parse(content, filename=str(path))
    for statement in tree.body:
        if (
            isinstance(statement, ast.If)
            and statement.lineno == candidate.start_line
            and statement.end_lineno == candidate.end_line
            and _is_main_guard_test(statement.test)
        ):
            source = _source_span_text(content, statement.lineno, statement.end_lineno)
            digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
            if digest == candidate.source_digest:
                return
    raise ValueError(f"stale or missing main-guard candidate in {path}")


def _discover_workspace_guards(
    workspace_root: Path, paths: Collection[Path]
) -> tuple[tuple[MainGuardCandidate, ...], set[str]]:
    """Discover current guards and any source paths that could not parse."""
    candidates: list[MainGuardCandidate] = []
    skipped_paths: set[str] = set()
    for path in paths:
        discovery = discover_main_guards(path, workspace_root)
        candidates.extend(discovery.candidates)
        if discovery.skipped:
            skipped_paths.add(path.relative_to(workspace_root).as_posix())
    return tuple(candidates), skipped_paths


def _read_source(path: Path) -> tuple[str, str]:
    """Read source without normalizing its declared encoding or newlines."""
    data = path.read_bytes()
    encoding, _ = tokenize.detect_encoding(io.BytesIO(data).readline)
    return data.decode(encoding), encoding


def _source_span_text(content: str, start_line: int, end_line: int) -> str:
    """Return inclusive source lines without normalizing newline sequences."""
    return "".join(content.splitlines(keepends=True)[start_line - 1 : end_line])
