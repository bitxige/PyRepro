"""Bounded directory-oriented file deletion before greedy cleanup."""

from __future__ import annotations

import shutil
import tempfile
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter

from pyrepro.reproducer.failure import (
    FailureMatchMode,
    FailureSignature,
    ReductionOutcome,
    classify_result,
)
from pyrepro.reproducer.reducer import (
    DEFAULT_IGNORED_DIRECTORY_NAMES,
    ProbeRecord,
    _python_files,
    _python_line_count,
)
from pyrepro.reproducer.runner import CommandRunner
from pyrepro.reproducer.workspace import ReductionWorkspace


@dataclass(frozen=True)
class CoarseReductionResult:
    """Metrics for bounded coarse deletion probes in one existing workspace."""

    candidate_attempts: int
    accepted_probes: int
    rejected_probes: int
    executions: int
    initial_python_lines: int
    remaining_python_lines: int
    wall_clock_seconds: float
    probe_records: tuple[ProbeRecord, ...]


class CoarseFileReducer:
    """Try path-structure groups, splitting failures within a fixed budget."""

    def __init__(self, runner: CommandRunner, *, max_probes: int = 16) -> None:
        """Configure the trusted command runner and coarse probe budget."""
        if max_probes < 0:
            raise ValueError("max_probes must not be negative")
        self.runner = runner
        self.max_probes = max_probes

    def reduce(
        self,
        workspace: ReductionWorkspace,
        baseline: FailureSignature,
        match_mode: FailureMatchMode,
        pytest_node: str | None = None,
    ) -> CoarseReductionResult:
        """Delete accepted directory groups without re-establishing a baseline."""
        started = perf_counter()
        files = _python_files(workspace.root, DEFAULT_IGNORED_DIRECTORY_NAMES)
        initial_lines = _python_line_count(files)
        protected = _pytest_path(pytest_node)
        candidates = tuple(path for path in files if path.as_posix() != protected)
        queue = deque(_top_level_groups(candidates, workspace.root))
        records: list[ProbeRecord] = []
        accepted = 0
        seen: set[frozenset[Path]] = set()
        while queue and len(records) < self.max_probes:
            group, split = queue.popleft()
            active = tuple(path for path in group if path.exists())
            key = frozenset(active)
            if not active or key in seen:
                continue
            seen.add(key)
            record, same = self._probe(
                workspace.root, active, baseline, match_mode, split
            )
            records.append(record)
            if same:
                for path in active:
                    path.unlink()
                accepted += 1
            else:
                queue.extend(_children(active, workspace.root, split=True))
        return CoarseReductionResult(
            candidate_attempts=len(records),
            accepted_probes=accepted,
            rejected_probes=len(records) - accepted,
            executions=len(records),
            initial_python_lines=initial_lines,
            remaining_python_lines=_python_line_count(
                _python_files(workspace.root, DEFAULT_IGNORED_DIRECTORY_NAMES)
            ),
            wall_clock_seconds=perf_counter() - started,
            probe_records=tuple(records),
        )

    def _probe(
        self,
        root: Path,
        group: tuple[Path, ...],
        baseline: FailureSignature,
        match_mode: FailureMatchMode,
        split: bool,
    ) -> tuple[ProbeRecord, bool]:
        with tempfile.TemporaryDirectory(prefix="pyrepro-coarse-probe-") as name:
            probe_root = Path(name) / "project"
            shutil.copytree(root, probe_root)
            relative = tuple(path.relative_to(root) for path in group)
            for path in relative:
                (probe_root / path).unlink()
            started = perf_counter()
            result = self.runner.run(probe_root)
            duration = perf_counter() - started
            outcome = classify_result(result, baseline, probe_root, match_mode)
            from pyrepro.reproducer.reducer import _probe_record

            record = _probe_record(
                "coarse_split" if split else "coarse_group",
                relative,
                result,
                outcome,
                outcome is ReductionOutcome.SAME_FAILURE,
                duration,
                probe_root,
                root,
                _python_line_count(
                    _python_files(probe_root, DEFAULT_IGNORED_DIRECTORY_NAMES)
                ),
            )
        return record, record.accepted


def _pytest_path(node: str | None) -> str | None:
    if not node or "::" not in node:
        return None
    path = node.split("::", 1)[0]
    return None if Path(path).is_absolute() else Path(path).as_posix()


def _top_level_groups(
    files: tuple[Path, ...], root: Path
) -> tuple[tuple[tuple[Path, ...], bool], ...]:
    groups: dict[str, list[Path]] = {}
    for path in files:
        relative = path.relative_to(root)
        key = relative.parts[0] if len(relative.parts) > 1 else relative.as_posix()
        groups.setdefault(key, []).append(path)
    return tuple((tuple(paths), False) for _, paths in sorted(groups.items()))


def _children(
    files: tuple[Path, ...], root: Path, *, split: bool
) -> tuple[tuple[tuple[Path, ...], bool], ...]:
    if len(files) <= 1:
        return ()
    parents = {path.parent for path in files}
    common = min(parents, key=lambda item: len(item.parts))
    groups: dict[str, list[Path]] = {}
    for path in files:
        relative = path.relative_to(common)
        key = relative.parts[0] if len(relative.parts) > 1 else relative.as_posix()
        groups.setdefault(key, []).append(path)
    result = tuple((tuple(paths), split) for _, paths in sorted(groups.items()))
    if len(result) > 1:
        return result
    midpoint = len(files) // 2
    return ((files[:midpoint], split), (files[midpoint:], split))
