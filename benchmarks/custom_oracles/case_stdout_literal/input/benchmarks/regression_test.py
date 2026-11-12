"""Fixture-owned overlay for the stdout-literal Oracle benchmark."""

from app import validation_message


def test_stdout_failure() -> str:
    """Return the target business failure marker without raising."""
    return validation_message((3, 5, 8), expected=20)
