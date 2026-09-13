"""Run trusted-local command-driven failure reduction as a Python module."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from pyrepro.reproducer.failure import ReductionOutcome, classify_result
from pyrepro.reproducer.reducer import (
    GreedyFileReducer,
    UnstableBaselineError,
    format_reduction_summary,
)
from pyrepro.reproducer.runner import CommandRunner
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
        reducer = GreedyFileReducer(runner, expected_text=args.expect)
        with ReductionWorkspace(source) as workspace:
            result = reducer.reduce(workspace)
            destination = workspace.copy_reduced_to(output)
            output_result = runner.run(destination)
            output_outcome = classify_result(
                output_result, result.baseline_signature, destination
            )
    except (OSError, UnstableBaselineError, ValueError) as error:
        parser.error(str(error))

    if output_outcome is not ReductionOutcome.SAME_FAILURE:
        parser.error("copied reduced project did not reproduce the baseline failure")

    print(format_reduction_summary(result))
    print(f"Reduced project: {destination}")
    return 0


def _default_output_directory(source: Path) -> Path:
    """Return a sibling output path that cannot be inside source by default."""
    return source.parent / _DEFAULT_OUTPUT_DIRECTORY_NAME / source.name


if __name__ == "__main__":
    raise SystemExit(main())
