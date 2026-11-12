"""Tests for opt-in JSONL probe telemetry."""

import json
from pathlib import Path
from types import SimpleNamespace

from pyrepro.reproducer.failure import ReductionOutcome
from pyrepro.reproducer.probe_report import write_probe_records
from pyrepro.reproducer.reducer import ProbeRecord


def test_probe_report_exposes_execution_limit_flags(tmp_path: Path):
    """Timeout and truncation facts accompany the Oracle decision."""
    record = ProbeRecord(
        phase="greedy",
        candidate_paths=("app.py",),
        outcome=ReductionOutcome.TIMEOUT,
        accepted=False,
        duration_seconds=1.5,
        return_code=None,
        exception_type=None,
        exception_message=None,
        failure_signature=None,
        timed_out=True,
        stdout_truncated=True,
        stderr_truncated=False,
    )
    destination = tmp_path / "probes.jsonl"

    write_probe_records(destination, SimpleNamespace(probe_records=(record,)))

    payload = json.loads(destination.read_text(encoding="utf-8"))
    assert payload["outcome"] == "timeout"
    assert payload["timed_out"] is True
    assert payload["stdout_truncated"] is True
    assert payload["stderr_truncated"] is False


def test_probe_report_defaults_execution_limit_flags_to_false(tmp_path: Path):
    """Ordinary probes keep explicit false values rather than omitting fields."""
    record = ProbeRecord(
        phase="greedy",
        candidate_paths=("app.py",),
        outcome=ReductionOutcome.SAME_FAILURE,
        accepted=True,
        duration_seconds=0.5,
        return_code=1,
        exception_type="ValueError",
        exception_message="boom",
        failure_signature=None,
    )
    destination = tmp_path / "probes.jsonl"

    write_probe_records(destination, SimpleNamespace(probe_records=(record,)))

    payload = json.loads(destination.read_text(encoding="utf-8"))
    assert payload["timed_out"] is False
    assert payload["stdout_truncated"] is False
    assert payload["stderr_truncated"] is False
