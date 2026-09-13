"""Run trusted-local command-driven failure reduction as a Python module."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from pyrepro.reproducer.failure import ReductionOutcome, classify_result
from pyrepro.reproducer.reducer import (
    DdminFileReducer,
    GreedyFileReducer,
    UnstableBaselineError,
    format_reduction_summary,
)
from pyrepro.reproducer.runner import CommandRunner
from pyrepro.reproducer.symbol_reducer import (
    GreedySymbolReducer,
    format_symbol_reduction_summary,
)
from pyrepro.reproducer.workspace import ReductionWorkspace

_DEFAULT_OUTPUT_DIRECTORY_NAME = ".pyrepro-output"


def main(argv: Sequence[str] | None = None) -> int:
    """Reduce a trusted local project while preserving a stable Python failure.

    Args:
        argv: Optional command-line arguments excluding the executable name.

    Returns:
        The process exit status.
    """
    parser = argparse.ArgumentParser(
        description="Reduce a trusted local Python project while preserving a failure."
    )
    subparsers = parser.add_subparsers(dest="operation", required=True)
    reduce_parser = subparsers.add_parser(
        "reduce", help="reduce one trusted local project"
    )
    reduce_parser.add_argument("source", type=Path, help="trusted local project root")
    reduce_parser.add_argument(
        "--output",
        type=Path,
        help="new reduced-project directory (default: sibling .pyrepro-output/<name>)",
    )
    reduce_parser.add_argument(
        "--timeout-seconds",
        default=5.0,
        type=float,
        help="maximum duration for each command execution (default: 5)",
    )
    reduce_parser.add_argument(
        "--expect",
        help="text that must occur in the stable baseline failure signature",
    )
    reduce_parser.add_argument(
        "--strategy",
        choices=("greedy", "ddmin"),
        default="greedy",
        help="file-reduction strategy (default: greedy)",
    )
    reduce_parser.add_argument(
        "--max-granularity",
        choices=("file", "symbol"),
        default="file",
        help="stop after file reduction or continue with symbols (default: file)",
    )
    arguments = list(sys.argv[1:] if argv is None else argv)
    try:
        command_separator = arguments.index("--")
    except ValueError:
        parser.error("a reproduction command is required after --")
    command = arguments[command_separator + 1 :]
    if not command:
        parser.error("a reproduction command is required after --")
    args = parser.parse_args(arguments[:command_separator])
    source = args.source.expanduser().resolve()
    if not source.is_dir():
        parser.error(f"source root is not a directory: {source}")
    output = args.output or _default_output_directory(source)

    print("Warning: PyRepro will repeatedly execute the supplied command.")
    print("Only run a project and command that you trust.")
    try:
        runner = CommandRunner(command, timeout_seconds=args.timeout_seconds)
        reducer_type = (
            GreedyFileReducer if args.strategy == "greedy" else DdminFileReducer
        )
        reducer = reducer_type(runner, expected_text=args.expect)
        with ReductionWorkspace(source) as workspace:
            file_result = reducer.reduce(workspace)
            symbol_result = None
            if args.max_granularity == "symbol":
                symbol_result = GreedySymbolReducer(runner).reduce(
                    workspace, file_result.baseline_signature
                )
            destination = workspace.copy_reduced_to(output)
            output_result = runner.run(destination)
            output_outcome = classify_result(
                output_result, file_result.baseline_signature, destination
            )
    except (OSError, UnstableBaselineError, ValueError) as error:
        parser.error(str(error))

    if output_outcome is not ReductionOutcome.SAME_FAILURE:
        parser.error("copied reduced project did not reproduce the baseline failure")

    print(format_reduction_summary(file_result))
    if symbol_result is not None:
        print()
        print(format_symbol_reduction_summary(symbol_result))
        print(
            "Total oracle executions: "
            f"{file_result.executions + symbol_result.executions}"
        )
        print(
            "Total wall-clock seconds: "
            f"{file_result.wall_clock_seconds + symbol_result.wall_clock_seconds:.3f}"
        )
    print(f"Reduced project: {destination}")
    return 0


def _default_output_directory(source: Path) -> Path:
    """Return a sibling output path that cannot be inside source by default."""
    return source.parent / _DEFAULT_OUTPUT_DIRECTORY_NAME / source.name


if __name__ == "__main__":
    raise SystemExit(main())
