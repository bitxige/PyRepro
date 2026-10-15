"""Execution-verified, bounded batch pruning of target-aware import candidates."""

from __future__ import annotations

import ast
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
    exception_details,
)
from pyrepro.reproducer.reducer import (
    DEFAULT_IGNORED_DIRECTORY_NAMES,
    ProbeRecord,
    UnstableBaselineError,
    _establish_baseline,
    _python_files,
    _python_line_count,
    _run_oracle,
    _verify_final_workspace,
)
from pyrepro.reproducer.runner import CommandRunner
from pyrepro.reproducer.workspace import ReductionWorkspace
from pyrepro.scanner.import_analyzer import ImportAnalyzer, ImportCandidate


@dataclass(frozen=True)
class ImportPruningResult:
    """Final-verified result of a target-aware import-pruning run."""

    baseline_signature: FailureSignature
    baseline_runs: int
    candidates_discovered: int
    editable_operations: int
    skipped_candidates: int
    candidate_attempts: int
    accepted_probes: int
    rejected_probes: int
    executions: int
    initial_python_lines: int
    remaining_python_lines: int
    wall_clock_seconds: float
    probe_records: tuple[ProbeRecord, ...]
    source_unchanged: bool
    budget_exhausted: bool = False


@dataclass(frozen=True)
class _Edit:
    """One UTF-8 byte-range replacement in a source file."""

    start: int
    end: int
    replacement: bytes


@dataclass(frozen=True)
class _Operation:
    """A candidate group whose concrete edits are rebuilt for every probe."""

    candidates: tuple[ImportCandidate, ...]

    @property
    def paths(self) -> tuple[str, ...]:
        return tuple(sorted({candidate.path for candidate in self.candidates}))

    @property
    def descriptions(self) -> tuple[str, ...]:
        return tuple(
            f"{candidate.path}:{candidate.line}:{candidate.bound_name}"
            for candidate in self.candidates
        )


@dataclass(frozen=True)
class _EditPlan:
    """Non-overlapping current-workspace edits for one atomic probe."""

    edits_by_path: tuple[tuple[str, tuple[_Edit, ...]], ...]


class _EditPlanUnavailableError(Exception):
    """Raised when current source no longer safely supports a planned probe."""


class BatchImportPruner:
    """Apply source-local import edits in accepted batches only.

    Static candidates are never trusted as deletion permission. Every batch is
    applied only to an active disposable workspace and retained solely when the
    existing failure oracle reports the established baseline failure.
    """

    def __init__(
        self,
        runner: CommandRunner,
        pytest_node: str,
        *,
        baseline_runs: int = 3,
        expected_text: str | None = None,
        match_mode: FailureMatchMode = FailureMatchMode.STRICT,
        max_probes: int = 16,
    ) -> None:
        """Configure a bounded import-pruning run."""
        if baseline_runs <= 0:
            raise ValueError("baseline_runs must be positive")
        if max_probes <= 0:
            raise ValueError("max_probes must be positive")
        self.runner = runner
        self.pytest_node = pytest_node
        self.baseline_runs = baseline_runs
        self.expected_text = _normalize_expected_text(expected_text)
        self.match_mode = match_mode
        self.max_probes = max_probes

    def prune(
        self,
        workspace: ReductionWorkspace,
        baseline_signature: FailureSignature | None = None,
        *,
        budget: ExecutionBudget | None = None,
        verify_final: bool = True,
    ) -> ImportPruningResult:
        """Run bounded probes and final verification in a workspace.

        Args:
            workspace: Active disposable workspace to edit.
            baseline_signature: Existing stable signature from an earlier
                composed stage. When omitted, establishes the normal baseline.
            budget: Optional shared Fast-Mode Oracle budget.
            verify_final: Whether to run the normal single-run stage check.
                Fast Mode defers this to its independent final verification.
        """
        started = perf_counter()
        if baseline_signature is None:
            baseline, executions = _establish_baseline(
                self.runner,
                workspace.root,
                self.baseline_runs,
                self.expected_text,
                self.match_mode,
                budget,
            )
            baseline_runs = self.baseline_runs
        else:
            baseline = baseline_signature
            executions = 0
            baseline_runs = 0
        analysis = ImportAnalyzer(workspace.root).analyze_pytest_node(self.pytest_node)
        operations, skipped = _build_operations(workspace.root, analysis.candidates)
        legacy_operations, extended_operations = _partition_operations(
            workspace.root, operations
        )
        initial_lines = _line_count(workspace.root)
        records: list[ProbeRecord] = []
        accepted = rejected = 0
        budget_exhausted = False
        for cohort in (legacy_operations, extended_operations):
            low_risk, risk_marked = _risk_batches(cohort)
            for batch in (low_risk, risk_marked):
                if not batch or len(records) >= self.max_probes:
                    continue
                if budget is not None and not budget.can_start_probe():
                    budget_exhausted = True
                    break
                new_records, new_accepted, new_rejected, stopped = self._search(
                    workspace.root,
                    batch,
                    baseline,
                    self.max_probes - len(records),
                    budget,
                )
                records.extend(new_records)
                accepted += new_accepted
                rejected += new_rejected
                if stopped:
                    budget_exhausted = True
                    break
            if budget_exhausted:
                break
        executions += len(records)
        if verify_final and not budget_exhausted:
            if (
                _verify_final_workspace(
                    self.runner,
                    workspace.root,
                    baseline,
                    self.match_mode,
                    budget,
                )
                is not ReductionOutcome.SAME_FAILURE
            ):
                raise UnstableBaselineError(
                    "final import-pruning verification did not match baseline"
                )
            executions += 1
        return ImportPruningResult(
            baseline_signature=baseline,
            baseline_runs=baseline_runs,
            candidates_discovered=len(analysis.candidates),
            editable_operations=len(operations),
            skipped_candidates=skipped,
            candidate_attempts=len(records),
            accepted_probes=accepted,
            rejected_probes=rejected,
            executions=executions,
            initial_python_lines=initial_lines,
            remaining_python_lines=_line_count(workspace.root),
            wall_clock_seconds=perf_counter() - started,
            probe_records=tuple(records),
            source_unchanged=workspace.source_is_unchanged(),
            budget_exhausted=budget_exhausted,
        )

    def _search(
        self,
        root: Path,
        operations: tuple[_Operation, ...],
        baseline: FailureSignature,
        budget: int,
        execution_budget: ExecutionBudget | None,
    ) -> tuple[list[ProbeRecord], int, int, bool]:
        """Try one batch, then split rejected batches while budget remains."""
        if not operations or budget <= 0:
            return [], 0, 0, False
        current_operations = tuple(
            operation
            for operation in operations
            if _build_edit_plan(root, (operation,)) is not None
        )
        if not current_operations:
            return [], 0, 0, False
        if current_operations != operations:
            return self._search(
                root, current_operations, baseline, budget, execution_budget
            )
        try:
            record, accepted = self._probe(
                root, current_operations, baseline, execution_budget
            )
        except BudgetExhaustedError:
            return [], 0, 0, True
        except _EditPlanUnavailableError:
            if len(current_operations) == 1:
                return [], 0, 0, False
            split = len(current_operations) // 2
            left, left_yes, left_no, left_stopped = self._search(
                root, current_operations[:split], baseline, budget, execution_budget
            )
            if left_stopped or len(left) >= budget:
                return left, left_yes, left_no, left_stopped
            right, right_yes, right_no, right_stopped = self._search(
                root,
                current_operations[split:],
                baseline,
                budget - len(left),
                execution_budget,
            )
            return left + right, left_yes + right_yes, left_no + right_no, right_stopped
        records = [record]
        if accepted:
            return records, 1, 0, False
        if len(current_operations) == 1 or budget == 1:
            return records, 0, 1, False
        split = len(current_operations) // 2
        left, left_yes, left_no, left_stopped = self._search(
            root, current_operations[:split], baseline, budget - 1, execution_budget
        )
        records.extend(left)
        if left_stopped:
            return records, left_yes, left_no + 1, True
        if len(records) < budget:
            right, right_yes, right_no, right_stopped = self._search(
                root,
                current_operations[split:],
                baseline,
                budget - len(records),
                execution_budget,
            )
            records.extend(right)
        else:
            right_yes = right_no = 0
            right_stopped = False
        return records, left_yes + right_yes, left_no + right_no + 1, right_stopped

    def _probe(
        self,
        root: Path,
        operations: tuple[_Operation, ...],
        baseline: FailureSignature,
        budget: ExecutionBudget | None,
    ) -> tuple[ProbeRecord, bool]:
        if budget is not None:
            budget.ensure_can_start(OracleExecutionKind.PROBE)
        plan = _build_edit_plan(root, operations)
        if plan is None:
            raise _EditPlanUnavailableError
        originals = _apply(root, plan)
        accepted = False
        try:
            started = perf_counter()
            execution = _run_oracle(
                self.runner, root, budget, OracleExecutionKind.PROBE
            )
            duration = perf_counter() - started
            outcome = classify_result(execution, baseline, root, self.match_mode)
            proposed_lines = _line_count(root)
            accepted = outcome is ReductionOutcome.SAME_FAILURE
            details = exception_details(execution)
            error_type, error_message = details or (None, None)
            return (
                ProbeRecord(
                    phase="import_pruning",
                    candidate_paths=tuple(
                        sorted(
                            {
                                path
                                for operation in operations
                                for path in operation.paths
                            }
                        )
                    ),
                    candidate_descriptions=tuple(
                        item
                        for operation in operations
                        for item in operation.descriptions
                    ),
                    outcome=outcome,
                    accepted=accepted,
                    duration_seconds=duration,
                    return_code=execution.return_code,
                    exception_type=error_type,
                    exception_message=error_message,
                    failure_signature=FailureSignature.from_result(execution, root),
                    candidate_python_lines=proposed_lines,
                ),
                accepted,
            )
        finally:
            if not accepted:
                _restore(root, originals)


def _build_operations(
    root: Path, candidates: tuple[ImportCandidate, ...]
) -> tuple[tuple[_Operation, ...], int]:
    """Build initially safe operation identities without retaining source ranges."""
    grouped: dict[tuple[str, int], list[ImportCandidate]] = {}
    for candidate in candidates:
        grouped.setdefault((candidate.path, candidate.line), []).append(candidate)
    operations: list[_Operation] = []
    skipped = 0
    for (path, line), group in grouped.items():
        del path, line
        operation = _Operation(tuple(group))
        if _build_edit_plan(root, (operation,)) is None:
            skipped += len(group)
        else:
            operations.append(operation)
    return tuple(operations), skipped


def _partition_operations(
    root: Path, operations: tuple[_Operation, ...]
) -> tuple[tuple[_Operation, ...], tuple[_Operation, ...]]:
    """Separate prior single-line shapes from P7-only source shapes.

    The legacy cohort is defined by the old editor's actual source contract,
    rather than by a broad path or candidate-kind heuristic. It keeps its
    original discovery order and risk batching so newly supported multiline
    shapes cannot consume the bounded probe budget before existing operations.
    """
    legacy: list[_Operation] = []
    extended: list[_Operation] = []
    for operation in operations:
        if _is_legacy_operation(root, operation):
            legacy.append(operation)
        else:
            extended.append(operation)
    return tuple(legacy), tuple(extended)


def _risk_batches(
    operations: tuple[_Operation, ...],
) -> tuple[tuple[_Operation, ...], tuple[_Operation, ...]]:
    """Return the existing low-risk then risk-marked batch order unchanged."""
    low_risk = tuple(
        operation
        for operation in operations
        if all(candidate.risk_reason is None for candidate in operation.candidates)
    )
    risk_marked = tuple(
        operation for operation in operations if operation not in low_risk
    )
    return low_risk, risk_marked


def _is_legacy_operation(root: Path, operation: _Operation) -> bool:
    """Return whether one operation fits the pre-P7 source-editor contract."""
    candidates_by_path: dict[str, list[ImportCandidate]] = {}
    for candidate in operation.candidates:
        candidates_by_path.setdefault(candidate.path, []).append(candidate)

    for path, candidates in candidates_by_path.items():
        try:
            source = (root / path).read_text(encoding="utf-8")
            tree = ast.parse(source, filename=path)
        except (OSError, UnicodeDecodeError, SyntaxError):
            return False
        matched = {
            node
            for candidate in candidates
            for node in _matching_import_nodes(tree, candidate)
        }
        if len(matched) != 1:
            return False
        import_node = next(iter(matched))
        if import_node.lineno != import_node.end_lineno or not _safe_statement(
            source, import_node
        ):
            return False

        all_lines = {
            candidate.all_line for candidate in candidates if candidate.all_line
        }
        if not all_lines:
            continue
        if len(all_lines) != 1:
            return False
        all_nodes = [
            node
            for node in tree.body
            if _is_all(node) and node.lineno == next(iter(all_lines))
        ]
        if len(all_nodes) != 1:
            return False
        all_node = all_nodes[0]
        if all_node.lineno != all_node.end_lineno or not _safe_statement(
            source, all_node
        ):
            return False
    return True


def _build_edit_plan(
    root: Path, operations: tuple[_Operation, ...]
) -> _EditPlan | None:
    """Rebuild one non-overlapping byte-edit plan from current workspace text.

    Candidate line numbers are discovery metadata only. Every probe reparses
    current source and matches candidates by their stable binding identity so a
    prior accepted edit cannot make a later probe use stale source ranges.
    """
    candidates_by_path: dict[str, list[ImportCandidate]] = {}
    for operation in operations:
        for candidate in operation.candidates:
            candidates_by_path.setdefault(candidate.path, []).append(candidate)

    planned: list[tuple[str, tuple[_Edit, ...]]] = []
    for path, candidates in candidates_by_path.items():
        source_path = root / path
        try:
            source_bytes = source_path.read_bytes()
            source = source_bytes.decode("utf-8")
            tree = ast.parse(source, filename=path)
        except (OSError, UnicodeDecodeError, SyntaxError):
            return None
        edits = _plan_file_edits(source, source_bytes, tree, candidates)
        if edits is None:
            return None
        planned.append((path, edits))
    return _EditPlan(tuple(sorted(planned)))


def _plan_file_edits(
    source: str,
    source_bytes: bytes,
    tree: ast.Module,
    candidates: list[ImportCandidate],
) -> tuple[_Edit, ...] | None:
    """Plan all import and shared-``__all__`` edits for one current source file."""
    import_matches: dict[ast.Import | ast.ImportFrom, list[ImportCandidate]] = {}
    for candidate in candidates:
        matches = _matching_import_nodes(tree, candidate)
        if len(matches) != 1:
            return None
        import_matches.setdefault(matches[0], []).append(candidate)

    edits: list[_Edit] = []
    removed_from_all: set[str] = set()
    for node, node_candidates in import_matches.items():
        if not _safe_statement(source, node):
            return None
        removed = {candidate.bound_name for candidate in node_candidates}
        aliases = [
            alias for alias in node.names if _bound_name(node, alias) not in removed
        ]
        if len(aliases) == len(node.names):
            return None
        start, end = _byte_range(source, node)
        if not aliases:
            end = _line_end(source_bytes, end)
            replacement = b""
        else:
            replacement = _render_import(node, aliases).encode("utf-8")
        edits.append(_Edit(start, end, replacement))
        for candidate in node_candidates:
            if candidate.all_line is not None:
                removed_from_all.add(candidate.bound_name)

    all_nodes = [node for node in tree.body if _is_all(node)]
    if removed_from_all and (len(all_nodes) != 1 or _has_dynamic_all_mutation(tree)):
        return None
    if removed_from_all:
        node = all_nodes[0]
        if not _safe_statement(source, node):
            return None
        all_edit = _render_all_edit(source, node, removed_from_all)
        if all_edit is None:
            return None
        edits.append(all_edit)
    if _has_overlapping_edits(edits):
        return None
    return tuple(edits)


def _matching_import_nodes(
    tree: ast.Module, candidate: ImportCandidate
) -> list[ast.Import | ast.ImportFrom]:
    """Return current top-level imports uniquely matching one candidate binding."""
    matches: list[ast.Import | ast.ImportFrom] = []
    for node in tree.body:
        if not isinstance(node, ast.Import | ast.ImportFrom):
            continue
        for alias in node.names:
            if _bound_name(node, alias) != candidate.bound_name:
                continue
            if candidate.imported_name is not None:
                if (
                    not isinstance(node, ast.ImportFrom)
                    or alias.name != candidate.imported_name
                    or not _matches_from_import_context(node, candidate)
                ):
                    continue
            elif (
                not isinstance(node, ast.Import)
                or alias.name != candidate.imported_module
            ):
                continue
            matches.append(node)
            break
    return matches


def _matches_from_import_context(
    node: ast.ImportFrom, candidate: ImportCandidate
) -> bool:
    """Return whether a current from-import matches the candidate module.

    Relative imports cannot be compared directly with the analyzer's resolved
    module name. Their explicit module component must nevertheless match the
    resolved suffix; unqualified relative imports are intentionally skipped
    because they do not provide a stable enough context for source relocation.
    """
    if node.module is None:
        return False
    if node.level == 0:
        return node.module == candidate.imported_module
    return (
        candidate.imported_module == node.module
        or candidate.imported_module.endswith(f".{node.module}")
    )


def _bound_name(node: ast.Import | ast.ImportFrom, alias: ast.alias) -> str:
    """Return the name introduced by one concrete import alias."""
    if alias.asname is not None:
        return alias.asname
    return alias.name.split(".")[0] if isinstance(node, ast.Import) else alias.name


def _safe_statement(source: str, node: ast.AST) -> bool:
    """Reject source spans whose comments or semicolons would be discarded."""
    lines = source.splitlines(keepends=True)[node.lineno - 1 : node.end_lineno]
    return node.col_offset == 0 and all(
        "#" not in line and ";" not in line for line in lines
    )


def _render_import(node: ast.Import | ast.ImportFrom, aliases: list[ast.alias]) -> str:
    names = ", ".join(
        alias.name if alias.asname is None else f"{alias.name} as {alias.asname}"
        for alias in aliases
    )
    if not aliases:
        return ""
    if isinstance(node, ast.Import):
        return f"import {names}"
    return f"from {'.' * node.level + (node.module or '')} import {names}"


def _render_all_edit(source: str, node: ast.Assign, removed: set[str]) -> _Edit | None:
    """Render one literal static ``__all__`` update in UTF-8 byte offsets."""
    value = node.value
    if not isinstance(value, ast.List | ast.Tuple):
        return None
    names = [
        item.value
        for item in value.elts
        if isinstance(item, ast.Constant) and isinstance(item.value, str)
    ]
    if len(names) != len(value.elts):
        return None
    retained_names = [name for name in names if name not in removed]
    rendered_value: list[str] | tuple[str, ...]
    if isinstance(value, ast.List):
        rendered_value = retained_names
    else:
        rendered_value = tuple(retained_names)
    return _Edit(
        *_byte_range(source, node),
        f"__all__ = {rendered_value!r}".encode(),
    )


def _is_all(node: ast.stmt) -> bool:
    """Return whether one supported statement safely assigns ``__all__``.

    Annotated assignments would require preserving their annotation exactly.
    Multiple targets would require preserving another binding. Both are outside
    this source-local renderer's narrow contract and are skipped.
    """
    if not isinstance(node, ast.Assign) or len(node.targets) != 1:
        return False
    target = node.targets[0]
    return isinstance(target, ast.Name) and target.id == "__all__"


def _byte_range(source: str, node: ast.AST) -> tuple[int, int]:
    """Return UTF-8 byte offsets compatible with Python AST columns."""
    lines = source.splitlines(keepends=True)
    start = len("".join(lines[: node.lineno - 1]).encode("utf-8")) + node.col_offset
    end = (
        len("".join(lines[: node.end_lineno - 1]).encode("utf-8")) + node.end_col_offset
    )
    return start, end


def _line_end(source: bytes, offset: int) -> int:
    """Return the offset after an optional platform-neutral line ending."""
    if source.startswith(b"\r\n", offset):
        return offset + 2
    if source.startswith(b"\n", offset):
        return offset + 1
    return offset


def _has_dynamic_all_mutation(tree: ast.Module) -> bool:
    """Conservatively reject writes or method calls that mutate ``__all__``."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            if any(_is_indirect_all_target(target) for target in node.targets):
                return True
        if isinstance(node, ast.AnnAssign) and _is_indirect_all_target(node.target):
            return True
        if isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name):
            if node.target.id == "__all__":
                return True
        if isinstance(node, ast.AugAssign) and _is_indirect_all_target(node.target):
            return True
        if isinstance(node, ast.Delete) and any(
            _references_all_target(target) for target in node.targets
        ):
            return True
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if (
                isinstance(node.func.value, ast.Name)
                and node.func.value.id == "__all__"
            ):
                return True
    return False


def _references_all_target(node: ast.expr) -> bool:
    """Return whether an assignment-like target starts from ``__all__``."""
    if isinstance(node, ast.Name):
        return node.id == "__all__"
    if isinstance(node, ast.Subscript):
        return _references_all_target(node.value)
    if isinstance(node, ast.Attribute):
        return _references_all_target(node.value)
    return False


def _is_indirect_all_target(node: ast.expr) -> bool:
    """Distinguish the supported direct assignment from other ``__all__`` writes."""
    return _references_all_target(node) and not (
        isinstance(node, ast.Name) and node.id == "__all__"
    )


def _has_overlapping_edits(edits: list[_Edit]) -> bool:
    """Return whether byte ranges overlap after the shared-plan merge."""
    previous_end = -1
    for edit in sorted(edits, key=lambda item: item.start):
        if edit.start < previous_end:
            return True
        previous_end = edit.end
    return False


def _apply(root: Path, plan: _EditPlan) -> dict[str, bytes]:
    """Apply one complete byte-edit plan and retain exact rollback bytes."""
    originals: dict[str, bytes] = {}
    for path, _ in plan.edits_by_path:
        source_path = root / path
        originals[path] = source_path.read_bytes()
    try:
        for path, edits in plan.edits_by_path:
            source = originals[path]
            for edit in sorted(edits, key=lambda item: item.start, reverse=True):
                source = source[: edit.start] + edit.replacement + source[edit.end :]
            (root / path).write_bytes(source)
    except OSError:
        _restore(root, originals)
        raise
    return originals


def _restore(root: Path, originals: dict[str, bytes]) -> None:
    """Restore exact original bytes for an unaccepted atomic edit plan."""
    for path, source in originals.items():
        (root / path).write_bytes(source)


def _line_count(root: Path) -> int:
    return _python_line_count(_python_files(root, DEFAULT_IGNORED_DIRECTORY_NAMES))


def _normalize_expected_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = " ".join(value.split())
    if not normalized:
        raise ValueError("expected_text must not be blank")
    return normalized


def format_import_pruning_summary(result: ImportPruningResult) -> str:
    """Format concise, user-facing metrics for a completed pruning run."""
    return "\n".join(
        (
            "Import pruning:",
            f"Candidates discovered: {result.candidates_discovered}",
            f"Editable operations: {result.editable_operations}",
            f"Skipped candidates: {result.skipped_candidates}",
            f"Candidate probes: {result.candidate_attempts}",
            f"Accepted probes: {result.accepted_probes}",
            f"Rejected probes: {result.rejected_probes}",
            f"Oracle executions: {result.executions}",
            "Python LOC: "
            f"{result.initial_python_lines} -> {result.remaining_python_lines}",
            f"Wall-clock seconds: {result.wall_clock_seconds:.3f}",
            f"Original modified: {'yes' if not result.source_unchanged else 'no'}",
        )
    )
