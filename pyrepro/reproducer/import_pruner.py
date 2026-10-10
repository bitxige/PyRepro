"""Execution-verified, bounded batch pruning of target-aware import candidates."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter

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
    _verify_final_workspace,
)
from pyrepro.reproducer.runner import CommandRunner
from pyrepro.reproducer.workspace import ReductionWorkspace
from pyrepro.scanner.import_analyzer import ImportAnalyzer, ImportCandidate


@dataclass(frozen=True)
class ImportPruningResult:
    """Final-verified result of a target-aware import-pruning run."""

    baseline_signature: FailureSignature
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


@dataclass(frozen=True)
class _Edit:
    start: int
    end: int
    replacement: str


@dataclass(frozen=True)
class _Operation:
    candidates: tuple[ImportCandidate, ...]
    edits_by_path: tuple[tuple[str, tuple[_Edit, ...]], ...]

    @property
    def paths(self) -> tuple[str, ...]:
        return tuple(sorted({candidate.path for candidate in self.candidates}))

    @property
    def descriptions(self) -> tuple[str, ...]:
        return tuple(
            f"{candidate.path}:{candidate.line}:{candidate.bound_name}"
            for candidate in self.candidates
        )


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

    def prune(self, workspace: ReductionWorkspace) -> ImportPruningResult:
        """Run baseline, bounded batch probes, rollback, and final verification."""
        started = perf_counter()
        baseline, executions = _establish_baseline(
            self.runner,
            workspace.root,
            self.baseline_runs,
            self.expected_text,
            self.match_mode,
        )
        analysis = ImportAnalyzer(workspace.root).analyze_pytest_node(self.pytest_node)
        operations, skipped = _build_operations(workspace.root, analysis.candidates)
        initial_lines = _line_count(workspace.root)
        records: list[ProbeRecord] = []
        accepted = rejected = 0
        low_risk = tuple(
            operation
            for operation in operations
            if all(candidate.risk_reason is None for candidate in operation.candidates)
        )
        risk_marked = tuple(op for op in operations if op not in low_risk)
        for batch in (low_risk, risk_marked):
            if batch and len(records) < self.max_probes:
                new_records, new_accepted, new_rejected = self._search(
                    workspace.root, batch, baseline, self.max_probes - len(records)
                )
                records.extend(new_records)
                accepted += new_accepted
                rejected += new_rejected
        executions += len(records)
        if (
            _verify_final_workspace(
                self.runner, workspace.root, baseline, self.match_mode
            )
            is not ReductionOutcome.SAME_FAILURE
        ):
            raise UnstableBaselineError(
                "final import-pruning verification did not match baseline"
            )
        return ImportPruningResult(
            baseline_signature=baseline,
            candidates_discovered=len(analysis.candidates),
            editable_operations=len(operations),
            skipped_candidates=skipped,
            candidate_attempts=len(records),
            accepted_probes=accepted,
            rejected_probes=rejected,
            executions=executions + 1,
            initial_python_lines=initial_lines,
            remaining_python_lines=_line_count(workspace.root),
            wall_clock_seconds=perf_counter() - started,
            probe_records=tuple(records),
            source_unchanged=workspace.source_is_unchanged(),
        )

    def _search(
        self,
        root: Path,
        operations: tuple[_Operation, ...],
        baseline: FailureSignature,
        budget: int,
    ) -> tuple[list[ProbeRecord], int, int]:
        """Try one batch, then split rejected batches while budget remains."""
        if not operations or budget <= 0:
            return [], 0, 0
        record, accepted = self._probe(root, operations, baseline)
        records = [record]
        if accepted:
            return records, 1, 0
        if len(operations) == 1 or budget == 1:
            return records, 0, 1
        split = len(operations) // 2
        left, left_yes, left_no = self._search(
            root, operations[:split], baseline, budget - 1
        )
        records.extend(left)
        if len(records) < budget:
            right, right_yes, right_no = self._search(
                root, operations[split:], baseline, budget - len(records)
            )
            records.extend(right)
        else:
            right_yes = right_no = 0
        return records, left_yes + right_yes, left_no + right_no + 1

    def _probe(
        self,
        root: Path,
        operations: tuple[_Operation, ...],
        baseline: FailureSignature,
    ) -> tuple[ProbeRecord, bool]:
        originals = _apply(root, operations)
        started = perf_counter()
        execution = self.runner.run(root)
        duration = perf_counter() - started
        outcome = classify_result(execution, baseline, root, self.match_mode)
        proposed_lines = _line_count(root)
        accepted = outcome is ReductionOutcome.SAME_FAILURE
        if not accepted:
            _restore(root, originals)
        details = exception_details(execution)
        error_type, error_message = details or (None, None)
        return (
            ProbeRecord(
                phase="import_pruning",
                candidate_paths=tuple(
                    sorted(
                        {path for operation in operations for path in operation.paths}
                    )
                ),
                candidate_descriptions=tuple(
                    item for operation in operations for item in operation.descriptions
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


def _build_operations(
    root: Path, candidates: tuple[ImportCandidate, ...]
) -> tuple[tuple[_Operation, ...], int]:
    grouped: dict[tuple[str, int], list[ImportCandidate]] = {}
    for candidate in candidates:
        grouped.setdefault((candidate.path, candidate.line), []).append(candidate)
    operations: list[_Operation] = []
    skipped = 0
    for (path, line), group in grouped.items():
        operation = _operation(root, path, line, tuple(group))
        if operation is None:
            skipped += len(group)
        else:
            operations.append(operation)
    return tuple(operations), skipped


def _operation(
    root: Path, path: str, line: int, candidates: tuple[ImportCandidate, ...]
) -> _Operation | None:
    source = (root / path).read_text(encoding="utf-8")
    tree = ast.parse(source, filename=path)
    node = next(
        (
            item
            for item in tree.body
            if isinstance(item, ast.Import | ast.ImportFrom) and item.lineno == line
        ),
        None,
    )
    if node is None or node.end_lineno != node.lineno or not _safe_line(source, node):
        return None
    removed = {candidate.bound_name for candidate in candidates}
    aliases = [
        alias
        for alias in node.names
        if (alias.asname or alias.name.split(".")[0]) not in removed
    ]
    if len(aliases) == len(node.names):
        return None
    start, end = _range(source, node)
    if not aliases:
        end = _line_end(source, end)
    edits = [_Edit(start, end, _render_import(node, aliases))]
    all_candidates = [item for item in candidates if item.all_line is not None]
    if all_candidates:
        all_edit = _render_all_edit(source, tree, all_candidates)
        if all_edit is None:
            return None
        edits.append(all_edit)
    return _Operation(candidates, ((path, tuple(edits)),))


def _safe_line(source: str, node: ast.Import | ast.ImportFrom) -> bool:
    line = source.splitlines(keepends=True)[node.lineno - 1]
    return node.col_offset == 0 and "#" not in line and ";" not in line


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


def _render_all_edit(
    source: str, tree: ast.Module, candidates: list[ImportCandidate]
) -> _Edit | None:
    lines = {candidate.all_line for candidate in candidates}
    if len(lines) != 1:
        return None
    line = next(iter(lines))
    node = next(
        (
            item
            for item in tree.body
            if isinstance(item, ast.Assign | ast.AnnAssign)
            and item.lineno == line
            and _is_all(item)
        ),
        None,
    )
    if node is None or node.end_lineno != node.lineno:
        return None
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
    removed = {candidate.bound_name for candidate in candidates}
    return _Edit(
        *_range(source, node),
        f"__all__ = {[name for name in names if name not in removed]!r}",
    )


def _is_all(node: ast.Assign | ast.AnnAssign) -> bool:
    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
    return any(
        isinstance(target, ast.Name) and target.id == "__all__" for target in targets
    )


def _range(source: str, node: ast.AST) -> tuple[int, int]:
    lines = source.splitlines(keepends=True)
    start = sum(len(line) for line in lines[: node.lineno - 1]) + node.col_offset
    end = sum(len(line) for line in lines[: node.end_lineno - 1]) + node.end_col_offset
    return start, end


def _line_end(source: str, offset: int) -> int:
    """Return the offset after an optional platform-neutral line ending."""
    if source.startswith("\r\n", offset):
        return offset + 2
    if source.startswith("\n", offset):
        return offset + 1
    return offset


def _apply(root: Path, operations: tuple[_Operation, ...]) -> dict[str, str]:
    edits_by_path: dict[str, list[_Edit]] = {}
    for operation in operations:
        for path, edits in operation.edits_by_path:
            edits_by_path.setdefault(path, []).extend(edits)
    originals: dict[str, str] = {}
    for path, edits in edits_by_path.items():
        source_path = root / path
        source = source_path.read_text(encoding="utf-8")
        originals[path] = source
        for edit in sorted(edits, key=lambda item: item.start, reverse=True):
            source = source[: edit.start] + edit.replacement + source[edit.end :]
        source_path.write_text(source, encoding="utf-8")
    return originals


def _restore(root: Path, originals: dict[str, str]) -> None:
    for path, source in originals.items():
        (root / path).write_text(source, encoding="utf-8")


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
