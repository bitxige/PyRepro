"""Tests for the V1.1 failure-oracle contract and exception compatibility."""

from __future__ import annotations

from pathlib import Path

import pytest
from pyrepro.reproducer.failure import FailureMatchMode
from pyrepro.reproducer.oracle import (
    OracleBaselineError,
    OracleDecision,
    PythonExceptionOracle,
)
from pyrepro.reproducer.runner import ExecutionResult


def test_exception_oracle_establishes_and_matches_a_strict_baseline(
    tmp_path: Path,
):
    """The compatibility oracle preserves the complete existing signature."""
    result = _key_error(tmp_path, "app/parser.py", "parse_lane")
    oracle = PythonExceptionOracle()

    baseline = oracle.establish_baseline((result, result, result), tmp_path)
    evaluation = baseline.evaluate(result, tmp_path)

    assert baseline.name == "python_exception"
    assert baseline.exception_signature is not None
    assert evaluation.decision is OracleDecision.MATCH
    assert evaluation.evidence["exception_type"] == "KeyError"


def test_exception_oracle_keeps_message_mode_compatibility(tmp_path: Path):
    """Message mode retains its established frame-insensitive behavior."""
    baseline_result = _key_error(tmp_path, "app/parser.py", "parse_lane")
    candidate = _key_error(tmp_path, "app/config.py", "load_config")
    oracle = PythonExceptionOracle(FailureMatchMode.MESSAGE)

    baseline = oracle.establish_baseline((baseline_result,) * 3, tmp_path)

    assert baseline.evaluate(candidate, tmp_path).decision is OracleDecision.MATCH


def test_exception_oracle_rejects_changed_failure_and_marks_timeouts_inconclusive(
    tmp_path: Path,
):
    """Only a true match is acceptable; incomplete execution is not a match."""
    result = _key_error(tmp_path, "app/parser.py", "parse_lane")
    baseline = PythonExceptionOracle().establish_baseline((result,) * 3, tmp_path)
    changed = ExecutionResult(
        ("python", "reproduce.py"),
        1,
        "",
        "ModuleNotFoundError: No module named 'removed_module'\n",
        False,
    )
    timeout = ExecutionResult(("python", "reproduce.py"), None, "", "", True)

    assert baseline.evaluate(changed, tmp_path).decision is OracleDecision.NO_MATCH
    assert baseline.evaluate(timeout, tmp_path).decision is OracleDecision.INCONCLUSIVE


def test_exception_oracle_rejects_unstable_baselines(tmp_path: Path):
    """Baseline establishment remains strict before any reducer can probe."""
    oracle = PythonExceptionOracle()

    with pytest.raises(OracleBaselineError, match="unstable"):
        oracle.establish_baseline(
            (
                _key_error(tmp_path, "app/parser.py", "parse_lane"),
                _key_error(tmp_path, "app/config.py", "load_config"),
            ),
            tmp_path,
        )


def _key_error(root: Path, file_name: str, function: str) -> ExecutionResult:
    return ExecutionResult(
        ("python", "reproduce.py"),
        1,
        "",
        f'''Traceback (most recent call last):
  File "{root / file_name}", line 10, in {function}
    raise KeyError("width")
KeyError: 'width'
''',
        False,
    )
