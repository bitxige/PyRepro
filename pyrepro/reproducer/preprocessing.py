"""Compose verified import preprocessing with existing file reduction."""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter

from pyrepro.reproducer.failure import FailureMatchMode
from pyrepro.reproducer.import_pruner import BatchImportPruner, ImportPruningResult
from pyrepro.reproducer.reducer import GreedyFileReducer, ProbeRecord, ReductionResult
from pyrepro.reproducer.runner import CommandRunner
from pyrepro.reproducer.workspace import ReductionWorkspace


@dataclass(frozen=True)
class PreprocessingReductionResult:
    """Results for import preprocessing followed by greedy file reduction."""

    import_pruning: ImportPruningResult
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
    ) -> None:
        """Configure the P5.3a greedy composition.

        Args:
            runner: Trusted argv runner used by both stages.
            pytest_node: Conventional pytest node used only for static scope.
            expected_text: Optional baseline-signature text anchor.
            match_mode: Failure identity used by both stages.
            max_import_probes: Bound for import batch probes.
        """
        self.runner = runner
        self.pytest_node = pytest_node
        self.expected_text = expected_text
        self.match_mode = match_mode
        self.max_import_probes = max_import_probes

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
        file_result = GreedyFileReducer(
            self.runner,
            expected_text=self.expected_text,
            match_mode=self.match_mode,
        ).reduce(workspace, import_result.baseline_signature)
        return PreprocessingReductionResult(
            import_pruning=import_result,
            file_reduction=file_result,
            executions=import_result.executions + file_result.executions,
            wall_clock_seconds=perf_counter() - started,
            probe_records=import_result.probe_records + file_result.probe_records,
            source_unchanged=(
                import_result.source_unchanged and file_result.source_unchanged
            ),
        )
