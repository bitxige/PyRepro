"""Regression checks for the configured-Oracle benchmark fixtures."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from pyrepro.reproducer.oracle import (
    ExitCodeOracle,
    OracleDecision,
    OutputTextOracle,
)
from pyrepro.reproducer.runner import ExecutionResult
from pyrepro.reproducer.workspace import tree_digest

REPOSITORY_ROOT = Path(__file__).parents[2]
CUSTOM_ORACLE_ROOT = REPOSITORY_ROOT / "benchmarks" / "custom_oracles"
CASE_IDS = (
    "case_exit_code",
    "case_stdout_literal",
    "case_stderr_regex",
)


@pytest.mark.parametrize("case_id", CASE_IDS)
def test_custom_oracle_case_has_a_stable_non_exception_baseline(
    case_id: str,
) -> None:
    """Each fixture preserves its configured behavior for three executions."""
    case_root = CUSTOM_ORACLE_ROOT / case_id
    manifest = json.loads((case_root / "manifest.json").read_text(encoding="utf-8"))
    source = case_root / manifest["input_root"]
    adapter = source / "benchmarks" / "adapter.py"
    before = tree_digest(source)
    environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}

    completed_runs = [
        subprocess.run(
            [sys.executable, str(adapter)],
            cwd=source,
            capture_output=True,
            text=True,
            env=environment,
            check=False,
        )
        for _ in range(3)
    ]
    results = tuple(
        ExecutionResult(
            command=tuple(manifest["oracle_command"]),
            return_code=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            timed_out=False,
        )
        for completed in completed_runs
    )
    oracle = _oracle_from_manifest(manifest["oracle"])
    baseline = oracle.establish_baseline(results, source)

    assert tree_digest(source) == before == manifest["input_digest"]
    assert all(
        baseline.evaluate(result, source).decision is OracleDecision.MATCH
        for result in results
    )
    assert all("Traceback" not in result.stderr for result in results)


def _oracle_from_manifest(config: dict[str, object]):
    """Construct the configured Oracle described by one fixture manifest."""
    if config["type"] == "exit-code":
        return ExitCodeOracle(int(config["expected_exit_code"]))
    return OutputTextOracle(
        str(config["stream"]),
        str(config["match_mode"]),
        str(config["pattern"]),
    )
