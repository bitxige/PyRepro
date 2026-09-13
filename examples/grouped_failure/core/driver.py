"""Coordinate optional setup before the deterministic failure."""

from optional_loader import configure_optional_pair

from core.failure import trigger_failure
from core.inputs import build_failure_input


def run() -> None:
    configure_optional_pair()
    trigger_failure(build_failure_input())
