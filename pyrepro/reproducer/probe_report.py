"""Write opt-in, machine-readable telemetry for verified reduction probes."""

from __future__ import annotations

import json
from pathlib import Path

from pyrepro.reproducer.reducer import ProbeRecord, ReductionResult


def validate_probe_report_path(path: Path, source_root: Path) -> Path:
    """Validate a new JSONL report location outside the protected source tree.

    Args:
        path: User-selected JSONL destination.
        source_root: Immutable source-project root.

    Returns:
        Normalized report destination.

    Raises:
        ValueError: If the path is inside source_root, already exists, or its
            parent directory does not exist.
    """
    destination = path.expanduser().resolve()
    try:
        destination.relative_to(source_root)
    except ValueError:
        pass
    else:
        raise ValueError("probe report path must be outside the source root")
    if destination.exists():
        raise ValueError(f"probe report path already exists: {destination}")
    if not destination.parent.is_dir():
        raise ValueError(
            f"probe report parent directory does not exist: {destination.parent}"
        )
    return destination


def write_probe_records(destination: Path, result: ReductionResult) -> None:
    """Write one JSON object per file-reduction probe.

    ``elapsed_seconds`` is the cumulative command-execution duration rather
    than reducer wall-clock time. This isolates Oracle cost from workspace I/O.
    ``remaining_python_loc`` describes the Python LOC in the candidate
    workspace proposed by the probe; for rejected probes it is not an accepted
    repository state.

    Args:
        destination: Validated, non-existing JSONL output path.
        result: Completed file-reduction result containing probe records.
    """
    cumulative_duration = 0.0
    with destination.open("x", encoding="utf-8") as stream:
        for probe_id, record in enumerate(result.probe_records, start=1):
            cumulative_duration += record.duration_seconds
            json.dump(
                _record_as_json(probe_id, record, cumulative_duration),
                stream,
                sort_keys=True,
            )
            stream.write("\n")


def _record_as_json(
    probe_id: int, record: ProbeRecord, elapsed_seconds: float
) -> dict[str, object]:
    """Serialize one record without changing reducer telemetry semantics."""
    signature = record.failure_signature
    return {
        "probe_id": probe_id,
        "phase": record.phase,
        "candidate": list(record.candidate_paths),
        "outcome": record.outcome.value,
        "accepted": record.accepted,
        "duration_seconds": record.duration_seconds,
        "elapsed_seconds": elapsed_seconds,
        "remaining_python_loc": record.candidate_python_lines,
        "return_code": record.return_code,
        "failure_type": record.exception_type,
        "failure_message": record.exception_message,
        "failure_signature": (
            None
            if signature is None
            else {
                "exception_type": signature.exception_type,
                "message": signature.normalized_message,
                "file": signature.file,
                "function": signature.function,
            }
        ),
    }
