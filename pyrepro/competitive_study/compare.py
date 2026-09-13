"""Run reproducible, tool-agnostic reduction comparisons.

This module is research tooling, not part of the PyRepro runtime. It protects
the original source with a disposable tool input, records source integrity,
and separates reducer-reported queries from verification executions. External
reducer commands may use ``{source}``, ``{output}``, and ``{oracle}``
placeholders.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from time import perf_counter

from pyrepro.reproducer.failure import (
    FailureMatchMode,
    FailureSignature,
    signatures_match,
)
from pyrepro.reproducer.runner import CommandRunner

STABILITY_RUNS = 3


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
    return_code: int | None
    runtime_seconds: float
    source: str
    output: str
    before: WorkspaceStats
    after: WorkspaceStats | None
    failure_match_mode: FailureMatchMode
    baseline_runs: int
    baseline_stable: bool
    reduced_verification_runs: int
    reduced_stable: bool
    failure_preserved: bool | None
    reducer_oracle_queries: int | None
    verification_executions: int
    source_digest_before: str
    source_digest_after: str
    source_unchanged: bool
    stdout_path: str
    stderr_path: str


@dataclass(frozen=True)
class VerificationResult:
    """Stability and failure-preservation result for one reduced output."""

    baseline_signature: FailureSignature
    baseline_stable: bool
    reduced_stable: bool
    failure_preserved: bool
    baseline_runs: int
    reduced_runs: int

    @property
    def executions(self) -> int:
        """Return baseline plus reduced verification executions."""
        return self.baseline_runs + self.reduced_runs


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


def source_digest(root: Path) -> str:
    """Return a deterministic digest of file names and bytes under ``root``."""
    digest = hashlib.sha256()
    for path in sorted(
        (path for path in root.rglob("*") if path.is_file()),
        key=lambda item: item.relative_to(root).as_posix(),
    ):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


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
    match_mode: FailureMatchMode = FailureMatchMode.STRICT,
    reducer_oracle_queries: int | None = None,
) -> ComparisonResult:
    """Run one external reducer and verify its output three times.

    The external tool receives a disposable copy of ``source``. The original
    tree is never used as the reducer's working directory and its digest is
    checked before and after the run.
    """
    source = source.expanduser().resolve()
    output = output.expanduser().resolve()
    result_root.mkdir(parents=True, exist_ok=True)
    _validate_output_path(source, output)
    if not source.is_dir():
        raise ValueError(f"source root is not a directory: {source}")
    if output.exists():
        raise ValueError(f"output already exists: {output}")

    before = measure_workspace(source)
    digest_before = source_digest(source)
    baseline_signature, baseline_stable = _establish_baseline(
        source, reproduction_command, timeout_seconds, match_mode
    )

    stdout_path = result_root / f"{tool}.stdout.txt"
    stderr_path = result_root / f"{tool}.stderr.txt"
    started_at = perf_counter()
    return_code: int | None = None
    command_for_result: tuple[str, ...] = ()
    with tempfile.TemporaryDirectory(prefix="pyrepro-comparison-source-") as name:
        working_source = Path(name) / "source"
        shutil.copytree(source, working_source)
        command_for_result = expand_command(command, working_source, output, oracle)
        completed = subprocess.run(
            command_for_result,
            cwd=working_source,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_seconds,
            shell=False,
        )
        return_code = completed.returncode
        stdout_path.write_text(completed.stdout, encoding="utf-8")
        stderr_path.write_text(completed.stderr, encoding="utf-8")
    runtime_seconds = perf_counter() - started_at

    digest_after = source_digest(source)
    source_unchanged = digest_before == digest_after
    after = measure_workspace(output) if output.is_dir() else None
    if after is not None:
        verification = _verify_failure(
            output,
            reproduction_command,
            timeout_seconds,
            baseline_signature,
            baseline_stable,
            match_mode,
        )
    else:
        verification = None

    result = ComparisonResult(
        tool=tool,
        command=command_for_result,
        return_code=return_code,
        runtime_seconds=runtime_seconds,
        source=str(source),
        output=str(output),
        before=before,
        after=after,
        failure_match_mode=match_mode,
        baseline_runs=STABILITY_RUNS,
        baseline_stable=baseline_stable,
        reduced_verification_runs=(
            verification.reduced_runs if verification is not None else 0
        ),
        reduced_stable=(verification.reduced_stable if verification else False),
        failure_preserved=(
            verification.failure_preserved if verification is not None else None
        ),
        reducer_oracle_queries=reducer_oracle_queries,
        verification_executions=(verification.executions if verification else 0),
        source_digest_before=digest_before,
        source_digest_after=digest_after,
        source_unchanged=source_unchanged,
        stdout_path=str(stdout_path),
        stderr_path=str(stderr_path),
    )
    (result_root / f"{tool}.json").write_text(
        json.dumps(asdict(result), indent=2) + "\n", encoding="utf-8"
    )
    return result


def _establish_baseline(
    source: Path,
    command: list[str],
    timeout_seconds: float,
    match_mode: FailureMatchMode,
) -> tuple[FailureSignature, bool]:
    runner = CommandRunner(command, timeout_seconds=timeout_seconds)
    signatures = [
        FailureSignature.from_result(runner.run(source), source)
        for _ in range(STABILITY_RUNS)
    ]
    if any(signature is None for signature in signatures):
        raise RuntimeError("comparison baseline is not a supported Python failure")
    baseline = signatures[0]
    stable = all(
        signatures_match(signature, baseline, match_mode)
        for signature in signatures[1:]
    )
    if not stable:
        raise RuntimeError("comparison baseline failure is unstable")
    return baseline, stable


def _verify_failure(
    output: Path,
    command: list[str],
    timeout_seconds: float,
    baseline: FailureSignature,
    baseline_stable: bool,
    match_mode: FailureMatchMode,
) -> VerificationResult:
    runner = CommandRunner(command, timeout_seconds=timeout_seconds)
    signatures = [
        FailureSignature.from_result(runner.run(output), output)
        for _ in range(STABILITY_RUNS)
    ]
    reduced_stable = (
        all(
            signature is not None
            and signatures_match(signature, signatures[0], match_mode)
            for signature in signatures[1:]
        )
        and signatures[0] is not None
    )
    preserved = (
        baseline_stable
        and reduced_stable
        and signatures[0] is not None
        and signatures_match(signatures[0], baseline, match_mode)
    )
    return VerificationResult(
        baseline_signature=baseline,
        baseline_stable=baseline_stable,
        reduced_stable=reduced_stable,
        failure_preserved=preserved,
        baseline_runs=STABILITY_RUNS,
        reduced_runs=STABILITY_RUNS,
    )


def _validate_output_path(source: Path, output: Path) -> None:
    """Reject an output path inside the protected source tree."""
    try:
        output.relative_to(source)
    except ValueError:
        return
    raise ValueError("comparison output must not be inside the source tree")


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser for one external-tool run."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tool", help="tool label, such as perses or shrinkray")
    parser.add_argument("source", type=Path, help="trusted local project root")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--results-root", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=float, default=600.0)
    parser.add_argument(
        "--failure-match",
        choices=tuple(mode.value for mode in FailureMatchMode),
        default=FailureMatchMode.STRICT.value,
        help="failure identity used for this controlled comparison",
    )
    parser.add_argument(
        "--reducer-oracle-queries",
        type=int,
        help="optional query count reported by the external reducer",
    )
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
    try:
        result = run_external(
            args.tool,
            args.tool_command,
            args.source,
            args.output,
            args.results_root,
            args.reproduction_command,
            args.timeout_seconds,
            args.oracle,
            FailureMatchMode(args.failure_match),
            args.reducer_oracle_queries,
        )
    except (OSError, RuntimeError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps(asdict(result), indent=2))
    return int(
        not (
            result.return_code == 0
            and result.source_unchanged
            and result.baseline_stable
            and result.reduced_stable
            and result.failure_preserved
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
