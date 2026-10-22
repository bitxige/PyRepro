"""Discover and greedily remove bounded Python source symbols."""

from __future__ import annotations

import ast
import shutil
import tempfile
import tokenize
from collections.abc import Collection
from dataclasses import dataclass
from enum import Enum
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
class SymbolCandidate:
    """A supported Python symbol represented by a source span.

    Attributes:
        file_path: Workspace-relative source path containing the symbol.
        qualified_name: Symbol name, qualified with its direct class name for
            method candidates.
        kind: One of ``function``, ``async_function``, ``class``, ``method``,
            or ``async_method``.
        start_line: Inclusive first source line, including decorators.
        end_line: Inclusive final source line.
    """

    file_path: str
    qualified_name: str
    kind: str
    start_line: int
    end_line: int

    @property
    def identity(self) -> tuple[str, str, str]:
        """Return the stable identity used to avoid repeated rejected probes."""
        return self.file_path, self.qualified_name, self.kind

    @property
    def source_span(self) -> int:
        """Return the inclusive source-line span used for candidate ordering."""
        return self.end_line - self.start_line + 1


class SymbolOrder(str, Enum):
    """Supported deterministic orderings for complete-symbol probes."""

    DISCOVERY = "discovery"
    SPAN_DESC = "span-desc"


class SymbolScope(str, Enum):
    """AST candidate domains supported by the concrete Symbol reducer."""

    TOP_LEVEL = "top-level"
    METHODS = "methods"


@dataclass(frozen=True)
class SymbolDiscovery:
    """Candidates discovered in one source file.

    Attributes:
        candidates: Module-level symbols available for greedy probing.
        skipped: Whether the file could not be parsed and was left unchanged.
    """

    candidates: tuple[SymbolCandidate, ...]
    skipped: bool


@dataclass(frozen=True)
class SymbolDecision:
    """Record one greedy complete-symbol deletion probe.

    Attributes:
        candidate: Symbol proposed for removal.
        outcome: Oracle result produced by the disposable probe.
        removed: Whether the candidate removal preserved the exact failure.
    """

    candidate: SymbolCandidate
    outcome: ReductionOutcome
    removed: bool


@dataclass(frozen=True)
class SymbolReductionResult:
    """Verified outcome of the P3 greedy symbol-reduction phase.

    Attributes:
        baseline_signature: Existing file-phase signature preserved by P3.
        initial_python_lines: Eligible Python LOC entering the symbol phase.
        remaining_python_lines: Eligible Python LOC after accepted removals.
        initial_symbols: Supported module-level candidate count before probing.
        remaining_symbols: Supported module-level candidate count after probing.
        executions: Symbol-phase oracle executions, including final verification.
        candidate_attempts: Number of symbol probes excluding final verification.
        accepted_removals: Probes accepted through ``SAME_FAILURE``.
        rejected_probes: Probes that did not preserve the exact signature.
        skipped_unparsable_files: Eligible files skipped because AST parsing failed.
        wall_clock_seconds: Duration of discovery, probes, and final verification.
        decisions: Ordered symbol probe decisions.
        source_unchanged: Whether the protected source tree retained its digest.
        probe_records: Optional telemetry for actual symbol probes.
        budget_exhausted: Whether Fast Mode stopped this stage before a probe.
    """

    baseline_signature: FailureSignature
    failure_match_mode: FailureMatchMode
    initial_python_lines: int
    remaining_python_lines: int
    initial_symbols: int
    remaining_symbols: int
    executions: int
    candidate_attempts: int
    accepted_removals: int
    rejected_probes: int
    skipped_unparsable_files: tuple[str, ...]
    wall_clock_seconds: float
    decisions: tuple[SymbolDecision, ...]
    source_unchanged: bool
    probe_records: tuple[ProbeRecord, ...] = ()
    budget_exhausted: bool = False


class GreedySymbolReducer:
    """Remove complete top-level symbols when the baseline failure remains.

    Args:
        runner: Command runner used for each disposable symbol probe.
        match_mode: Failure identity used for candidate acceptance.
        ignored_directory_names: Directory names excluded from P1-eligible files.
        max_probes: Optional maximum number of symbol probes. ``None`` leaves
            the established Standard Mode behavior unbounded.
        candidate_order: Deterministic ordering used to choose the next symbol.
        candidate_scope: AST domain used to discover candidates. ``METHODS`` is
            intentionally limited to direct methods of module-level classes.
    """

    def __init__(
        self,
        runner: CommandRunner,
        match_mode: FailureMatchMode = FailureMatchMode.STRICT,
        ignored_directory_names: Collection[str] = DEFAULT_IGNORED_DIRECTORY_NAMES,
        *,
        max_probes: int | None = None,
        candidate_order: SymbolOrder = SymbolOrder.DISCOVERY,
        candidate_scope: SymbolScope = SymbolScope.TOP_LEVEL,
    ) -> None:
        """Initialize the P3 greedy symbol reducer."""
        if max_probes is not None and max_probes < 0:
            raise ValueError("max_probes must not be negative")
        self.runner = runner
        self.match_mode = match_mode
        self.ignored_directory_names = frozenset(ignored_directory_names)
        self.max_probes = max_probes
        self.candidate_order = candidate_order
        self.candidate_scope = candidate_scope

    def reduce(
        self,
        workspace: ReductionWorkspace,
        baseline_signature: FailureSignature,
        *,
        budget: ExecutionBudget | None = None,
        verify_final: bool = True,
    ) -> SymbolReductionResult:
        """Greedily remove complete symbols from a verified file workspace.

        Args:
            workspace: Active disposable workspace after file-level reduction.
            baseline_signature: Exact failure signature established by file reduction.
            budget: Optional shared Fast-Mode Oracle budget.
            verify_final: Whether to run the normal single-run stage check.
                Fast Mode defers this check to Publisher's independent 3/3
                final verification.

        Returns:
            Verified symbol-phase result.

        Raises:
            UnstableBaselineError: If final verification does not preserve the
                established signature.
        """
        started_at = perf_counter()
        initial_files = _python_files(workspace.root, self.ignored_directory_names)
        initial_lines = _python_line_count(initial_files)
        initial_discovery, skipped_paths = _discover_workspace_symbols(
            workspace.root, initial_files, self.candidate_scope
        )
        initial_symbols = len(initial_discovery)
        rejected_identities: set[tuple[str, str, str]] = set()
        decisions: list[SymbolDecision] = []
        probe_records: list[ProbeRecord] = []
        budget_exhausted = False

        while self.max_probes is None or len(decisions) < self.max_probes:
            if budget is not None and not budget.can_start_probe():
                budget_exhausted = True
                break
            current_files = _python_files(workspace.root, self.ignored_directory_names)
            candidates, skipped = _discover_workspace_symbols(
                workspace.root, current_files, self.candidate_scope
            )
            skipped_paths.update(skipped)
            candidate = next(
                (
                    item
                    for item in _order_candidates(candidates, self.candidate_order)
                    if item.identity not in rejected_identities
                ),
                None,
            )
            if candidate is None:
                break

            try:
                outcome, probe_record = self._probe_candidate(
                    workspace.root, candidate, baseline_signature, budget
                )
            except BudgetExhaustedError:
                budget_exhausted = True
                break
            removed = outcome is ReductionOutcome.SAME_FAILURE
            decisions.append(SymbolDecision(candidate, outcome, removed))
            probe_records.append(probe_record)
            if removed:
                _remove_symbol_span(workspace.root / candidate.file_path, candidate)
            else:
                rejected_identities.add(candidate.identity)

        final_executions = 0
        if verify_final and not budget_exhausted:
            final_outcome = _verify_final_workspace(
                self.runner,
                workspace.root,
                baseline_signature,
                self.match_mode,
                budget,
            )
            final_executions = 1
            if final_outcome is not ReductionOutcome.SAME_FAILURE:
                raise UnstableBaselineError(
                    "final symbol reduction verification did not match baseline"
                )

        remaining_files = _python_files(workspace.root, self.ignored_directory_names)
        remaining_symbols, skipped = _discover_workspace_symbols(
            workspace.root, remaining_files, self.candidate_scope
        )
        skipped_paths.update(skipped)
        accepted_removals = sum(decision.removed for decision in decisions)

        return SymbolReductionResult(
            baseline_signature=baseline_signature,
            failure_match_mode=self.match_mode,
            initial_python_lines=initial_lines,
            remaining_python_lines=_python_line_count(remaining_files),
            initial_symbols=initial_symbols,
            remaining_symbols=len(remaining_symbols),
            executions=len(decisions) + final_executions,
            candidate_attempts=len(decisions),
            accepted_removals=accepted_removals,
            rejected_probes=len(decisions) - accepted_removals,
            skipped_unparsable_files=tuple(sorted(skipped_paths)),
            wall_clock_seconds=perf_counter() - started_at,
            decisions=tuple(decisions),
            source_unchanged=workspace.source_is_unchanged(),
            probe_records=tuple(probe_records),
            budget_exhausted=budget_exhausted,
        )

    def _probe_candidate(
        self,
        workspace_root: Path,
        candidate: SymbolCandidate,
        baseline_signature: FailureSignature,
        budget: ExecutionBudget | None,
    ) -> tuple[ReductionOutcome, ProbeRecord]:
        """Run one disposable source-span deletion through the shared Oracle."""
        if budget is not None:
            budget.ensure_can_start(OracleExecutionKind.PROBE)
        with tempfile.TemporaryDirectory(prefix="pyrepro-symbol-probe-") as name:
            probe_root = Path(name) / "project"
            shutil.copytree(workspace_root, probe_root)
            _remove_symbol_span(probe_root / candidate.file_path, candidate)
            started_at = perf_counter()
            result = _run_oracle(
                self.runner, probe_root, budget, OracleExecutionKind.PROBE
            )
            duration_seconds = perf_counter() - started_at
            outcome = classify_result(
                result, baseline_signature, probe_root, self.match_mode
            )
            return outcome, _probe_record(
                "symbol",
                (Path(candidate.file_path),),
                result,
                outcome,
                outcome is ReductionOutcome.SAME_FAILURE,
                duration_seconds,
                probe_root,
                candidate_python_lines=_python_line_count(
                    _python_files(probe_root, self.ignored_directory_names)
                ),
                candidate_descriptions=(
                    f"{candidate.file_path}:{candidate.qualified_name}:"
                    f"{candidate.start_line}-{candidate.end_line}:{candidate.kind}",
                ),
                candidate_rolled_back=outcome is not ReductionOutcome.SAME_FAILURE,
            )


def discover_symbols(
    path: Path,
    workspace_root: Path,
    candidate_scope: SymbolScope = SymbolScope.TOP_LEVEL,
) -> SymbolDiscovery:
    """Return supported current-source candidates from one eligible file.

    Args:
        path: Existing Python file in the current workspace.
        workspace_root: Root used to make candidate paths relative.
        candidate_scope: Candidate domain. Methods are direct methods of
            top-level classes only and are skipped if removal would empty the
            enclosing class body.

    Returns:
        Parsed candidates, or a skipped discovery when parsing fails.
    """
    try:
        with tokenize.open(path) as source:
            tree = ast.parse(source.read(), filename=str(path))
    except (OSError, SyntaxError, UnicodeError):
        return SymbolDiscovery((), skipped=True)

    relative = path.relative_to(workspace_root).as_posix()
    candidates: list[SymbolCandidate] = []
    if candidate_scope is SymbolScope.TOP_LEVEL:
        for node in tree.body:
            kind = _symbol_kind(node)
            if kind is not None:
                candidate = _candidate_from_node(relative, node, node.name, kind)
                if candidate is not None:
                    candidates.append(candidate)
    elif candidate_scope is SymbolScope.METHODS:
        for class_node in tree.body:
            if not isinstance(class_node, ast.ClassDef):
                continue
            for method in class_node.body:
                kind = _method_kind(method)
                if kind is None or len(class_node.body) <= 1:
                    continue
                candidate = _candidate_from_node(
                    relative,
                    method,
                    f"{class_node.name}.{method.name}",
                    kind,
                )
                if candidate is not None:
                    candidates.append(candidate)
    else:
        raise ValueError(f"unsupported symbol candidate scope: {candidate_scope}")
    return SymbolDiscovery(tuple(candidates), skipped=False)


def format_symbol_reduction_summary(result: SymbolReductionResult) -> str:
    """Format P3-specific metrics without obscuring the P2 file phase.

    Args:
        result: Verified symbol reduction result.

    Returns:
        Multi-line symbol-phase summary.
    """
    return "\n".join(
        [
            "Symbol reduction",
            "----------------",
            f"Python LOC: {result.initial_python_lines} -> "
            f"{result.remaining_python_lines}",
            f"Supported symbols: {result.initial_symbols} -> "
            f"{result.remaining_symbols}",
            f"Symbol oracle executions: {result.executions}",
            f"Symbol candidate attempts: {result.candidate_attempts}",
            f"Accepted symbol removals: {result.accepted_removals}",
            f"Rejected symbol probes: {result.rejected_probes}",
            f"Skipped unparsable files: {len(result.skipped_unparsable_files)}",
            f"Symbol wall-clock seconds: {result.wall_clock_seconds:.3f}",
            "Symbol final verification: SAME_FAILURE",
        ]
    )


def _discover_workspace_symbols(
    workspace_root: Path,
    paths: Collection[Path],
    candidate_scope: SymbolScope,
) -> tuple[tuple[SymbolCandidate, ...], set[str]]:
    candidates: list[SymbolCandidate] = []
    skipped_paths: set[str] = set()
    for path in paths:
        discovery = discover_symbols(path, workspace_root, candidate_scope)
        candidates.extend(discovery.candidates)
        if discovery.skipped:
            skipped_paths.add(path.relative_to(workspace_root).as_posix())
    return tuple(candidates), skipped_paths


def _order_candidates(
    candidates: Collection[SymbolCandidate], candidate_order: SymbolOrder
) -> tuple[SymbolCandidate, ...]:
    """Return candidates in their configured deterministic probe order."""
    if candidate_order is SymbolOrder.DISCOVERY:
        return tuple(candidates)
    if candidate_order is SymbolOrder.SPAN_DESC:
        return tuple(
            sorted(
                candidates,
                key=lambda candidate: (
                    -candidate.source_span,
                    candidate.file_path,
                    candidate.start_line,
                    candidate.end_line,
                    candidate.qualified_name,
                    candidate.kind,
                ),
            )
        )
    raise ValueError(f"unsupported symbol candidate order: {candidate_order}")


def _remove_symbol_span(path: Path, candidate: SymbolCandidate) -> None:
    with tokenize.open(path) as source:
        content = source.read()
        encoding = source.encoding
    lines = content.splitlines(keepends=True)
    del lines[candidate.start_line - 1 : candidate.end_line]
    path.write_text("".join(lines), encoding=encoding)


def _symbol_kind(node: ast.stmt) -> str | None:
    if isinstance(node, ast.FunctionDef):
        return "function"
    if isinstance(node, ast.AsyncFunctionDef):
        return "async_function"
    if isinstance(node, ast.ClassDef):
        return "class"
    return None


def _method_kind(node: ast.stmt) -> str | None:
    if isinstance(node, ast.FunctionDef):
        return "method"
    if isinstance(node, ast.AsyncFunctionDef):
        return "async_method"
    return None


def _candidate_from_node(
    file_path: str,
    node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef,
    qualified_name: str,
    kind: str,
) -> SymbolCandidate | None:
    """Build a candidate while retaining decorated source lines."""
    if node.end_lineno is None:
        return None
    start_line = min(
        (decorator.lineno for decorator in node.decorator_list), default=node.lineno
    )
    return SymbolCandidate(
        file_path=file_path,
        qualified_name=qualified_name,
        kind=kind,
        start_line=start_line,
        end_line=node.end_lineno,
    )
