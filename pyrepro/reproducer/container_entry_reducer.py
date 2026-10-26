"""Execution-verified reduction of entries in conservative module dictionaries.

The reducer deliberately handles only a narrow source form: one multiline,
module-level dictionary bound to one name, with string keys and static values.
It uses exact byte-range edits rather than reformatting the module with
``ast.unparse``. Static structure finds candidates; the established runtime
failure oracle remains the sole acceptance authority.
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


@dataclass(frozen=True)
class ContainerEntryCandidate:
    """A current batch of entries in one source-safe module dictionary."""

    file_path: str
    container_name: str
    keys: tuple[str, ...]
    source_digest: str
    source_span: int

    @property
    def identity(self) -> tuple[str, str, tuple[str, ...], str]:
        """Return a stable identity while the same container text is current."""
        return (self.file_path, self.container_name, self.keys, self.source_digest)


@dataclass(frozen=True)
class ContainerEntryDiscovery:
    """Supported static module dictionaries discovered in one source file."""

    containers: tuple[ContainerEntryCandidate, ...]
    skipped: bool


@dataclass(frozen=True)
class ContainerEntryReductionResult:
    """Verified metrics from bounded module-container entry reduction."""

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
class _Entry:
    """One static dictionary entry and its AST source boundaries."""

    key: str
    node: ast.expr
    value: ast.expr


@dataclass(frozen=True)
class _Dictionary:
    """Parsed source facts used to relocate a container edit safely."""

    name: str
    node: ast.Dict
    entries: tuple[_Entry, ...]
    data: bytes
    encoding: str


class GreedyContainerEntryReducer:
    """Reduce static module-dictionary entries with batch splitting.

    A root batch first probes removing all entries in one discovered container.
    Rejected batches are bisected deterministically; accepted batches are
    applied to the active disposable workspace. Every probe is separately
    copied and executed, so rejected edits cannot leak into later candidates.
    """

    def __init__(
        self,
        runner: CommandRunner,
        match_mode: FailureMatchMode = FailureMatchMode.STRICT,
        ignored_directory_names: Collection[str] = DEFAULT_IGNORED_DIRECTORY_NAMES,
        *,
        max_probes: int | None = None,
    ) -> None:
        """Initialize a bounded conservative dictionary-entry reducer."""
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
    ) -> ContainerEntryReductionResult:
        """Run bounded batch-and-split removal in ``workspace``.

        Args:
            workspace: Disposable reduction workspace whose source is protected.
            baseline_signature: Stable failure identity to preserve.
            budget: Optional shared Fast Mode execution budget.
            verify_final: Whether to issue a final direct verification.

        Returns:
            One result containing every execution-verified probe record.
        """
        started_at = perf_counter()
        initial_files = _python_files(workspace.root, self.ignored_directory_names)
        initial, skipped_paths = _discover_workspace(workspace.root, initial_files)
        initial_count = sum(len(item.keys) for item in initial)
        queue: deque[tuple[str, str, tuple[str, ...]]] = deque(
            (item.file_path, item.container_name, item.keys) for item in initial
        )
        records: list[ProbeRecord] = []
        accepted = 0
        budget_exhausted = False

        while queue and (self.max_probes is None or len(records) < self.max_probes):
            if budget is not None and not budget.can_start_probe():
                budget_exhausted = True
                break
            file_path, name, requested_keys = queue.popleft()
            dictionary = _find_dictionary(
                workspace.root / file_path, workspace.root, name
            )
            if dictionary is None:
                continue
            present = tuple(entry.key for entry in dictionary.entries)
            keys = tuple(key for key in requested_keys if key in set(present))
            if not keys:
                continue
            candidate = ContainerEntryCandidate(
                file_path=file_path,
                container_name=name,
                keys=keys,
                source_digest=_dictionary_digest(dictionary),
                source_span=_source_span(dictionary.node),
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
                _remove_entries(workspace.root / candidate.file_path, name, keys)
                accepted += 1
            elif len(keys) > 1:
                midpoint = len(keys) // 2
                queue.appendleft((file_path, name, keys[midpoint:]))
                queue.appendleft((file_path, name, keys[:midpoint]))

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
                    "final container-entry verification did not match baseline"
                )
        remaining_files = _python_files(workspace.root, self.ignored_directory_names)
        remaining, skipped = _discover_workspace(workspace.root, remaining_files)
        skipped_paths.update(skipped)
        remaining_count = sum(len(item.keys) for item in remaining)
        return ContainerEntryReductionResult(
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
        candidate: ContainerEntryCandidate,
        baseline_signature: FailureSignature,
        budget: ExecutionBudget | None,
    ) -> tuple[ReductionOutcome, ProbeRecord]:
        """Execute one batch in a fresh probe copy and report its outcome."""
        if budget is not None:
            budget.ensure_can_start(OracleExecutionKind.PROBE)
        with tempfile.TemporaryDirectory(
            prefix="pyrepro-container-entry-probe-"
        ) as name:
            probe_root = Path(name) / "project"
            shutil.copytree(workspace_root, probe_root)
            _remove_entries(
                probe_root / candidate.file_path,
                candidate.container_name,
                candidate.keys,
            )
            started_at = perf_counter()
            result = _run_oracle(
                self.runner, probe_root, budget, OracleExecutionKind.PROBE
            )
            duration = perf_counter() - started_at
            outcome = classify_result(
                result, baseline_signature, probe_root, self.match_mode
            )
            return outcome, _probe_record(
                "container_entry",
                (Path(candidate.file_path),),
                result,
                outcome,
                outcome is ReductionOutcome.SAME_FAILURE,
                duration,
                probe_root,
                candidate_python_lines=_python_line_count(
                    _python_files(probe_root, self.ignored_directory_names)
                ),
                candidate_descriptions=(
                    f"{candidate.file_path}:{candidate.container_name}:"
                    f"entries={len(candidate.keys)}:keys={','.join(candidate.keys)}:"
                    f"span={candidate.source_span}",
                ),
                candidate_rolled_back=outcome is not ReductionOutcome.SAME_FAILURE,
            )


def discover_container_entries(
    path: Path, workspace_root: Path
) -> ContainerEntryDiscovery:
    """Discover conservative static module dictionaries in one Python source."""
    dictionary = _supported_dictionaries(path, workspace_root)
    if dictionary is None:
        return ContainerEntryDiscovery((), skipped=True)
    return ContainerEntryDiscovery(
        tuple(
            ContainerEntryCandidate(
                file_path=path.relative_to(workspace_root).as_posix(),
                container_name=item.name,
                keys=tuple(entry.key for entry in item.entries),
                source_digest=_dictionary_digest(item),
                source_span=_source_span(item.node),
            )
            for item in dictionary
        ),
        skipped=False,
    )


def _discover_workspace(root: Path, files: Collection[Path]):
    """Return all current supported containers and paths that could not parse."""
    containers: list[ContainerEntryCandidate] = []
    skipped: set[str] = set()
    for path in files:
        discovery = discover_container_entries(path, root)
        containers.extend(discovery.containers)
        if discovery.skipped:
            skipped.add(path.relative_to(root).as_posix())
    return tuple(containers), skipped


def _find_dictionary(path: Path, root: Path, name: str) -> _Dictionary | None:
    """Relocate one named source-safe dictionary in its current source text."""
    dictionaries = _supported_dictionaries(path, root)
    if dictionaries is None:
        return None
    return next((item for item in dictionaries if item.name == name), None)


def _supported_dictionaries(
    path: Path, workspace_root: Path
) -> tuple[_Dictionary, ...] | None:
    """Parse source and return only unambiguous safe module-level dictionaries."""
    try:
        data = path.read_bytes()
        encoding, _ = tokenize.detect_encoding(io.BytesIO(data).readline)
        content = data.decode(encoding)
        tree = ast.parse(content, filename=str(path))
        tokens = tuple(tokenize.generate_tokens(io.StringIO(content).readline))
    except (OSError, SyntaxError, UnicodeError, tokenize.TokenError):
        return None
    bindings: dict[str, list[ast.Dict | None]] = {}
    for statement in tree.body:
        target, value = _assignment_parts(statement)
        if target is None:
            for name in _target_names(statement):
                bindings.setdefault(name, []).append(None)
            continue
        bindings.setdefault(target, []).append(value)
    dictionaries: list[_Dictionary] = []
    for name, values in bindings.items():
        if len(values) != 1 or not isinstance(values[0], ast.Dict):
            continue
        node = values[0]
        if node.end_lineno is None or node.lineno == node.end_lineno:
            continue
        if _unsafe_tokens(tokens, node.lineno, node.end_lineno):
            continue
        entries = _static_entries(node)
        if entries is None or not entries:
            continue
        dictionaries.append(_Dictionary(name, node, entries, data, encoding))
    return tuple(dictionaries)


def _assignment_parts(statement: ast.stmt) -> tuple[str | None, ast.Dict | None]:
    """Return a one-name dict binding, or a marker for unsupported bindings."""
    if isinstance(statement, ast.Assign) and len(statement.targets) == 1:
        if isinstance(statement.targets[0], ast.Name) and isinstance(
            statement.value, ast.Dict
        ):
            return statement.targets[0].id, statement.value
    if isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
        if isinstance(statement.value, ast.Dict):
            return statement.target.id, statement.value
    return None, None


def _target_names(statement: ast.stmt) -> tuple[str, ...]:
    """Return direct module names potentially rebound by an unsupported statement."""
    targets: list[ast.expr] = []
    if isinstance(statement, ast.Assign):
        targets.extend(statement.targets)
    elif isinstance(statement, ast.AnnAssign):
        targets.append(statement.target)
    elif isinstance(statement, ast.AugAssign):
        targets.append(statement.target)
    return tuple(name for target in targets for name in _names_in_target(target))


def _names_in_target(target: ast.expr) -> tuple[str, ...]:
    """Return every direct name bound by one assignment target shape."""
    if isinstance(target, ast.Name):
        return (target.id,)
    if isinstance(target, ast.Tuple | ast.List):
        return tuple(name for item in target.elts for name in _names_in_target(item))
    return ()


def _static_entries(node: ast.Dict) -> tuple[_Entry, ...] | None:
    """Return safe string-key entries, or ``None`` for dynamic dictionary syntax."""
    entries: list[_Entry] = []
    seen: set[str] = set()
    for key, value in zip(node.keys, node.values, strict=True):
        if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
            return None
        if key.value in seen or not _is_supported_entry_value(value):
            return None
        seen.add(key.value)
        entries.append(_Entry(key.value, key, value))
    return tuple(entries)


def _is_static_value(node: ast.expr) -> bool:
    """Recognize static literals and direct-name construction with literal arguments."""
    if isinstance(node, ast.Constant):
        return True
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.UAdd | ast.USub):
        return isinstance(node.operand, ast.Constant)
    if isinstance(node, ast.Tuple | ast.List | ast.Set):
        return all(_is_static_value(item) for item in node.elts)
    if isinstance(node, ast.Dict):
        return all(
            key is not None and _is_static_value(key) and _is_static_value(value)
            for key, value in zip(node.keys, node.values, strict=True)
        )
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        return all(_is_static_value(item) for item in node.args) and all(
            keyword.arg is not None and _is_static_value(keyword.value)
            for keyword in node.keywords
        )
    return False


def _is_supported_entry_value(node: ast.expr) -> bool:
    """Recognize the deliberately narrow first-version dictionary values."""
    if isinstance(node, ast.Constant):
        return isinstance(node.value, str)
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and all(_is_static_value(item) for item in node.args)
        and all(
            keyword.arg is not None and _is_static_value(keyword.value)
            for keyword in node.keywords
        )
    )


def _remove_entries(path: Path, name: str, keys: Collection[str]) -> None:
    """Apply one exact byte-range entry deletion and verify the new syntax."""
    dictionary = _find_dictionary(path, path.parent, name)
    if dictionary is None:
        raise ValueError(f"unsupported or missing dictionary: {name}")
    remove = set(keys)
    selected = [entry for entry in dictionary.entries if entry.key in remove]
    if not selected:
        return
    data = dictionary.data
    line_starts = _line_starts(data)
    ranges = [
        _entry_range(data, dictionary.node, entry, line_starts) for entry in selected
    ]
    updated = _apply_ranges(data, ranges)
    try:
        ast.parse(updated.decode(dictionary.encoding), filename=str(path))
    except (SyntaxError, UnicodeError) as error:
        raise ValueError(f"entry edit produced invalid syntax in {path}") from error
    path.write_bytes(updated)


def _entry_range(
    data: bytes, node: ast.Dict, entry: _Entry, line_starts: list[int]
) -> tuple[int, int]:
    """Return one entry's byte range, including an adjacent comma when safe."""
    start = _offset(line_starts, entry.node.lineno, entry.node.col_offset)
    end = _offset(line_starts, entry.value.end_lineno, entry.value.end_col_offset)
    cursor = end
    while cursor < len(data) and data[cursor] in b" \t\r\n":
        cursor += 1
    if cursor < len(data) and data[cursor : cursor + 1] == b",":
        cursor += 1
        while cursor < len(data) and data[cursor] in b" \t\r\n":
            cursor += 1
        return start, cursor
    node_start = _offset(line_starts, node.lineno, node.col_offset)
    previous = data.rfind(b",", node_start, start)
    if previous >= node_start:
        return previous, end
    return start, end


def _apply_ranges(data: bytes, ranges: Collection[tuple[int, int]]) -> bytes:
    """Apply non-overlapping ranges from tail to head, merging adjacency first."""
    ordered = sorted(ranges)
    merged: list[tuple[int, int]] = []
    for start, end in ordered:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    updated = data
    for start, end in reversed(merged):
        updated = updated[:start] + updated[end:]
    return updated


def _dictionary_digest(dictionary: _Dictionary) -> str:
    """Hash current dictionary bytes for telemetry identity."""
    starts = _line_starts(dictionary.data)
    start = _offset(starts, dictionary.node.lineno, dictionary.node.col_offset)
    end = _offset(starts, dictionary.node.end_lineno, dictionary.node.end_col_offset)
    return hashlib.sha256(dictionary.data[start:end]).hexdigest()


def _source_span(node: ast.AST) -> int:
    """Return an inclusive physical line span for display only."""
    return (node.end_lineno or node.lineno) - node.lineno + 1


def _line_starts(data: bytes) -> list[int]:
    """Return byte positions of physical source-line starts."""
    starts = [0]
    starts.extend(index + 1 for index, byte in enumerate(data) if byte == 10)
    return starts


def _offset(starts: list[int], line: int, column: int) -> int:
    """Translate AST's byte column into an absolute byte offset."""
    return starts[line - 1] + column


def _unsafe_tokens(
    tokens: Collection[tokenize.TokenInfo], start: int, end: int
) -> bool:
    """Reject comment and semicolon source that AST ranges would not retain."""
    return any(
        start <= token.start[0] <= end
        and (
            token.type == tokenize.COMMENT
            or (token.type == tokenize.OP and token.string == ";")
        )
        for token in tokens
    )
