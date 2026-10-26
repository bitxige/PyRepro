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
from pyrepro.reproducer.failure import FailureMatchMode
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
from pyrepro.reproducer.reducer import GreedyFileReducer, ProbeRecord, ReductionResult
from pyrepro.reproducer.runner import CommandRunner
from pyrepro.reproducer.symbol_reducer import (
    GreedySymbolReducer,
    SymbolOrder,
    SymbolReductionResult,
    SymbolScope,
)
from pyrepro.reproducer.workspace import ReductionWorkspace


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
    executions: int
    wall_clock_seconds: float
    probe_records: tuple[ProbeRecord, ...]
    source_unchanged: bool
    budget_exhausted: bool = False


class PreprocessingFirstReducer:
    """Reuse one workspace and baseline across pruning then greedy reduction.

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
        max_import_probes: int = 16,
        max_coarse_probes: int = 0,
        max_symbol_probes: int = 0,
        max_method_probes: int = 0,
        max_if_statement_probes: int = 0,
        max_container_entry_probes: int = 0,
        max_list_entry_probes: int = 0,
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
        self.symbol_order = symbol_order

    def reduce(
        self,
        workspace: ReductionWorkspace,
        *,
        budget: ExecutionBudget | None = None,
    ) -> PreprocessingReductionResult:
        """Run composed stages with one baseline and optional shared budget."""
        started = perf_counter()
        import_result = BatchImportPruner(
            self.runner,
            self.pytest_node,
            expected_text=self.expected_text,
            match_mode=self.match_mode,
            max_probes=self.max_import_probes,
        ).prune(workspace, budget=budget, verify_final=budget is None)
        coarse_result = None
        if self.max_coarse_probes:
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
            verify_final=budget is None,
        )
        symbol_result = None
        if self.max_symbol_probes:
            symbol_result = GreedySymbolReducer(
                self.runner,
                match_mode=self.match_mode,
                max_probes=self.max_symbol_probes,
                candidate_order=self.symbol_order,
            ).reduce(
                workspace,
                import_result.baseline_signature,
                budget=budget,
                verify_final=budget is None,
            )
        method_result = None
        if self.max_method_probes:
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
                verify_final=budget is None,
            )
        if_statement_result = None
        if self.max_if_statement_probes:
            if_statement_result = GreedyIfStatementReducer(
                self.runner,
                match_mode=self.match_mode,
                max_probes=self.max_if_statement_probes,
                candidate_order=IfStatementOrder.SPAN_DESC,
            ).reduce(
                workspace,
                import_result.baseline_signature,
                budget=budget,
                verify_final=budget is None,
            )
        container_entry_result = None
        if self.max_container_entry_probes:
            container_entry_result = GreedyContainerEntryReducer(
                self.runner,
                match_mode=self.match_mode,
                max_probes=self.max_container_entry_probes,
            ).reduce(
                workspace,
                import_result.baseline_signature,
                budget=budget,
                verify_final=budget is None,
            )
        list_entry_result = None
        if self.max_list_entry_probes:
            list_entry_result = GreedyListEntryReducer(
                self.runner,
                match_mode=self.match_mode,
                max_probes=self.max_list_entry_probes,
            ).reduce(
                workspace,
                import_result.baseline_signature,
                budget=budget,
                verify_final=budget is None,
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
            ),
        )
