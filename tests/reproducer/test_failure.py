"""Tests for Python failure-signature extraction and comparison."""

from pathlib import Path

from pyrepro.reproducer.failure import (
    FailureMatchMode,
    FailureSignature,
    ReductionOutcome,
    classify_result,
)
from pyrepro.reproducer.runner import ExecutionResult


def test_signature_uses_exception_message_and_final_workspace_frame(tmp_path: Path):
    """Distinguish the original KeyError from the same text in another frame."""
    root = tmp_path / "workspace"
    parser_file = root / "app" / "parser.py"
    stderr = f"""Traceback (most recent call last):
  File "{root / "reproduce.py"}", line 5, in <module>
    parse_lane({{"id": "lane-1"}})
  File "{parser_file}", line 15, in parse_lane
    lane.width = record["width"]
KeyError: 'width'
"""
    result = ExecutionResult(("python", "reproduce.py"), 1, "", stderr, False)

    signature = FailureSignature.from_result(result, root)

    assert signature == FailureSignature(
        "KeyError", "'width'", "app/parser.py", "parse_lane"
    )


def test_classification_rejects_matching_exception_text_in_another_frame(
    tmp_path: Path,
):
    """Require the final traceback frame in addition to exception type and text."""
    root = tmp_path / "workspace"
    baseline = FailureSignature("KeyError", "'width'", "app/parser.py", "parse_lane")
    stderr = f"""Traceback (most recent call last):
  File "{root / "app" / "config.py"}", line 8, in load_config
    return values["width"]
KeyError: 'width'
"""
    result = ExecutionResult(("python", "reproduce.py"), 1, "", stderr, False)

    outcome = classify_result(result, baseline, root)

    assert outcome is ReductionOutcome.DIFFERENT_FAILURE


def test_classification_reports_pass_and_timeout(tmp_path: Path):
    """Treat successful and timed-out candidates as rejected reductions."""
    baseline = FailureSignature("KeyError", "'width'", "app/parser.py", "parse_lane")
    passed = ExecutionResult(("python", "reproduce.py"), 0, "", "", False)
    timed_out = ExecutionResult(("python", "reproduce.py"), None, "", "", True)

    assert classify_result(passed, baseline, tmp_path) is ReductionOutcome.PASS
    assert classify_result(timed_out, baseline, tmp_path) is ReductionOutcome.TIMEOUT


def test_message_matching_mode_ignores_traceback_frame(tmp_path: Path):
    """Allow the fair single-file comparison to use message-only identity."""
    root = tmp_path / "workspace"
    baseline = FailureSignature("KeyError", "'width'", "app/parser.py", "parse_lane")
    stderr = f"""Traceback (most recent call last):
  File "{root / "app" / "config.py"}", line 8, in load_config
    return values["width"]
KeyError: 'width'
"""
    result = ExecutionResult(("python", "reproduce.py"), 1, "", stderr, False)

    outcome = classify_result(result, baseline, root, FailureMatchMode.MESSAGE)

    assert outcome is ReductionOutcome.SAME_FAILURE
