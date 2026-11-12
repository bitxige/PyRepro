"""Fixture-owned overlay for the stderr-regex Oracle benchmark."""

from app import validation_log


def test_stderr_failure() -> str:
    """Return the target dynamic error marker without raising."""
    return validation_log({"valid": False, "payload": "sample-7"})
