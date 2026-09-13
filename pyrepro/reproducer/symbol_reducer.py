"""Discover and greedily remove complete Python source symbols."""

from __future__ import annotations

import ast
import shutil
import tempfile
import tokenize
from collections.abc import Collection
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter

from pyrepro.reproducer.failure import (
    FailureMatchMode,
    FailureSignature,
    ReductionOutcome,
    classify_result,
)
from pyrepro.reproducer.reducer import (
    DEFAULT_IGNORED_DIRECTORY_NAMES,
    UnstableBaselineError,
    _python_files,
    _python_line_count,
    _verify_final_workspace,
)
from pyrepro.reproducer.runner import CommandRunner
from pyrepro.reproducer.workspace import ReductionWorkspace


@dataclass(frozen=True)
class SymbolCandidate:
    """A complete module-level Python symbol represented by a source span.

    Attributes:
        file_path: Workspace-relative source path containing the symbol.
        qualified_name: Module-level symbol name.
        kind: One of ``function``, ``async_function``, or ``class``.
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


class GreedySymbolReducer:
    """Remove complete top-level symbols when the baseline failure remains.

    Args:
        runner: Command runner used for each disposable symbol probe.
        match_mode: Failure identity used for candidate acceptance.
        ignored_directory_names: Directory names excluded from P1-eligible files.
    """

    def __init__(
        self,
        runner: CommandRunner,
        match_mode: FailureMatchMode = FailureMatchMode.STRICT,
        ignored_directory_names: Collection[str] = DEFAULT_IGNORED_DIRECTORY_NAMES,
    ) -> None:
        """Initialize the P3 greedy symbol reducer."""
        self.runner = runner
        self.match_mode = match_mode
        self.ignored_directory_names = frozenset(ignored_directory_names)

    def reduce(
        self,
        workspace: ReductionWorkspace,
        baseline_signature: FailureSignature,
    ) -> SymbolReductionResult:
        """Greedily remove complete symbols from a verified file workspace.

        Args:
            workspace: Active disposable workspace after file-level reduction.
            baseline_signature: Exact failure signature established by file reduction.

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
            workspace.root, initial_files
        )
        initial_symbols = len(initial_discovery)
        rejected_identities: set[tuple[str, str, str]] = set()
        decisions: list[SymbolDecision] = []

        while True:
            current_files = _python_files(workspace.root, self.ignored_directory_names)
            candidates, skipped = _discover_workspace_symbols(
                workspace.root, current_files
            )
            skipped_paths.update(skipped)
            candidate = next(
                (
                    item
                    for item in candidates
                    if item.identity not in rejected_identities
                ),
                None,
            )
            if candidate is None:
                break

            outcome = self._probe_candidate(
                workspace.root, candidate, baseline_signature
            )
            removed = outcome is ReductionOutcome.SAME_FAILURE
            decisions.append(SymbolDecision(candidate, outcome, removed))
            if removed:
                _remove_symbol_span(workspace.root / candidate.file_path, candidate)
            else:
                rejected_identities.add(candidate.identity)

        final_outcome = _verify_final_workspace(
            self.runner,
            workspace.root,
            baseline_signature,
            self.match_mode,
        )
        if final_outcome is not ReductionOutcome.SAME_FAILURE:
            raise UnstableBaselineError(
                "final symbol reduction verification did not match baseline"
            )

        remaining_files = _python_files(workspace.root, self.ignored_directory_names)
        remaining_symbols, skipped = _discover_workspace_symbols(
            workspace.root, remaining_files
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
            executions=len(decisions) + 1,
            candidate_attempts=len(decisions),
            accepted_removals=accepted_removals,
            rejected_probes=len(decisions) - accepted_removals,
            skipped_unparsable_files=tuple(sorted(skipped_paths)),
            wall_clock_seconds=perf_counter() - started_at,
            decisions=tuple(decisions),
            source_unchanged=workspace.source_is_unchanged(),
        )

    def _probe_candidate(
        self,
        workspace_root: Path,
        candidate: SymbolCandidate,
        baseline_signature: FailureSignature,
    ) -> ReductionOutcome:
        with tempfile.TemporaryDirectory(prefix="pyrepro-symbol-probe-") as name:
            probe_root = Path(name) / "project"
            shutil.copytree(workspace_root, probe_root)
            _remove_symbol_span(probe_root / candidate.file_path, candidate)
            result = self.runner.run(probe_root)
            return classify_result(
                result, baseline_signature, probe_root, self.match_mode
            )


def discover_symbols(path: Path, workspace_root: Path) -> SymbolDiscovery:
    """Return complete supported module-level symbols from one current source file.

    Args:
        path: Existing Python file in the current workspace.
        workspace_root: Root used to make candidate paths relative.

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
    for node in tree.body:
        kind = _symbol_kind(node)
        if kind is None or node.end_lineno is None:
            continue
        decorators = getattr(node, "decorator_list", ())
        start_line = min(
            (decorator.lineno for decorator in decorators), default=node.lineno
        )
        candidates.append(
            SymbolCandidate(
                file_path=relative,
                qualified_name=node.name,
                kind=kind,
                start_line=start_line,
                end_line=node.end_lineno,
            )
        )
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
    workspace_root: Path, paths: Collection[Path]
) -> tuple[tuple[SymbolCandidate, ...], set[str]]:
    candidates: list[SymbolCandidate] = []
    skipped_paths: set[str] = set()
    for path in paths:
        discovery = discover_symbols(path, workspace_root)
        candidates.extend(discovery.candidates)
        if discovery.skipped:
            skipped_paths.add(path.relative_to(workspace_root).as_posix())
    return tuple(candidates), skipped_paths


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
