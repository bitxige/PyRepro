"""Execution-verified prototype for deleting complete ordinary ``if`` statements.

The experiment considers only source lines that begin with ``if`` (not
``elif``), inside top-level functions and direct methods. Static AST structure
locates source ranges, while the established execution oracle alone accepts or
rejects each deletion.
"""

from __future__ import annotations

import ast
import hashlib
import io
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
class IfStatementCandidate:
    """One complete source ``if`` statement eligible for a deletion probe."""

    file_path: str
    owner_qualified_name: str
    owner_kind: str
    start_line: int
    end_line: int
    source_digest: str
    requires_pass: bool
    control_path: tuple[str, ...] = ()

    @property
    def identity(self) -> tuple[str, str, str, str]:
        """Return a position-independent identity for rejected-probe suppression."""
        return (
            self.file_path,
            self.owner_qualified_name,
            "if_statement",
            self.source_digest,
        )

    @property
    def source_span(self) -> int:
        """Return the inclusive physical span of the complete statement."""
        return self.end_line - self.start_line + 1


class IfStatementOrder(str, Enum):
    """Deterministic candidate orderings for the complete-if prototype."""

    DISCOVERY = "discovery"
    SPAN_DESC = "span-desc"


@dataclass(frozen=True)
class IfStatementDiscovery:
    """Current complete-if candidates found in one source file."""

    candidates: tuple[IfStatementCandidate, ...]
    skipped: bool


@dataclass(frozen=True)
class IfStatementReductionResult:
    """Verified outcome metrics from one greedy complete-if experiment."""

    baseline_signature: FailureSignature
    initial_python_lines: int
    remaining_python_lines: int
    initial_candidates: int
    remaining_candidates: int
    candidate_attempts: int
    accepted_removals: int
    rejected_probes: int
    executions: int
    source_unchanged: bool
    probe_records: tuple[ProbeRecord, ...]
    skipped_unparsable_files: tuple[str, ...]
    wall_clock_seconds: float
    budget_exhausted: bool = False


class GreedyIfStatementReducer:
    """Greedily verify deleting complete ordinary ``if`` statements.

    This deliberately narrow prototype excludes actual ``elif`` source lines,
    loop and exception statements, module/class bodies, nested definitions,
    and source ranges containing comments or semicolon chains. When the target
    is its direct parent suite's sole statement, deletion is replaced with a
    same-indentation ``pass`` to preserve valid syntax.
    """

    def __init__(
        self,
        runner: CommandRunner,
        match_mode: FailureMatchMode = FailureMatchMode.STRICT,
        ignored_directory_names: Collection[str] = DEFAULT_IGNORED_DIRECTORY_NAMES,
        *,
        max_probes: int | None = None,
        candidate_order: IfStatementOrder = IfStatementOrder.DISCOVERY,
    ) -> None:
        """Initialize the bounded complete-if reducer."""
        if max_probes is not None and max_probes < 0:
            raise ValueError("max_probes must not be negative")
        self.runner = runner
        self.match_mode = match_mode
        self.ignored_directory_names = frozenset(ignored_directory_names)
        self.max_probes = max_probes
        self.candidate_order = candidate_order

    def reduce(
        self,
        workspace: ReductionWorkspace,
        baseline_signature: FailureSignature,
        *,
        budget: ExecutionBudget | None = None,
        verify_final: bool = True,
    ) -> IfStatementReductionResult:
        """Run bounded, execution-verified complete-if deletion in a workspace."""
        started_at = perf_counter()
        initial_files = _python_files(workspace.root, self.ignored_directory_names)
        initial_candidates, skipped_paths = _discover_workspace_ifs(
            workspace.root, initial_files
        )
        rejected: set[tuple[str, str, str, str]] = set()
        records: list[ProbeRecord] = []
        accepted = 0
        budget_exhausted = False

        while self.max_probes is None or len(records) < self.max_probes:
            if budget is not None and not budget.can_start_probe():
                budget_exhausted = True
                break
            files = _python_files(workspace.root, self.ignored_directory_names)
            candidates, skipped = _discover_workspace_ifs(workspace.root, files)
            skipped_paths.update(skipped)
            candidate = next(
                (
                    item
                    for item in _order_candidates(candidates, self.candidate_order)
                    if item.identity not in rejected
                ),
                None,
            )
            if candidate is None:
                break
            try:
                outcome, record = self._probe_candidate(
                    workspace.root, candidate, baseline_signature, budget
                )
            except BudgetExhaustedError:
                budget_exhausted = True
                break
            records.append(record)
            if outcome is ReductionOutcome.SAME_FAILURE:
                _remove_if_statement(workspace.root / candidate.file_path, candidate)
                accepted += 1
            else:
                rejected.add(candidate.identity)

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
                    "final complete-if verification did not match baseline"
                )
        remaining_files = _python_files(workspace.root, self.ignored_directory_names)
        remaining_candidates, skipped = _discover_workspace_ifs(
            workspace.root, remaining_files
        )
        skipped_paths.update(skipped)
        return IfStatementReductionResult(
            baseline_signature=baseline_signature,
            initial_python_lines=_python_line_count(initial_files),
            remaining_python_lines=_python_line_count(remaining_files),
            initial_candidates=len(initial_candidates),
            remaining_candidates=len(remaining_candidates),
            candidate_attempts=len(records),
            accepted_removals=accepted,
            rejected_probes=len(records) - accepted,
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
        candidate: IfStatementCandidate,
        baseline_signature: FailureSignature,
        budget: ExecutionBudget | None,
    ) -> tuple[ReductionOutcome, ProbeRecord]:
        """Probe one complete-if deletion in a disposable project copy."""
        if budget is not None:
            budget.ensure_can_start(OracleExecutionKind.PROBE)
        with tempfile.TemporaryDirectory(prefix="pyrepro-if-statement-probe-") as name:
            probe_root = Path(name) / "project"
            shutil.copytree(workspace_root, probe_root)
            _remove_if_statement(probe_root / candidate.file_path, candidate)
            started_at = perf_counter()
            result = _run_oracle(
                self.runner, probe_root, budget, OracleExecutionKind.PROBE
            )
            duration = perf_counter() - started_at
            outcome = classify_result(
                result, baseline_signature, probe_root, self.match_mode
            )
            return outcome, _probe_record(
                "if_statement",
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
                    f"{candidate.file_path}:{candidate.owner_qualified_name}:"
                    f"{candidate.start_line}-{candidate.end_line}:if_statement:"
                    f"{'/'.join(candidate.control_path) or 'direct'}:"
                    f"requires_pass={candidate.requires_pass}",
                ),
                candidate_rolled_back=outcome is not ReductionOutcome.SAME_FAILURE,
            )


def discover_if_statements(path: Path, workspace_root: Path) -> IfStatementDiscovery:
    """Discover source-safe complete ordinary ``if`` statement candidates.

    AST represents `elif` as an ``If`` inside a predecessor's ``orelse``. This
    function checks the original source header and deliberately skips such
    nodes, so the prototype only deletes source statements beginning with
    ``if``. Candidate source spans include any associated elif/else chain.
    """
    try:
        content, _encoding = _read_source(path)
        lines = content.splitlines(keepends=True)
        tree = ast.parse(content, filename=str(path))
        tokens = tuple(tokenize.generate_tokens(io.StringIO(content).readline))
    except (OSError, SyntaxError, UnicodeError, tokenize.TokenError):
        return IfStatementDiscovery((), skipped=True)
    relative = path.relative_to(workspace_root).as_posix()
    candidates: list[IfStatementCandidate] = []
    for owner, name, kind in _direct_owners(tree):
        _discover_in_suite(
            list(owner.body),
            content=content,
            lines=lines,
            tokens=tokens,
            relative=relative,
            owner_name=name,
            owner_kind=kind,
            control_path=(),
            candidates=candidates,
        )
    return IfStatementDiscovery(tuple(candidates), skipped=False)


def _discover_in_suite(
    statements: list[ast.stmt],
    *,
    content: str,
    lines: list[str],
    tokens: Collection[tokenize.TokenInfo],
    relative: str,
    owner_name: str,
    owner_kind: str,
    control_path: tuple[str, ...],
    candidates: list[IfStatementCandidate],
) -> None:
    """Recursively discover source ``if`` nodes without entering definitions."""
    for statement in statements:
        if isinstance(statement, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            continue
        if isinstance(statement, ast.If):
            is_elif = lines[statement.lineno - 1].lstrip().startswith("elif")
            current = (
                *control_path,
                f"{'elif' if is_elif else 'if'}@{statement.lineno}",
            )
            if not is_elif:
                candidate = _if_candidate(
                    statement,
                    content=content,
                    tokens=tokens,
                    relative=relative,
                    owner_name=owner_name,
                    owner_kind=owner_kind,
                    parent_suite=statements,
                    control_path=current,
                )
                if candidate is not None:
                    candidates.append(candidate)
            _discover_in_suite(
                statement.body,
                content=content,
                lines=lines,
                tokens=tokens,
                relative=relative,
                owner_name=owner_name,
                owner_kind=owner_kind,
                control_path=current,
                candidates=candidates,
            )
            _discover_in_suite(
                statement.orelse,
                content=content,
                lines=lines,
                tokens=tokens,
                relative=relative,
                owner_name=owner_name,
                owner_kind=owner_kind,
                control_path=current,
                candidates=candidates,
            )
        elif isinstance(statement, ast.For | ast.AsyncFor | ast.While):
            kind = _control_kind(statement)
            current = (*control_path, f"{kind}@{statement.lineno}")
            _discover_in_suite(
                statement.body,
                content=content,
                lines=lines,
                tokens=tokens,
                relative=relative,
                owner_name=owner_name,
                owner_kind=owner_kind,
                control_path=current,
                candidates=candidates,
            )
            _discover_in_suite(
                statement.orelse,
                content=content,
                lines=lines,
                tokens=tokens,
                relative=relative,
                owner_name=owner_name,
                owner_kind=owner_kind,
                control_path=current,
                candidates=candidates,
            )
        elif isinstance(statement, ast.Try):
            current = (*control_path, f"try@{statement.lineno}")
            _discover_in_suite(
                statement.body,
                content=content,
                lines=lines,
                tokens=tokens,
                relative=relative,
                owner_name=owner_name,
                owner_kind=owner_kind,
                control_path=current,
                candidates=candidates,
            )
            _discover_in_suite(
                statement.orelse,
                content=content,
                lines=lines,
                tokens=tokens,
                relative=relative,
                owner_name=owner_name,
                owner_kind=owner_kind,
                control_path=current,
                candidates=candidates,
            )
            _discover_in_suite(
                statement.finalbody,
                content=content,
                lines=lines,
                tokens=tokens,
                relative=relative,
                owner_name=owner_name,
                owner_kind=owner_kind,
                control_path=current,
                candidates=candidates,
            )
            for index, handler in enumerate(statement.handlers, start=1):
                _discover_in_suite(
                    handler.body,
                    content=content,
                    lines=lines,
                    tokens=tokens,
                    relative=relative,
                    owner_name=owner_name,
                    owner_kind=owner_kind,
                    control_path=(*current, f"except[{index}]@{handler.lineno}"),
                    candidates=candidates,
                )
        elif isinstance(statement, ast.With | ast.AsyncWith):
            kind = _control_kind(statement)
            _discover_in_suite(
                statement.body,
                content=content,
                lines=lines,
                tokens=tokens,
                relative=relative,
                owner_name=owner_name,
                owner_kind=owner_kind,
                control_path=(*control_path, f"{kind}@{statement.lineno}"),
                candidates=candidates,
            )


def _if_candidate(
    statement: ast.If,
    *,
    content: str,
    tokens: Collection[tokenize.TokenInfo],
    relative: str,
    owner_name: str,
    owner_kind: str,
    parent_suite: list[ast.stmt],
    control_path: tuple[str, ...],
) -> IfStatementCandidate | None:
    """Build one candidate when a complete if source span is safe to edit."""
    if statement.end_lineno is None:
        return None
    if _contains_unsafe_token(tokens, statement.lineno, statement.end_lineno):
        return None
    text = _source_span_text(content, statement.lineno, statement.end_lineno)
    return IfStatementCandidate(
        file_path=relative,
        owner_qualified_name=owner_name,
        owner_kind=owner_kind,
        start_line=statement.lineno,
        end_line=statement.end_lineno,
        source_digest=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        requires_pass=len(parent_suite) == 1,
        control_path=control_path,
    )


def _direct_owners(tree: ast.Module):
    """Yield top-level functions and direct methods of top-level classes."""
    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            kind = (
                "async_function"
                if isinstance(node, ast.AsyncFunctionDef)
                else "function"
            )
            yield node, node.name, kind
        elif isinstance(node, ast.ClassDef):
            for child in node.body:
                if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                    kind = (
                        "async_method"
                        if isinstance(child, ast.AsyncFunctionDef)
                        else "method"
                    )
                    yield child, f"{node.name}.{child.name}", kind


def _control_kind(node: ast.AST) -> str:
    """Return stable telemetry text for a non-candidate enclosing construct."""
    if isinstance(node, ast.AsyncFor):
        return "async_for"
    if isinstance(node, ast.AsyncWith):
        return "async_with"
    return type(node).__name__.lower()


def _read_source(path: Path) -> tuple[str, str]:
    """Read source without normalizing its declared encoding or newlines."""
    data = path.read_bytes()
    encoding, _ = tokenize.detect_encoding(io.BytesIO(data).readline)
    return data.decode(encoding), encoding


def _contains_unsafe_token(
    tokens: Collection[tokenize.TokenInfo], start_line: int, end_line: int
) -> bool:
    """Reject ranges containing comment or semicolon source that AST omits."""
    return any(
        start_line <= token.start[0] <= end_line
        and (
            token.type == tokenize.COMMENT
            or (token.type == tokenize.OP and token.string == ";")
        )
        for token in tokens
    )


def _source_span_text(content: str, start_line: int, end_line: int) -> str:
    """Return an inclusive source span without altering newline sequences."""
    return "".join(content.splitlines(keepends=True)[start_line - 1 : end_line])


def _remove_if_statement(path: Path, candidate: IfStatementCandidate) -> None:
    """Remove one complete if span, or replace it with an indented ``pass``."""
    content, encoding = _read_source(path)
    lines = content.splitlines(keepends=True)
    if candidate.requires_pass:
        header = lines[candidate.start_line - 1]
        indent = header[: len(header) - len(header.lstrip(" \t"))]
        newline = "\r\n" if header.endswith("\r\n") else "\n"
        replacement = [f"{indent}pass{newline}"]
    else:
        replacement = []
    lines[candidate.start_line - 1 : candidate.end_line] = replacement
    path.write_bytes("".join(lines).encode(encoding))


def _discover_workspace_ifs(
    workspace_root: Path, paths: Collection[Path]
) -> tuple[tuple[IfStatementCandidate, ...], set[str]]:
    """Discover current complete-if candidates in a disposable workspace."""
    candidates: list[IfStatementCandidate] = []
    skipped_paths: set[str] = set()
    for path in paths:
        discovery = discover_if_statements(path, workspace_root)
        candidates.extend(discovery.candidates)
        if discovery.skipped:
            skipped_paths.add(path.relative_to(workspace_root).as_posix())
    return tuple(candidates), skipped_paths


def _order_candidates(
    candidates: Collection[IfStatementCandidate], order: IfStatementOrder
) -> tuple[IfStatementCandidate, ...]:
    """Return deterministic complete-if candidates in the configured order."""
    if order is IfStatementOrder.DISCOVERY:
        return tuple(candidates)
    if order is IfStatementOrder.SPAN_DESC:
        return tuple(
            sorted(
                candidates,
                key=lambda candidate: (
                    -candidate.source_span,
                    candidate.file_path,
                    candidate.owner_qualified_name,
                    candidate.start_line,
                    candidate.end_line,
                    candidate.source_digest,
                ),
            )
        )
    raise ValueError(f"unsupported complete-if order: {order}")
