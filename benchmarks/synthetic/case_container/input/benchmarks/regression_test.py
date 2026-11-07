"""Fixture-owned regression test for the container benchmark."""

from app import trigger


def test_container_failure() -> None:
    """Exercise the fixture's required failure path."""
    trigger()
