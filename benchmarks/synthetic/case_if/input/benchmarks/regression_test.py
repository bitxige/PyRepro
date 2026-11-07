"""Fixture-owned regression test for the if benchmark."""

from app import trigger


def test_if_failure() -> None:
    """Exercise the fixture's required failure path."""
    trigger()
