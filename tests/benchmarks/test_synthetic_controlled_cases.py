"""Regression checks for the deterministic synthetic benchmark fixtures."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from pyrepro.reproducer.workspace import tree_digest

REPOSITORY_ROOT = Path(__file__).parents[2]
SYNTHETIC_ROOT = REPOSITORY_ROOT / "benchmarks" / "synthetic"
CASE_IDS = (
    "case_method",
    "case_if",
    "case_container",
    "case_main_guard",
    "case_nested_list",
)


@pytest.mark.parametrize("case_id", CASE_IDS)
def test_synthetic_case_has_a_stable_strict_baseline(case_id: str) -> None:
    """Each fixture retains its manifest-defined target failure and input tree."""
    case_root = SYNTHETIC_ROOT / case_id
    manifest = json.loads((case_root / "manifest.json").read_text())
    source = case_root / manifest["input_root"]
    adapter = source / "benchmarks" / "adapter.py"
    before = tree_digest(source)
    environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}

    completed = subprocess.run(
        [sys.executable, str(adapter)],
        cwd=source,
        capture_output=True,
        text=True,
        env=environment,
        check=False,
    )

    signature = manifest["failure_signature"]
    assert completed.returncode != 0
    assert f"{signature['exception_type']}: {signature['message']}" in completed.stderr
    assert f"in {signature['function']}" in completed.stderr
    assert tree_digest(source) == before
