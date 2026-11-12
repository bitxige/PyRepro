"""Tests for the V1.1 failure-oracle contract and exception compatibility."""

from __future__ import annotations

from pathlib import Path

import pytest
from pyrepro.reproducer.failure import FailureMatchMode
from pyrepro.reproducer.oracle import (
    ExitCodeOracle,
    OracleBaselineError,
    OracleDecision,
    OutputTextOracle,
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


def test_exit_code_oracle_requires_the_configured_code(tmp_path: Path):
    """A configured exit code is stable without requiring an exception."""
    target = ExecutionResult(("tool",), 42, "", "", False)
    oracle = ExitCodeOracle(42)
    baseline = oracle.establish_baseline((target,) * 3, tmp_path)

    assert baseline.name == "exit_code"
    assert baseline.evaluate(target, tmp_path).decision is OracleDecision.MATCH
    assert (
        baseline.evaluate(
            ExecutionResult(("tool",), 1, "", "", False), tmp_path
        ).decision
        is OracleDecision.NO_MATCH
    )
    assert (
        baseline.evaluate(
            ExecutionResult(("tool",), None, "", "", True), tmp_path
        ).decision
        is OracleDecision.INCONCLUSIVE
    )


def test_output_text_oracle_matches_selected_streams_and_regex(tmp_path: Path):
    """Output matching supports literal, regex, and both-stream selection."""
    literal_result = ExecutionResult(
        ("tool",), 0, "", "VALIDATION_FAILED: checksum mismatch\n", False
    )
    literal = OutputTextOracle("stderr", "literal", "VALIDATION_FAILED")
    literal_baseline = literal.establish_baseline((literal_result,) * 3, tmp_path)
    assert (
        literal_baseline.evaluate(literal_result, tmp_path).decision
        is OracleDecision.MATCH
    )
    assert (
        literal_baseline.evaluate(
            ExecutionResult(("tool",), 0, "VALIDATION_FAILED", "", False), tmp_path
        ).decision
        is OracleDecision.NO_MATCH
    )

    regex_result = ExecutionResult(
        ("tool",), 0, "ERROR[PAYLOAD-1007]: invalid record", "", False
    )
    regex = OutputTextOracle("both", "regex", r"ERROR\[PAYLOAD-\d+\]")
    regex_baseline = regex.establish_baseline((regex_result,) * 3, tmp_path)
    assert (
        regex_baseline.evaluate(regex_result, tmp_path).decision is OracleDecision.MATCH
    )


def test_output_text_oracle_marks_missing_truncated_output_inconclusive(
    tmp_path: Path,
):
    """A missing marker cannot reject a candidate when selected output is partial."""
    matching = ExecutionResult(("tool",), 0, "target marker", "", False)
    oracle = OutputTextOracle("stdout", "literal", "target marker")
    baseline = oracle.establish_baseline((matching,) * 3, tmp_path)
    truncated = ExecutionResult(("tool",), 0, "other tail", "", False, True)

    assert (
        baseline.evaluate(truncated, tmp_path).decision is OracleDecision.INCONCLUSIVE
    )
    assert (
        baseline.evaluate(
            ExecutionResult(("tool",), 0, "other output", "", False), tmp_path
        ).decision
        is OracleDecision.NO_MATCH
    )
    assert (
        baseline.evaluate(
            ExecutionResult(("tool",), None, "target marker", "", True), tmp_path
        ).decision
        is OracleDecision.INCONCLUSIVE
    )


def test_output_text_oracle_rejects_invalid_regular_expression():
    """Invalid regular expressions fail before any command can run."""
    with pytest.raises(ValueError, match="invalid output regular expression"):
        OutputTextOracle("stdout", "regex", "[")


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
