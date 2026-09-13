"""Run the P0 command-driven failure reducer as a Python module."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from reposentinel.reproducer.failure import ReductionOutcome, classify_result
from reposentinel.reproducer.reducer import (
    GreedyFileReducer,
    UnstableBaselineError,
    format_reduction_summary,
)
from reposentinel.reproducer.runner import CommandRunner
from reposentinel.reproducer.workspace import ReductionWorkspace

P0_FIXTURE_ROOT = Path(__file__).parents[2] / "examples" / "failing_project"


def main(argv: Sequence[str] | None = None) -> int:
    """Reduce a trusted fixture while preserving a stable Python failure.

    Args:
        argv: Optional command-line arguments excluding the executable name.

    Returns:
        The process exit status.
    """
    parser = argparse.ArgumentParser(
        description="Run the P0 command-driven file-reduction spike."
    )
    parser.add_argument("source", type=Path, help="trusted source fixture root")
    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="new directory for the verified reduced project",
    )
    parser.add_argument(
        "--timeout-seconds",
        default=5.0,
        type=float,
        help="maximum duration for each command execution (default: 5)",
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
    if source != P0_FIXTURE_ROOT.resolve():
        parser.error(
            "P0 only permits the trusted examples/failing_project fixture source"
        )

    runner = CommandRunner(command, timeout_seconds=args.timeout_seconds)
    reducer = GreedyFileReducer(runner)
    try:
        with ReductionWorkspace(source) as workspace:
            result = reducer.reduce(workspace)
            destination = workspace.copy_reduced_to(args.output)
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


if __name__ == "__main__":
    raise SystemExit(main())
