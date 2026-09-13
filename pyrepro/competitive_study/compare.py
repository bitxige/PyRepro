"""Run reproducible, tool-agnostic reduction comparisons.

This module is research tooling, not part of the PyRepro runtime. It runs
trusted local commands, records their process output, and measures the
resulting project copy. External reducer commands may use ``{source}``,
``{output}``, and ``{oracle}`` placeholders.
"""

from __future__ import annotations

import argparse
import ast
import json
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from time import perf_counter

from pyrepro.reproducer.failure import FailureSignature
from pyrepro.reproducer.runner import CommandRunner


@dataclass(frozen=True)
class WorkspaceStats:
    """Source-size measurements for one project directory."""

    total_files: int
    python_files: int
    python_loc: int
    top_level_symbols: int


@dataclass(frozen=True)
class ComparisonResult:
    """Machine-readable result of one reducer invocation."""

    tool: str
    command: tuple[str, ...]
    return_code: int
    runtime_seconds: float
    source: str
    output: str
    before: WorkspaceStats
    after: WorkspaceStats | None
    failure_preserved: bool | None
    verification_executions: int
    stdout_path: str
    stderr_path: str


def measure_workspace(root: Path) -> WorkspaceStats:
    """Measure files, Python LOC, and module-level symbols under ``root``."""
    files = [path for path in root.rglob("*") if path.is_file()]
    python_files = [path for path in files if path.suffix == ".py"]
    line_count = 0
    symbol_count = 0
    for path in python_files:
        try:
            source = path.read_text(encoding="utf-8")
            line_count += len(source.splitlines())
            symbol_count += sum(
                isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
                for node in ast.parse(source, filename=str(path)).body
            )
        except (OSError, SyntaxError, UnicodeError):
            continue
    return WorkspaceStats(
        total_files=len(files),
        python_files=len(python_files),
        python_loc=line_count,
        top_level_symbols=symbol_count,
    )


def expand_command(
    command: list[str], source: Path, output: Path, oracle: Path | None = None
) -> tuple[str, ...]:
    """Expand safe path placeholders in an external reducer command."""
    values = {
        "{source}": str(source.resolve()),
        "{output}": str(output.resolve()),
        "{oracle}": str(oracle.resolve()) if oracle is not None else "",
    }
    return tuple(
        next((value for key, value in values.items() if token == key), token)
        for token in command
    )


def run_external(
    tool: str,
    command: list[str],
    source: Path,
    output: Path,
    result_root: Path,
    reproduction_command: list[str],
    timeout_seconds: float,
    oracle: Path | None = None,
) -> ComparisonResult:
    """Run one external reducer and verify its output with the shared command."""
    source = source.expanduser().resolve()
    output = output.expanduser().resolve()
    result_root.mkdir(parents=True, exist_ok=True)
    expanded = expand_command(command, source, output, oracle)
    before = measure_workspace(source)
    started_at = perf_counter()
    completed = subprocess.run(
        expanded,
        cwd=source,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout_seconds,
    )
    runtime_seconds = perf_counter() - started_at
    stdout_path = result_root / f"{tool}.stdout.txt"
    stderr_path = result_root / f"{tool}.stderr.txt"
    stdout_path.write_text(completed.stdout, encoding="utf-8")
    stderr_path.write_text(completed.stderr, encoding="utf-8")

    after = measure_workspace(output) if output.is_dir() else None
    if after is not None:
        preserved, verification_executions = _verify_failure(
            source, output, reproduction_command, timeout_seconds
        )
    else:
        preserved, verification_executions = None, 0
    result = ComparisonResult(
        tool=tool,
        command=expanded,
        return_code=completed.returncode,
        runtime_seconds=runtime_seconds,
        source=str(source),
        output=str(output),
        before=before,
        after=after,
        failure_preserved=preserved,
        verification_executions=verification_executions,
        stdout_path=str(stdout_path),
        stderr_path=str(stderr_path),
    )
    (result_root / f"{tool}.json").write_text(
        json.dumps(asdict(result), indent=2) + "\n", encoding="utf-8"
    )
    return result


def _verify_failure(
    source: Path, output: Path, command: list[str], timeout_seconds: float
) -> tuple[bool, int]:
    runner = CommandRunner(command, timeout_seconds=timeout_seconds)
    source_result = runner.run(source)
    baseline = FailureSignature.from_result(source_result, source)
    output_result = runner.run(output)
    reduced = FailureSignature.from_result(output_result, output)
    return baseline is not None and baseline == reduced, 2


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser for one external-tool run."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tool", help="tool label, such as perses or shrinkray")
    parser.add_argument("source", type=Path, help="trusted local project root")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--results-root", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=float, default=600.0)
    parser.add_argument(
        "--oracle",
        type=Path,
        help="optional path substituted for {oracle} in the tool command",
    )
    parser.add_argument(
        "--tool-command",
        type=_parse_command_json,
        required=True,
        help=(
            "JSON argv for the external command; use {source}, {output}, and "
            "{oracle} placeholders"
        ),
    )
    parser.add_argument(
        "--reproduction-command",
        type=_parse_command_json,
        required=True,
        help="JSON argv used to verify the reduced output",
    )
    return parser


def _parse_command_json(value: str) -> list[str]:
    """Parse a JSON array of argv strings without invoking a shell."""
    try:
        command = json.loads(value)
    except json.JSONDecodeError as error:
        raise argparse.ArgumentTypeError("command must be a JSON array") from error
    if (
        not isinstance(command, list)
        or not command
        or not all(isinstance(item, str) and item for item in command)
    ):
        raise argparse.ArgumentTypeError(
            "command must be a non-empty JSON array of non-empty strings"
        )
    return command


def main(argv: list[str] | None = None) -> int:
    """Run one external comparison command and write JSON metrics."""
    parser = build_parser()
    args = parser.parse_args(argv)
    result = run_external(
        args.tool,
        args.tool_command,
        args.source,
        args.output,
        args.results_root,
        args.reproduction_command,
        args.timeout_seconds,
        args.oracle,
    )
    print(json.dumps(asdict(result), indent=2))
    return 0 if result.return_code == 0 and result.failure_preserved else 1


if __name__ == "__main__":
    raise SystemExit(main())
