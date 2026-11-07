"""Fixture-owned regression test for the nested-list benchmark."""

from app import trigger


def test_nested_list_failure() -> None:
    """Exercise the fixture's required failure path."""
    trigger()
