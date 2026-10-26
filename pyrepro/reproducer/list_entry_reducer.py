"""Execution-verified reduction of conservative module-level list entries.

This reducer accepts only multiline module-level lists with unique elements
that are tuples of integer literals.  It uses exact byte-range edits and
batch splitting to minimize source risk; the established runtime failure
oracle is the sole authority that accepts or rejects a deletion.
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

ListValue = tuple[int, ...]


@dataclass(frozen=True)
class ListEntryCandidate:
    """A batch of entries in one current, source-safe module-level list."""

    file_path: str
    container_name: str
    values: tuple[ListValue, ...]
    source_digest: str
    source_span: int


@dataclass(frozen=True)
class ListEntryDiscovery:
    """Conservative module-level lists discovered in one Python source file."""

    containers: tuple[ListEntryCandidate, ...]
    skipped: bool


@dataclass(frozen=True)
class ListEntryReductionResult:
    """Verified metrics from bounded static list-entry reduction."""

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
    skipped_unparsable_files: tuple[str, ...]
    wall_clock_seconds: float
    budget_exhausted: bool = False


@dataclass(frozen=True)
class _StaticList:
    """Current parsed facts needed to relocate one list edit safely."""

    name: str
    node: ast.List
    values: tuple[ListValue, ...]
    item_nodes: tuple[ast.expr, ...]
    data: bytes
    encoding: str


class GreedyListEntryReducer:
    """Reduce entries in conservative module-level lists with batch splitting.

    The reducer probes removing all entries in each discovered list before
    recursively splitting rejected batches.  Rejected probes run in a copied
    workspace, so no rejected edit reaches the active workspace.
    """

    def __init__(
        self,
        runner: CommandRunner,
        match_mode: FailureMatchMode = FailureMatchMode.STRICT,
        ignored_directory_names: Collection[str] = DEFAULT_IGNORED_DIRECTORY_NAMES,
        *,
        max_probes: int | None = None,
    ) -> None:
        """Initialize a bounded conservative list-entry reducer."""
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
    ) -> ListEntryReductionResult:
        """Run bounded batch-and-split list-entry reduction in ``workspace``."""
        started_at = perf_counter()
        initial_files = _python_files(workspace.root, self.ignored_directory_names)
        initial, skipped_paths = _discover_workspace(workspace.root, initial_files)
        initial_count = sum(len(item.values) for item in initial)
        queue: deque[tuple[str, str, tuple[ListValue, ...]]] = deque(
            (item.file_path, item.container_name, item.values) for item in initial
        )
        records: list[ProbeRecord] = []
        accepted = 0
        budget_exhausted = False

        while queue and (self.max_probes is None or len(records) < self.max_probes):
            if budget is not None and not budget.can_start_probe():
                budget_exhausted = True
                break
            file_path, name, requested_values = queue.popleft()
            container = _find_list(workspace.root / file_path, workspace.root, name)
            if container is None:
                continue
            present = set(container.values)
            values = tuple(value for value in requested_values if value in present)
            if not values:
                continue
            candidate = ListEntryCandidate(
                file_path=file_path,
                container_name=name,
                values=values,
                source_digest=_list_digest(container),
                source_span=_source_span(container.node),
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
                _remove_entries(
                    workspace.root / candidate.file_path, name, candidate.values
                )
                accepted += 1
            elif len(values) > 1:
                midpoint = len(values) // 2
                queue.appendleft((file_path, name, values[midpoint:]))
                queue.appendleft((file_path, name, values[:midpoint]))

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
                    "final list-entry verification did not match baseline"
                )
        remaining_files = _python_files(workspace.root, self.ignored_directory_names)
        remaining, skipped = _discover_workspace(workspace.root, remaining_files)
        skipped_paths.update(skipped)
        remaining_count = sum(len(item.values) for item in remaining)
        return ListEntryReductionResult(
            baseline_signature=baseline_signature,
            initial_python_lines=_python_line_count(initial_files),
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
            skipped_unparsable_files=tuple(sorted(skipped_paths)),
            wall_clock_seconds=perf_counter() - started_at,
            budget_exhausted=budget_exhausted,
        )

    def _probe_candidate(
        self,
        workspace_root: Path,
        candidate: ListEntryCandidate,
        baseline_signature: FailureSignature,
        budget: ExecutionBudget | None,
    ) -> tuple[ReductionOutcome, ProbeRecord]:
        """Execute one list batch in a fresh probe copy."""
        if budget is not None:
            budget.ensure_can_start(OracleExecutionKind.PROBE)
        with tempfile.TemporaryDirectory(prefix="pyrepro-list-entry-probe-") as name:
            probe_root = Path(name) / "project"
            shutil.copytree(workspace_root, probe_root)
            _remove_entries(
                probe_root / candidate.file_path,
                candidate.container_name,
                candidate.values,
            )
            started_at = perf_counter()
            execution = _run_oracle(
                self.runner, probe_root, budget, OracleExecutionKind.PROBE
            )
            duration = perf_counter() - started_at
            outcome = classify_result(
                execution, baseline_signature, probe_root, self.match_mode
            )
            return outcome, _probe_record(
                "list_entry",
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
                    f"{candidate.file_path}:{candidate.container_name}:"
                    f"entries={len(candidate.values)}:span={candidate.source_span}",
                ),
                candidate_rolled_back=outcome is not ReductionOutcome.SAME_FAILURE,
            )


def discover_list_entries(path: Path, workspace_root: Path) -> ListEntryDiscovery:
    """Discover source-safe static module lists in one Python source file."""
    containers = _supported_lists(path, workspace_root)
    if containers is None:
        return ListEntryDiscovery((), skipped=True)
    return ListEntryDiscovery(
        tuple(
            ListEntryCandidate(
                file_path=path.relative_to(workspace_root).as_posix(),
                container_name=item.name,
                values=item.values,
                source_digest=_list_digest(item),
                source_span=_source_span(item.node),
            )
            for item in containers
            if item.values
        ),
        skipped=False,
    )


def _discover_workspace(root: Path, files: Collection[Path]):
    """Return current supported list containers and unparseable source paths."""
    containers: list[ListEntryCandidate] = []
    skipped: set[str] = set()
    for path in files:
        discovery = discover_list_entries(path, root)
        containers.extend(discovery.containers)
        if discovery.skipped:
            skipped.add(path.relative_to(root).as_posix())
    return tuple(containers), skipped


def _find_list(path: Path, root: Path, name: str) -> _StaticList | None:
    """Relocate one named source-safe list in its current source text."""
    containers = _supported_lists(path, root)
    if containers is None:
        return None
    return next((item for item in containers if item.name == name), None)


def _supported_lists(
    path: Path, workspace_root: Path
) -> tuple[_StaticList, ...] | None:
    """Parse only unambiguous multiline module-level lists with int tuples."""
    try:
        data = path.read_bytes()
        encoding, _ = tokenize.detect_encoding(io.BytesIO(data).readline)
        content = data.decode(encoding)
        tree = ast.parse(content, filename=str(path))
        tokens = tuple(tokenize.generate_tokens(io.StringIO(content).readline))
    except (OSError, SyntaxError, UnicodeError, tokenize.TokenError):
        return None
    bindings: dict[str, list[ast.List | None]] = {}
    for statement in tree.body:
        target, value = _assignment_parts(statement)
        if target is None:
            for name in _target_names(statement):
                bindings.setdefault(name, []).append(None)
            continue
        bindings.setdefault(target, []).append(value)
    lists: list[_StaticList] = []
    for name, values in bindings.items():
        if len(values) != 1 or not isinstance(values[0], ast.List):
            continue
        node = values[0]
        if node.end_lineno is None or node.lineno == node.end_lineno:
            continue
        if _unsafe_tokens(tokens, node.lineno, node.end_lineno):
            continue
        entries = _list_values(node)
        if entries is None:
            continue
        lists.append(_StaticList(name, node, entries, tuple(node.elts), data, encoding))
    return tuple(lists)


def _assignment_parts(statement: ast.stmt) -> tuple[str | None, ast.List | None]:
    """Return one-name list binding or a marker for unsupported bindings."""
    if isinstance(statement, ast.Assign) and len(statement.targets) == 1:
        if isinstance(statement.targets[0], ast.Name) and isinstance(
            statement.value, ast.List
        ):
            return statement.targets[0].id, statement.value
    if isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
        if isinstance(statement.value, ast.List):
            return statement.target.id, statement.value
    return None, None


def _target_names(statement: ast.stmt) -> tuple[str, ...]:
    """Return names possibly rebound by an unsupported module statement."""
    targets: list[ast.expr] = []
    if isinstance(statement, ast.Assign):
        targets.extend(statement.targets)
    elif isinstance(statement, ast.AnnAssign | ast.AugAssign):
        targets.append(statement.target)
    return tuple(name for target in targets for name in _names_in_target(target))


def _names_in_target(target: ast.expr) -> tuple[str, ...]:
    """Return direct names in one assignment target."""
    if isinstance(target, ast.Name):
        return (target.id,)
    if isinstance(target, ast.Tuple | ast.List):
        return tuple(name for item in target.elts for name in _names_in_target(item))
    return ()


def _list_values(node: ast.List) -> tuple[ListValue, ...] | None:
    """Return unique integer-tuple entries, rejecting other expressions."""
    values: list[ListValue] = []
    for item in node.elts:
        if not isinstance(item, ast.Tuple):
            return None
        tuple_values: list[int] = []
        for value_node in item.elts:
            try:
                value = ast.literal_eval(value_node)
            except (ValueError, TypeError):
                return None
            if not isinstance(value, int) or isinstance(value, bool):
                return None
            tuple_values.append(value)
        values.append(tuple(tuple_values))
    return tuple(values) if len(set(values)) == len(values) else None


def _remove_entries(path: Path, name: str, values: Collection[ListValue]) -> None:
    """Apply exact byte-range edits and verify that the module still parses."""
    container = _find_list(path, path.parent, name)
    if container is None:
        raise ValueError(f"unsupported or missing list: {name}")
    remove = set(values)
    selected = [
        node
        for value, node in zip(container.values, container.item_nodes, strict=True)
        if value in remove
    ]
    if not selected:
        return
    starts = _line_starts(container.data)
    ranges = [
        _item_range(container.data, container.node, item, starts) for item in selected
    ]
    updated = _apply_ranges(container.data, ranges)
    try:
        ast.parse(updated.decode(container.encoding), filename=str(path))
    except (SyntaxError, UnicodeError) as error:
        raise ValueError(f"list edit produced invalid syntax in {path}") from error
    path.write_bytes(updated)


def _item_range(
    data: bytes, node: ast.List, item: ast.expr, starts: list[int]
) -> tuple[int, int]:
    """Return an item's byte range, including one adjacent comma when safe."""
    start = _offset(starts, item.lineno, item.col_offset)
    end = _offset(
        starts, item.end_lineno or item.lineno, item.end_col_offset or item.col_offset
    )
    cursor = end
    while cursor < len(data) and data[cursor] in b" \t\r\n":
        cursor += 1
    if cursor < len(data) and data[cursor : cursor + 1] == b",":
        cursor += 1
        while cursor < len(data) and data[cursor] in b" \t\r\n":
            cursor += 1
        return start, cursor
    node_start = _offset(starts, node.lineno, node.col_offset)
    previous = data.rfind(b",", node_start, start)
    return (previous, end) if previous >= node_start else (start, end)


def _list_digest(container: _StaticList) -> str:
    """Hash current list bytes for stable telemetry identity."""
    starts = _line_starts(container.data)
    start = _offset(starts, container.node.lineno, container.node.col_offset)
    end = _offset(
        starts,
        container.node.end_lineno or container.node.lineno,
        container.node.end_col_offset or container.node.col_offset,
    )
    return hashlib.sha256(container.data[start:end]).hexdigest()


def _source_span(node: ast.AST) -> int:
    """Return an inclusive physical source span for display only."""
    return (node.end_lineno or node.lineno) - node.lineno + 1


def _line_starts(data: bytes) -> list[int]:
    """Return byte offsets for physical source lines."""
    return [0, *(index + 1 for index, byte in enumerate(data) if byte == 10)]


def _offset(starts: list[int], line: int, column: int) -> int:
    """Translate AST byte columns into an absolute source offset."""
    return starts[line - 1] + column


def _apply_ranges(data: bytes, ranges: Collection[tuple[int, int]]) -> bytes:
    """Apply non-overlapping ranges from tail to head, merging adjacency."""
    merged: list[list[int]] = []
    for start, end in sorted(ranges):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    for start, end in reversed(merged):
        data = data[:start] + data[end:]
    return data


def _unsafe_tokens(
    tokens: Collection[tokenize.TokenInfo], start: int, end: int
) -> bool:
    """Reject comments and semicolons that exact AST ranges cannot preserve."""
    return any(
        start <= token.start[0] <= end
        and (
            token.type == tokenize.COMMENT
            or (token.type == tokenize.OP and token.string == ";")
        )
        for token in tokens
    )
