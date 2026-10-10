"""Compose verified import preprocessing with existing file reduction."""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter

from pyrepro.reproducer.coarse_reducer import CoarseFileReducer, CoarseReductionResult
from pyrepro.reproducer.failure import FailureMatchMode
from pyrepro.reproducer.import_pruner import BatchImportPruner, ImportPruningResult
from pyrepro.reproducer.reducer import GreedyFileReducer, ProbeRecord, ReductionResult
from pyrepro.reproducer.runner import CommandRunner
from pyrepro.reproducer.workspace import ReductionWorkspace


@dataclass(frozen=True)
class PreprocessingReductionResult:
    """Results for import preprocessing followed by greedy file reduction."""

    import_pruning: ImportPruningResult
    coarse_reduction: CoarseReductionResult | None
    file_reduction: ReductionResult
    executions: int
    wall_clock_seconds: float
    probe_records: tuple[ProbeRecord, ...]
    source_unchanged: bool


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
        """
        self.runner = runner
        self.pytest_node = pytest_node
        self.expected_text = expected_text
        self.match_mode = match_mode
        self.max_import_probes = max_import_probes
        self.max_coarse_probes = max_coarse_probes

    def reduce(self, workspace: ReductionWorkspace) -> PreprocessingReductionResult:
        """Verify preprocessing, then run greedy reduction without rebasing."""
        started = perf_counter()
        import_result = BatchImportPruner(
            self.runner,
            self.pytest_node,
            expected_text=self.expected_text,
            match_mode=self.match_mode,
            max_probes=self.max_import_probes,
        ).prune(workspace)
        coarse_result = None
        if self.max_coarse_probes:
            coarse_result = CoarseFileReducer(
                self.runner, max_probes=self.max_coarse_probes
            ).reduce(
                workspace,
                import_result.baseline_signature,
                self.match_mode,
                self.pytest_node,
            )
        file_result = GreedyFileReducer(
            self.runner,
            expected_text=self.expected_text,
            match_mode=self.match_mode,
        ).reduce(workspace, import_result.baseline_signature)
        return PreprocessingReductionResult(
            import_pruning=import_result,
            coarse_reduction=coarse_result,
            file_reduction=file_result,
            executions=(
                import_result.executions
                + (0 if coarse_result is None else coarse_result.executions)
                + file_result.executions
            ),
            wall_clock_seconds=perf_counter() - started,
            probe_records=(
                import_result.probe_records
                + (() if coarse_result is None else coarse_result.probe_records)
                + file_result.probe_records
            ),
            source_unchanged=(
                import_result.source_unchanged and file_result.source_unchanged
            ),
        )
