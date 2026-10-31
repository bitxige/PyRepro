"""Execution-verified reduction of conservative nested palette-list entries.

The reducer recognizes module-level direct ``Palette([...])`` bindings whose
first positional argument is a multiline, comment-free list of three-integer
tuples. Entries use current AST indices, not RGB values, so duplicate colours
remain independently reducible. Static structure only locates safe edits; the
strict runtime oracle decides every deletion.
"""

from __future__ import annotations

import ast
import hashlib
import io
import shutil
import tempfile
import tokenize
from collections import deque
from collections.abc import Collection
from dataclasses import dataclass, replace
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
from pyrepro.reproducer.list_entry_reducer import (
    _apply_ranges,
    _item_range,
    _line_starts,
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
class NestedPaletteCandidate:
    """A batch of current entries in one supported nested palette list."""

    file_path: str
    binding_name: str
    entry_indices: tuple[int, ...]
    source_digest: str
    source_span: int


@dataclass(frozen=True)
class NestedPaletteDiscovery:
    """Supported nested palette candidates discovered in one source file."""

    candidates: tuple[NestedPaletteCandidate, ...]
    skipped: bool


@dataclass(frozen=True)
class NestedPaletteReductionResult:
    """Verified metrics from bounded nested-palette entry reduction."""

    baseline_signature: FailureSignature
    initial_python_lines: int
    remaining_python_lines: int
    initial_candidates: int
    remaining_candidates: int
    candidate_attempts: int
    accepted_batches: int
    rejected_probes: int
    removed_entries: int
    executions: int
    source_unchanged: bool
    probe_records: tuple[ProbeRecord, ...]
    wall_clock_seconds: float
    budget_exhausted: bool = False


@dataclass(frozen=True)
class _PaletteList:
    """Current parsed facts needed to relocate one nested palette edit."""

    binding_name: str
    list_node: ast.List
    entries: tuple[ast.Tuple, ...]
    data: bytes
    encoding: str


class GreedyNestedPaletteReducer:
    """Reduce conservative nested ``Palette([...])`` entries with splitting."""

    def __init__(
        self,
        runner: CommandRunner,
        *,
        match_mode: FailureMatchMode = FailureMatchMode.STRICT,
        ignored_directory_names: Collection[str] = DEFAULT_IGNORED_DIRECTORY_NAMES,
        max_probes: int | None = None,
    ) -> None:
        """Initialize a bounded nested-palette reducer.

        Args:
            runner: Trusted command runner used only in disposable workspaces.
            match_mode: Failure-signature comparison mode for the oracle.
            ignored_directory_names: Directories excluded from LOC metrics.
            max_probes: Maximum reduction probes, excluding final verification.

        Raises:
            ValueError: If the limit is negative.
        """
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
    ) -> NestedPaletteReductionResult:
        """Run bounded batch-and-split nested-palette reduction."""
        started_at = perf_counter()
        initial_files = _python_files(workspace.root, self.ignored_directory_names)
        initial_python_lines = _python_line_count(initial_files)
        initial, skipped_paths = _discover_workspace(workspace.root, initial_files)
        initial_count = sum(len(item.entry_indices) for item in initial)
        pending: deque[NestedPaletteCandidate] = deque(initial)
        records: list[ProbeRecord] = []
        accepted = 0
        budget_exhausted = False

        while pending and (self.max_probes is None or len(records) < self.max_probes):
            if budget is not None and not budget.can_start_probe():
                budget_exhausted = True
                break
            requested = pending.popleft()
            palette = _find_palette(
                workspace.root / requested.file_path,
                workspace.root,
                requested.binding_name,
            )
            if palette is None:
                continue
            present = set(range(len(palette.entries)))
            indices = tuple(
                index for index in requested.entry_indices if index in present
            )
            if not indices:
                continue
            candidate = NestedPaletteCandidate(
                file_path=requested.file_path,
                binding_name=requested.binding_name,
                entry_indices=indices,
                source_digest=_palette_digest(palette),
                source_span=_source_span(palette.list_node),
            )
            try:
                outcome, record = self._probe_candidate(
                    workspace.root, candidate, baseline_signature, budget
                )
            except BudgetExhaustedError:
                budget_exhausted = True
                break
            records.append(record)
            if outcome is ReductionOutcome.SAME_FAILURE:
                _remove_palette_entries(workspace.root, candidate)
                accepted += 1
                pending.clear()
                current, skipped = _discover_workspace(
                    workspace.root,
                    _python_files(workspace.root, self.ignored_directory_names),
                )
                skipped_paths.update(skipped)
                pending.extend(current)
            elif len(indices) > 1:
                midpoint = len(indices) // 2
                pending.appendleft(replace(candidate, entry_indices=indices[midpoint:]))
                pending.appendleft(replace(candidate, entry_indices=indices[:midpoint]))

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
                    "final nested-palette verification did not match baseline"
                )
        remaining_files = _python_files(workspace.root, self.ignored_directory_names)
        remaining, skipped = _discover_workspace(workspace.root, remaining_files)
        skipped_paths.update(skipped)
        remaining_count = sum(len(item.entry_indices) for item in remaining)
        return NestedPaletteReductionResult(
            baseline_signature=baseline_signature,
            initial_python_lines=initial_python_lines,
            remaining_python_lines=_python_line_count(remaining_files),
            initial_candidates=initial_count,
            remaining_candidates=remaining_count,
            candidate_attempts=len(records),
            accepted_batches=accepted,
            rejected_probes=len(records) - accepted,
            removed_entries=initial_count - remaining_count,
            executions=len(records) + final_executions,
            source_unchanged=workspace.source_is_unchanged(),
            probe_records=tuple(records),
            wall_clock_seconds=perf_counter() - started_at,
            budget_exhausted=budget_exhausted,
        )

    def _probe_candidate(
        self,
        workspace_root: Path,
        candidate: NestedPaletteCandidate,
        baseline_signature: FailureSignature,
        budget: ExecutionBudget | None,
    ) -> tuple[ReductionOutcome, ProbeRecord]:
        """Run one entry batch in an isolated workspace copy."""
        if budget is not None:
            budget.ensure_can_start(OracleExecutionKind.PROBE)
        with tempfile.TemporaryDirectory(
            prefix="pyrepro-nested-palette-probe-"
        ) as name:
            probe_root = Path(name) / "project"
            shutil.copytree(workspace_root, probe_root)
            _remove_palette_entries(probe_root, candidate)
            started_at = perf_counter()
            execution = _run_oracle(
                self.runner, probe_root, budget, OracleExecutionKind.PROBE
            )
            duration = perf_counter() - started_at
            outcome = classify_result(
                execution, baseline_signature, probe_root, self.match_mode
            )
            return outcome, _probe_record(
                "nested_list_entry",
                (Path(candidate.file_path),),
                execution,
                outcome,
                outcome is ReductionOutcome.SAME_FAILURE,
                duration,
                probe_root,
                candidate_python_lines=_python_line_count(
                    _python_files(probe_root, self.ignored_directory_names)
                ),
                candidate_descriptions=(
                    f"{candidate.file_path}:{candidate.binding_name}:"
                    f"indices={candidate.entry_indices}:"
                    f"span={candidate.source_span}",
                ),
                candidate_rolled_back=outcome is not ReductionOutcome.SAME_FAILURE,
            )


def discover_nested_palette_entries(
    path: Path, workspace_root: Path
) -> NestedPaletteDiscovery:
    """Discover source-safe direct module-level ``Palette([...])`` bindings."""
    palettes = _supported_palettes(path, workspace_root)
    if palettes is None:
        return NestedPaletteDiscovery((), skipped=True)
    relative = path.relative_to(workspace_root).as_posix()
    return NestedPaletteDiscovery(
        tuple(
            NestedPaletteCandidate(
                file_path=relative,
                binding_name=palette.binding_name,
                entry_indices=tuple(range(len(palette.entries))),
                source_digest=_palette_digest(palette),
                source_span=_source_span(palette.list_node),
            )
            for palette in palettes
            if palette.entries
        ),
        skipped=False,
    )


def _find_palette(path: Path, root: Path, binding_name: str) -> _PaletteList | None:
    """Locate one current conservative nested palette list, if supported."""
    palettes = _supported_palettes(path, root)
    if palettes is None:
        return None
    return next((item for item in palettes if item.binding_name == binding_name), None)


def _discover_workspace(
    root: Path, paths: Collection[Path]
) -> tuple[tuple[NestedPaletteCandidate, ...], set[str]]:
    """Discover current palette candidates and source files that could not parse."""
    candidates: list[NestedPaletteCandidate] = []
    skipped_paths: set[str] = set()
    for path in paths:
        discovery = discover_nested_palette_entries(path, root)
        candidates.extend(discovery.candidates)
        if discovery.skipped:
            skipped_paths.add(path.relative_to(root).as_posix())
    return tuple(candidates), skipped_paths


def _supported_palettes(path: Path, root: Path) -> tuple[_PaletteList, ...] | None:
    """Return every unambiguous direct module-level palette list in one file."""
    del root
    try:
        data = path.read_bytes()
        encoding, _ = tokenize.detect_encoding(io.BytesIO(data).readline)
        content = data.decode(encoding)
        tree = ast.parse(content, filename=str(path))
        tokens = tuple(tokenize.generate_tokens(io.StringIO(content).readline))
    except (OSError, SyntaxError, UnicodeError, tokenize.TokenError):
        return None
    bindings: dict[str, list[ast.expr | None]] = {}
    for statement in tree.body:
        direct = _direct_binding(statement)
        if direct is not None:
            name, value = direct
            bindings.setdefault(name, []).append(value)
        else:
            for name in _assigned_names(statement):
                bindings.setdefault(name, []).append(None)
    palettes: list[_PaletteList] = []
    for name, values in bindings.items():
        if len(values) != 1:
            continue
        binding = values[0]
        if not isinstance(binding, ast.Call) or not _is_palette_call(binding):
            continue
        if not binding.args or not isinstance(binding.args[0], ast.List):
            continue
        list_node = binding.args[0]
        if list_node.end_lineno is None or list_node.lineno == list_node.end_lineno:
            continue
        if _unsafe_tokens(tokens, list_node.lineno, list_node.end_lineno):
            continue
        entries = _rgb_entries(list_node)
        if entries is not None:
            palettes.append(_PaletteList(name, list_node, entries, data, encoding))
    return tuple(palettes)


def _direct_binding(statement: ast.stmt) -> tuple[str, ast.expr] | None:
    """Return one exact module-level name binding and its assigned value."""
    if isinstance(statement, ast.Assign) and len(statement.targets) == 1:
        if isinstance(statement.targets[0], ast.Name):
            return statement.targets[0].id, statement.value
    if isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
        if statement.value is not None:
            return statement.target.id, statement.value
    return None


def _assigned_names(statement: ast.stmt) -> tuple[str, ...]:
    """Return direct names rebound by unsupported module-level assignments."""
    targets: tuple[ast.expr, ...]
    if isinstance(statement, ast.Assign):
        targets = tuple(statement.targets)
    elif isinstance(statement, ast.AnnAssign | ast.AugAssign):
        targets = (statement.target,)
    else:
        return ()
    return tuple(target.id for target in targets if isinstance(target, ast.Name))


def _is_palette_call(node: ast.Call) -> bool:
    """Return whether the constructor is the direct name ``Palette``."""
    return isinstance(node.func, ast.Name) and node.func.id == "Palette"


def _rgb_entries(node: ast.List) -> tuple[ast.Tuple, ...] | None:
    """Return exactly three-integer tuple nodes, preserving duplicates."""
    entries: list[ast.Tuple] = []
    for item in node.elts:
        if not isinstance(item, ast.Tuple) or len(item.elts) != 3:
            return None
        for value_node in item.elts:
            try:
                value = ast.literal_eval(value_node)
            except (ValueError, TypeError):
                return None
            if not isinstance(value, int) or isinstance(value, bool):
                return None
        entries.append(item)
    return tuple(entries)


def _remove_palette_entries(root: Path, candidate: NestedPaletteCandidate) -> None:
    """Remove one current batch with byte ranges while preserving the call."""
    path = root / candidate.file_path
    palette = _find_palette(path, root, candidate.binding_name)
    if palette is None or _palette_digest(palette) != candidate.source_digest:
        raise ValueError(f"stale or missing nested palette: {candidate.file_path}")
    if any(
        index < 0 or index >= len(palette.entries) for index in candidate.entry_indices
    ):
        raise ValueError(f"stale nested palette entry index: {candidate.file_path}")
    starts = _line_starts(palette.data)
    ranges = [
        _item_range(palette.data, palette.list_node, palette.entries[index], starts)
        for index in candidate.entry_indices
    ]
    updated = _apply_ranges(palette.data, ranges)
    try:
        ast.parse(updated.decode(palette.encoding), filename=str(path))
    except (SyntaxError, UnicodeError) as error:
        raise ValueError(
            f"nested palette edit produced invalid syntax in {path}"
        ) from error
    path.write_bytes(updated)


def _palette_digest(palette: _PaletteList) -> str:
    """Hash current list text so stale batches cannot edit new source."""
    starts = _line_starts(palette.data)
    start = starts[palette.list_node.lineno - 1] + palette.list_node.col_offset
    end = starts[(palette.list_node.end_lineno or palette.list_node.lineno) - 1] + (
        palette.list_node.end_col_offset or palette.list_node.col_offset
    )
    return hashlib.sha256(palette.data[start:end]).hexdigest()


def _source_span(node: ast.AST) -> int:
    """Return inclusive physical lines for report-only source span metadata."""
    return (node.end_lineno or node.lineno) - node.lineno + 1


def _unsafe_tokens(
    tokens: Collection[tokenize.TokenInfo], start: int, end: int
) -> bool:
    """Reject comments and semicolons inside an exact list-edit region."""
    return any(
        start <= token.start[0] <= end
        and (
            token.type == tokenize.COMMENT
            or (token.type == tokenize.OP and token.string == ";")
        )
        for token in tokens
    )
