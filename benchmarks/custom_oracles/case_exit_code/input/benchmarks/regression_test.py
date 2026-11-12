"""Fixture-owned overlay for the exit-code Oracle benchmark."""

from app import validation_exit_code


def test_exit_code_failure() -> int:
    """Return the expected business failure code without raising."""
    return validation_exit_code({"status": "invalid", "values": (4, 6, 9)})
