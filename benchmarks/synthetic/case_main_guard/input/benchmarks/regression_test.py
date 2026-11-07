"""Fixture-owned regression test for the main-guard benchmark."""

from app import trigger


def test_main_guard_failure() -> None:
    """Exercise the fixture's required failure path."""
    trigger()
