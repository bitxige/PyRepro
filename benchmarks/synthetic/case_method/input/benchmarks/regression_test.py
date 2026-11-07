"""Fixture-owned regression test for the method benchmark."""

from app import Scenario


def test_method_failure() -> None:
    """Exercise the fixture's required failure path."""
    Scenario().trigger()
