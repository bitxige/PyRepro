"""Compose verified import preprocessing with existing file reduction."""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter

from pyrepro.reproducer.budget import ExecutionBudget
from pyrepro.reproducer.coarse_reducer import CoarseFileReducer, CoarseReductionResult
from pyrepro.reproducer.container_entry_reducer import (
    ContainerEntryReductionResult,
    GreedyContainerEntryReducer,
)
from pyrepro.reproducer.failure import FailureMatchMode, FailureSignature
from pyrepro.reproducer.if_statement_reducer import (
    GreedyIfStatementReducer,
    IfStatementOrder,
    IfStatementReductionResult,
)
from pyrepro.reproducer.import_pruner import BatchImportPruner, ImportPruningResult
from pyrepro.reproducer.list_entry_reducer import (
    GreedyListEntryReducer,
    ListEntryReductionResult,
)
from pyrepro.reproducer.main_guard_reducer import (
    GreedyMainGuardReducer,
    MainGuardReductionResult,
)
from pyrepro.reproducer.nested_palette_reducer import (
    GreedyNestedPaletteReducer,
    NestedPaletteReductionResult,
)
from pyrepro.reproducer.reducer import (
    DEFAULT_IGNORED_DIRECTORY_NAMES,
    GreedyFileReducer,
    ProbeRecord,
    ReductionResult,
    _python_files,
    _python_line_count,
)
from pyrepro.reproducer.runner import CommandRunner
from pyrepro.reproducer.symbol_reducer import (
    GreedySymbolReducer,
    SymbolOrder,
    SymbolReductionResult,
    SymbolScope,
)
from pyrepro.reproducer.workspace import ReductionWorkspace

PRODUCTION_REDUCER_STAGE_ORDER = (
    "import_pruning",
    "coarse",
    "file",
    "symbol",
    "method",
    "if_statement",
    "container_entry",
    "list_entry",
    "main_guard",
    "nested_list_entry",
)


def _stage_enabled(max_probes: int | None) -> bool:
    """Return whether a stage is enabled for bounded or unbounded search."""
    return max_probes is None or max_probes > 0


@dataclass(frozen=True)
class PreprocessingReductionResult:
    """Results for import preprocessing followed by greedy file reduction."""

    import_pruning: ImportPruningResult
    coarse_reduction: CoarseReductionResult | None
    file_reduction: ReductionResult
    symbol_reduction: SymbolReductionResult | None
    method_reduction: SymbolReductionResult | None
    if_statement_reduction: IfStatementReductionResult | None
    container_entry_reduction: ContainerEntryReductionResult | None
    list_entry_reduction: ListEntryReductionResult | None
    main_guard_reduction: MainGuardReductionResult | None
    nested_list_entry_reduction: NestedPaletteReductionResult | None
    executions: int
    wall_clock_seconds: float
    probe_records: tuple[ProbeRecord, ...]
    source_unchanged: bool
    budget_exhausted: bool = False


@dataclass(frozen=True)
class PipelineProbeLimits:
    """Per-stage probe limits for one shared production reducer pipeline.

    ``None`` means unbounded search for Standard Mode; zero disables a stage.
    Positive limits are consumed across all Fast-Mode sweeps, rather than
    renewed every time a later edit triggers pipeline rediscovery.
    """

    import_pruning: int | None = 16
    coarse: int | None = 16
    symbol: int | None = 0
    method: int | None = 0
    if_statement: int | None = 0
    container_entry: int | None = 0
    list_entry: int | None = 0
    main_guard: int | None = 0
    nested_list_entry: int | None = 0

    def remaining(self, consumed: dict[str, int], stage: str) -> int | None:
        """Return the unspent limit for one stage in the current sweep."""
        configured = getattr(self, stage)
        if configured is None:
            return None
        return max(0, configured - consumed.get(stage, 0))


@dataclass(frozen=True)
class PipelineReductionResult:
    """Aggregate all sweeps of the shared production reducer pipeline."""

    baseline_signature: FailureSignature
    sweeps: tuple[PreprocessingReductionResult, ...]
    baseline_executions: int
    search_executions: int
    executions: int
    wall_clock_seconds: float
    probe_records: tuple[ProbeRecord, ...]
    source_unchanged: bool
    budget_exhausted: bool
    fixed_point_reached: bool
    limits: PipelineProbeLimits


class PreprocessingFirstReducer:
    """Run one ordered sweep of the shared production reducer pipeline.

    The import stage is fully verified before the existing greedy reducer sees
    the workspace. Static candidate facts remain advisory in the import stage;
    the runtime failure oracle remains the acceptance authority throughout.
    """

    def __init__(
        self,
        runner: CommandRunner,
        pytest_node: str,
        *,
        expected_text: str | None = None,
        match_mode: FailureMatchMode = FailureMatchMode.STRICT,
        max_import_probes: int | None = 16,
        max_coarse_probes: int | None = 0,
        max_symbol_probes: int | None = 0,
        max_method_probes: int | None = 0,
        max_if_statement_probes: int | None = 0,
        max_container_entry_probes: int | None = 0,
        max_list_entry_probes: int | None = 0,
        max_main_guard_probes: int | None = 0,
        max_nested_list_entry_probes: int | None = 0,
        symbol_order: SymbolOrder = SymbolOrder.DISCOVERY,
    ) -> None:
        """Configure the preprocessing-first reduction pipeline.

        Args:
            runner: Trusted argv runner used by both stages.
            pytest_node: Conventional pytest node used only for static scope.
            expected_text: Optional baseline-signature text anchor.
            match_mode: Failure identity used by both stages.
            max_import_probes: Bound for import batch probes.
            max_coarse_probes: Bound for optional directory-group probes before
                greedy cleanup. Zero preserves import-pruning then greedy-only
                behavior.
            max_symbol_probes: Bound for optional complete-symbol probes after
                file cleanup. Zero preserves the existing Fast Mode pipeline.
            max_method_probes: Bound for optional direct-method probes after
                complete-symbol reduction. Zero preserves the existing Fast
                Mode pipeline.
            max_if_statement_probes: Bound for experimental complete-source-if
                probes after direct-method reduction. Zero preserves the
                existing Fast Mode pipeline.
            max_container_entry_probes: Bound for experimental static
                module-dictionary entry probes after complete-if reduction.
                Zero preserves the existing Fast Mode pipeline.
            max_list_entry_probes: Bound for experimental static module-list
                entry probes after module-dictionary reduction. Zero preserves
                the existing Fast Mode pipeline.
            max_main_guard_probes: Bound for experimental direct module-level
                main-guard probes after module-list reduction. Zero preserves
                the existing Fast Mode pipeline.
            max_nested_list_entry_probes: Bound for experimental nested
                ``Palette([...])`` RGB-list entry probes after direct
                module-level main-guard reduction. Zero preserves the existing
                Fast Mode pipeline.
            symbol_order: Deterministic order used only when symbol probes are
                enabled.
        """
        self.runner = runner
        self.pytest_node = pytest_node
        self.expected_text = expected_text
        self.match_mode = match_mode
        self.max_import_probes = max_import_probes
        self.max_coarse_probes = max_coarse_probes
        self.max_symbol_probes = max_symbol_probes
        self.max_method_probes = max_method_probes
        self.max_if_statement_probes = max_if_statement_probes
        self.max_container_entry_probes = max_container_entry_probes
        self.max_list_entry_probes = max_list_entry_probes
        self.max_main_guard_probes = max_main_guard_probes
        self.max_nested_list_entry_probes = max_nested_list_entry_probes
        self.symbol_order = symbol_order

    def reduce(
        self,
        workspace: ReductionWorkspace,
        *,
        budget: ExecutionBudget | None = None,
        verify_stage_finals: bool | None = None,
        baseline_signature: FailureSignature | None = None,
    ) -> PreprocessingReductionResult:
        """Run composed stages with one baseline and optional shared budget."""
        started = perf_counter()
        if verify_stage_finals is None:
            verify_stage_finals = budget is None
        if _stage_enabled(self.max_import_probes):
            import_result = BatchImportPruner(
                self.runner,
                self.pytest_node,
                expected_text=self.expected_text,
                match_mode=self.match_mode,
                max_probes=self.max_import_probes,
            ).prune(
                workspace,
                baseline_signature,
                budget=budget,
                verify_final=verify_stage_finals,
            )
        else:
            if baseline_signature is None:
                raise ValueError("the first pipeline sweep must establish a baseline")
            lines = _python_line_count(
                _python_files(workspace.root, DEFAULT_IGNORED_DIRECTORY_NAMES)
            )
            import_result = ImportPruningResult(
                baseline_signature=baseline_signature,
                baseline_runs=0,
                candidates_discovered=0,
                editable_operations=0,
                skipped_candidates=0,
                candidate_attempts=0,
                accepted_probes=0,
                rejected_probes=0,
                executions=0,
                initial_python_lines=lines,
                remaining_python_lines=lines,
                wall_clock_seconds=0.0,
                probe_records=(),
                source_unchanged=workspace.source_is_unchanged(),
            )
        coarse_result = None
        if _stage_enabled(self.max_coarse_probes):
            coarse_result = CoarseFileReducer(
                self.runner, max_probes=self.max_coarse_probes
            ).reduce(
                workspace,
                import_result.baseline_signature,
                self.match_mode,
                self.pytest_node,
                budget=budget,
            )
        file_result = GreedyFileReducer(
            self.runner,
            expected_text=self.expected_text,
            match_mode=self.match_mode,
        ).reduce(
            workspace,
            import_result.baseline_signature,
            budget=budget,
            verify_final=verify_stage_finals,
        )
        symbol_result = None
        if _stage_enabled(self.max_symbol_probes):
            symbol_result = GreedySymbolReducer(
                self.runner,
                match_mode=self.match_mode,
                max_probes=self.max_symbol_probes,
                candidate_order=self.symbol_order,
            ).reduce(
                workspace,
                import_result.baseline_signature,
                budget=budget,
                verify_final=verify_stage_finals,
            )
        method_result = None
        if _stage_enabled(self.max_method_probes):
            method_result = GreedySymbolReducer(
                self.runner,
                match_mode=self.match_mode,
                max_probes=self.max_method_probes,
                candidate_order=self.symbol_order,
                candidate_scope=SymbolScope.METHODS,
            ).reduce(
                workspace,
                import_result.baseline_signature,
                budget=budget,
                verify_final=verify_stage_finals,
            )
        if_statement_result = None
        if _stage_enabled(self.max_if_statement_probes):
            if_statement_result = GreedyIfStatementReducer(
                self.runner,
                match_mode=self.match_mode,
                max_probes=self.max_if_statement_probes,
                candidate_order=IfStatementOrder.SPAN_DESC,
            ).reduce(
                workspace,
                import_result.baseline_signature,
                budget=budget,
                verify_final=verify_stage_finals,
            )
        container_entry_result = None
        if _stage_enabled(self.max_container_entry_probes):
            container_entry_result = GreedyContainerEntryReducer(
                self.runner,
                match_mode=self.match_mode,
                max_probes=self.max_container_entry_probes,
            ).reduce(
                workspace,
                import_result.baseline_signature,
                budget=budget,
                verify_final=verify_stage_finals,
            )
        list_entry_result = None
        if _stage_enabled(self.max_list_entry_probes):
            list_entry_result = GreedyListEntryReducer(
                self.runner,
                match_mode=self.match_mode,
                max_probes=self.max_list_entry_probes,
            ).reduce(
                workspace,
                import_result.baseline_signature,
                budget=budget,
                verify_final=verify_stage_finals,
            )
        main_guard_result = None
        if _stage_enabled(self.max_main_guard_probes):
            main_guard_result = GreedyMainGuardReducer(
                self.runner,
                match_mode=self.match_mode,
                max_probes=self.max_main_guard_probes,
            ).reduce(
                workspace,
                import_result.baseline_signature,
                budget=budget,
                verify_final=verify_stage_finals,
            )
        nested_list_entry_result = None
        if _stage_enabled(self.max_nested_list_entry_probes):
            nested_list_entry_result = GreedyNestedPaletteReducer(
                self.runner,
                match_mode=self.match_mode,
                max_probes=self.max_nested_list_entry_probes,
            ).reduce(
                workspace,
                import_result.baseline_signature,
                budget=budget,
                verify_final=verify_stage_finals,
            )
        return PreprocessingReductionResult(
            import_pruning=import_result,
            coarse_reduction=coarse_result,
            file_reduction=file_result,
            symbol_reduction=symbol_result,
            method_reduction=method_result,
            if_statement_reduction=if_statement_result,
            container_entry_reduction=container_entry_result,
            list_entry_reduction=list_entry_result,
            main_guard_reduction=main_guard_result,
            nested_list_entry_reduction=nested_list_entry_result,
            executions=(
                import_result.executions
                + (0 if coarse_result is None else coarse_result.executions)
                + file_result.executions
                + (0 if symbol_result is None else symbol_result.executions)
                + (0 if method_result is None else method_result.executions)
                + (0 if if_statement_result is None else if_statement_result.executions)
                + (
                    0
                    if container_entry_result is None
                    else container_entry_result.executions
                )
                + (0 if list_entry_result is None else list_entry_result.executions)
                + (0 if main_guard_result is None else main_guard_result.executions)
                + (
                    0
                    if nested_list_entry_result is None
                    else nested_list_entry_result.executions
                )
            ),
            wall_clock_seconds=perf_counter() - started,
            probe_records=(
                import_result.probe_records
                + (() if coarse_result is None else coarse_result.probe_records)
                + file_result.probe_records
                + (() if symbol_result is None else symbol_result.probe_records)
                + (() if method_result is None else method_result.probe_records)
                + (
                    ()
                    if if_statement_result is None
                    else if_statement_result.probe_records
                )
                + (
                    ()
                    if container_entry_result is None
                    else container_entry_result.probe_records
                )
                + (() if list_entry_result is None else list_entry_result.probe_records)
                + (() if main_guard_result is None else main_guard_result.probe_records)
                + (
                    ()
                    if nested_list_entry_result is None
                    else nested_list_entry_result.probe_records
                )
            ),
            source_unchanged=(
                import_result.source_unchanged
                and file_result.source_unchanged
                and (symbol_result is None or symbol_result.source_unchanged)
                and (method_result is None or method_result.source_unchanged)
                and (
                    if_statement_result is None or if_statement_result.source_unchanged
                )
                and (
                    container_entry_result is None
                    or container_entry_result.source_unchanged
                )
                and (list_entry_result is None or list_entry_result.source_unchanged)
                and (main_guard_result is None or main_guard_result.source_unchanged)
                and (
                    nested_list_entry_result is None
                    or nested_list_entry_result.source_unchanged
                )
            ),
            budget_exhausted=(
                import_result.budget_exhausted
                or (coarse_result is not None and coarse_result.budget_exhausted)
                or file_result.budget_exhausted
                or (symbol_result is not None and symbol_result.budget_exhausted)
                or (method_result is not None and method_result.budget_exhausted)
                or (
                    if_statement_result is not None
                    and if_statement_result.budget_exhausted
                )
                or (
                    container_entry_result is not None
                    and container_entry_result.budget_exhausted
                )
                or (
                    list_entry_result is not None and list_entry_result.budget_exhausted
                )
                or (
                    main_guard_result is not None and main_guard_result.budget_exhausted
                )
                or (
                    nested_list_entry_result is not None
                    and nested_list_entry_result.budget_exhausted
                )
            ),
        )


class FixedPointPipelineReducer:
    """Repeat the production pipeline until stable or a Fast budget stops it.

    Each sweep rediscover candidates from the active disposable workspace.
    Fast-mode stage limits are consumed across all sweeps; Standard Mode passes
    ``None`` for every limit and therefore has no default search cap.
    """

    def __init__(
        self,
        runner: CommandRunner,
        pytest_node: str,
        *,
        expected_text: str | None = None,
        match_mode: FailureMatchMode = FailureMatchMode.STRICT,
        limits: PipelineProbeLimits = PipelineProbeLimits(),
        symbol_order: SymbolOrder = SymbolOrder.DISCOVERY,
    ) -> None:
        """Configure the shared pipeline and its execution policy."""
        self.runner = runner
        self.pytest_node = pytest_node
        self.expected_text = expected_text
        self.match_mode = match_mode
        self.limits = limits
        self.symbol_order = symbol_order

    def reduce(
        self,
        workspace: ReductionWorkspace,
        *,
        budget: ExecutionBudget | None = None,
    ) -> PipelineReductionResult:
        """Reduce until a complete sweep has no accepted edits.

        Args:
            workspace: Active disposable workspace.
            budget: Shared Fast-Mode budget, or ``None`` for Standard Mode.

        Returns:
            Aggregated, per-sweep telemetry and fixed-point status.
        """
        started = perf_counter()
        consumed = {stage: 0 for stage in PRODUCTION_REDUCER_STAGE_ORDER}
        sweeps: list[PreprocessingReductionResult] = []
        baseline: FailureSignature | None = None
        fixed_point = False
        budget_exhausted = False

        while True:
            sweep = PreprocessingFirstReducer(
                self.runner,
                self.pytest_node,
                expected_text=self.expected_text,
                match_mode=self.match_mode,
                max_import_probes=self.limits.remaining(consumed, "import_pruning"),
                max_coarse_probes=self.limits.remaining(consumed, "coarse"),
                max_symbol_probes=self.limits.remaining(consumed, "symbol"),
                max_method_probes=self.limits.remaining(consumed, "method"),
                max_if_statement_probes=self.limits.remaining(consumed, "if_statement"),
                max_container_entry_probes=self.limits.remaining(
                    consumed, "container_entry"
                ),
                max_list_entry_probes=self.limits.remaining(consumed, "list_entry"),
                max_main_guard_probes=self.limits.remaining(consumed, "main_guard"),
                max_nested_list_entry_probes=self.limits.remaining(
                    consumed, "nested_list_entry"
                ),
                symbol_order=self.symbol_order,
            ).reduce(
                workspace,
                budget=budget,
                verify_stage_finals=False,
                baseline_signature=baseline,
            )
            sweeps.append(sweep)
            baseline = sweep.import_pruning.baseline_signature
            for stage, attempts in _stage_attempts(sweep).items():
                consumed[stage] += attempts
            accepted = _accepted_edits(sweep)
            if sweep.budget_exhausted:
                budget_exhausted = True
                break
            if accepted == 0:
                fixed_point = True
                break

        if baseline is None:
            raise AssertionError("the pipeline did not establish a baseline")
        return PipelineReductionResult(
            baseline_signature=baseline,
            sweeps=tuple(sweeps),
            baseline_executions=sum(
                sweep.import_pruning.baseline_runs for sweep in sweeps
            ),
            search_executions=(
                sum(sweep.executions for sweep in sweeps)
                - sum(sweep.import_pruning.baseline_runs for sweep in sweeps)
            ),
            executions=sum(sweep.executions for sweep in sweeps),
            wall_clock_seconds=perf_counter() - started,
            probe_records=tuple(
                record for sweep in sweeps for record in sweep.probe_records
            ),
            source_unchanged=all(sweep.source_unchanged for sweep in sweeps),
            budget_exhausted=budget_exhausted,
            fixed_point_reached=fixed_point,
            limits=self.limits,
        )


def _stage_attempts(result: PreprocessingReductionResult) -> dict[str, int]:
    """Return stage probe counts for cumulative Fast-Mode limit accounting."""
    optional = {
        "coarse": result.coarse_reduction,
        "symbol": result.symbol_reduction,
        "method": result.method_reduction,
        "if_statement": result.if_statement_reduction,
        "container_entry": result.container_entry_reduction,
        "list_entry": result.list_entry_reduction,
        "main_guard": result.main_guard_reduction,
        "nested_list_entry": result.nested_list_entry_reduction,
    }
    return {
        "import_pruning": result.import_pruning.candidate_attempts,
        "file": result.file_reduction.candidate_attempts,
        **{
            stage: 0 if stage_result is None else stage_result.candidate_attempts
            for stage, stage_result in optional.items()
        },
    }


def _accepted_edits(result: PreprocessingReductionResult) -> int:
    """Count accepted source or file edits in one completed sweep."""
    optional = (
        result.coarse_reduction,
        result.symbol_reduction,
        result.method_reduction,
        result.if_statement_reduction,
        result.container_entry_reduction,
        result.list_entry_reduction,
        result.main_guard_reduction,
        result.nested_list_entry_reduction,
    )
    return (
        result.import_pruning.accepted_probes
        + result.file_reduction.accepted_probes
        + sum(
            0 if stage is None else _accepted_stage_edits(stage) for stage in optional
        )
    )


def _accepted_stage_edits(stage: object) -> int:
    """Read a reducer's established accepted-edit counter."""
    accepted_probes = getattr(stage, "accepted_probes", None)
    if accepted_probes is not None:
        return accepted_probes
    accepted_removals = getattr(stage, "accepted_removals", None)
    if accepted_removals is not None:
        return accepted_removals
    return getattr(stage, "accepted_batches")
