"""Tests for P3 AST discovery and complete-symbol source mutation."""

import ast
import sys
from pathlib import Path

from pyrepro.reproducer.failure import FailureSignature, ReductionOutcome
from pyrepro.reproducer.reducer import GreedyFileReducer
from pyrepro.reproducer.runner import CommandRunner
from pyrepro.reproducer.symbol_reducer import (
    GreedySymbolReducer,
    SymbolCandidate,
    _remove_symbol_span,
    discover_symbols,
)
from pyrepro.reproducer.workspace import ReductionWorkspace, tree_digest

SYMBOL_PROJECT = Path(__file__).parents[2] / "examples" / "symbol_failure"


def test_discovery_reports_top_level_symbol_spans_and_decorators(tmp_path: Path):
    """Discover only supported module-level symbols with inclusive spans."""
    source = tmp_path / "module.py"
    source.write_text(
        """def helper() -> None:
    return None


@staticmethod
async def fetch_value(
    value: str,
) -> str:
    return value


class Preview:
    def render(self) -> str:
        return "preview"


def outer() -> None:
    def nested() -> None:
        return None

    nested()
""",
        encoding="utf-8",
    )

    discovery = discover_symbols(source, tmp_path)

    assert not discovery.skipped
    assert discovery.candidates == (
        _candidate("helper", "function", 1, 2),
        _candidate("fetch_value", "async_function", 5, 9),
        _candidate("Preview", "class", 12, 14),
        _candidate("outer", "function", 17, 21),
    )


def test_symbol_mutation_removes_a_decorator_with_its_symbol(tmp_path: Path):
    """Delete a full decorated span while retaining syntactically valid source."""
    source = tmp_path / "module.py"
    source.write_text(
        """@staticmethod
def unused() -> str:
    return "unused"


def required() -> str:
    return "required"
""",
        encoding="utf-8",
    )
    candidate = discover_symbols(source, tmp_path).candidates[0]

    _remove_symbol_span(source, candidate)

    content = source.read_text(encoding="utf-8")
    ast.parse(content)
    assert "@staticmethod" not in content
    assert "unused" not in content
    assert "def required" in content


def test_discovery_skips_unparsable_source(tmp_path: Path):
    """Leave a syntax-invalid source file unchanged instead of proposing a span."""
    source = tmp_path / "broken.py"
    source.write_text("def incomplete(:\n", encoding="utf-8")

    discovery = discover_symbols(source, tmp_path)

    assert discovery.skipped
    assert not discovery.candidates


def test_symbol_reducer_removes_internal_ballast_after_file_reduction(
    tmp_path: Path,
):
    """Reduce retained source files while preserving the exact reward failure."""
    source_digest = tree_digest(SYMBOL_PROJECT)
    runner = CommandRunner((sys.executable, "reproduce.py"), timeout_seconds=2)

    with ReductionWorkspace(SYMBOL_PROJECT) as workspace:
        file_result = GreedyFileReducer(runner).reduce(workspace)
        symbol_result = GreedySymbolReducer(runner).reduce(
            workspace, file_result.baseline_signature
        )
        destination = workspace.copy_reduced_to(tmp_path / "symbol-output")

    final_result = runner.run(destination)
    final_signature = FailureSignature.from_result(final_result, destination)
    remaining_files = {
        path.relative_to(destination).as_posix() for path in destination.rglob("*.py")
    }
    reward_class = next(
        decision
        for decision in symbol_result.decisions
        if decision.candidate.qualified_name == "RewardComparisonArchive"
    )
    decorated_function = next(
        decision
        for decision in symbol_result.decisions
        if decision.candidate.qualified_name == "reward_debug_message"
    )
    required_function = next(
        decision
        for decision in symbol_result.decisions
        if decision.candidate.qualified_name == "weighted_reward"
    )

    assert file_result.initial_python_files == 9
    assert file_result.remaining_python_files == 4
    assert symbol_result.baseline_signature == final_signature
    assert symbol_result.initial_python_lines > symbol_result.remaining_python_lines
    assert symbol_result.initial_symbols > symbol_result.remaining_symbols
    assert symbol_result.remaining_symbols == 4
    assert symbol_result.executions == symbol_result.candidate_attempts + 1
    assert symbol_result.accepted_removals > 0
    assert reward_class.removed
    assert decorated_function.removed
    assert not required_function.removed
    assert required_function.outcome is ReductionOutcome.DIFFERENT_FAILURE
    assert symbol_result.source_unchanged
    assert tree_digest(SYMBOL_PROJECT) == source_digest
    assert remaining_files == {
        "environment/road_env.py",
        "reproduce.py",
        "reward/shaping.py",
        "training/trainer.py",
    }
    assert "RewardComparisonArchive" not in (
        destination / "reward" / "shaping.py"
    ).read_text(encoding="utf-8")
    for path in destination.rglob("*.py"):
        ast.parse(path.read_text(encoding="utf-8"))


def _candidate(name: str, kind: str, start_line: int, end_line: int) -> SymbolCandidate:
    return SymbolCandidate("module.py", name, kind, start_line, end_line)
