"""Build and publish optional JSON and HTML reduction-result reports.

Reports summarize results that existing reducers, the shared Fast-Mode budget,
and the Publisher already produced.  They never participate in candidate
selection or acceptance decisions.
"""

from __future__ import annotations

import html
import json
import os
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from pyrepro.reproducer.preprocessing import PreprocessingReductionResult
from pyrepro.reproducer.publisher import PublishingResult
from pyrepro.reproducer.reducer import (
    DEFAULT_IGNORED_DIRECTORY_NAMES,
    ReductionResult,
)
from pyrepro.reproducer.symbol_reducer import SymbolReductionResult

REPORT_SCHEMA_VERSION = 1


def validate_report_paths(
    json_path: Path | None,
    html_path: Path | None,
    source_root: Path,
    output_path: Path,
) -> tuple[Path | None, Path | None]:
    """Validate optional, new report files outside the protected source tree.

    Args:
        json_path: Requested JSON report destination, if any.
        html_path: Requested HTML report destination, if any.
        source_root: Immutable input project root.
        output_path: Requested reduced-project destination.

    Returns:
        Normalized JSON and HTML paths in the same order as the inputs.

    Raises:
        ValueError: If a requested path is unsafe, occupied, or overlaps a
            requested report or reduced-project destination.
    """
    destinations = tuple(
        _validate_report_path(path, source_root, output_path, label)
        for path, label in ((json_path, "JSON"), (html_path, "HTML"))
    )
    json_destination, html_destination = destinations
    if (
        json_destination is not None
        and html_destination is not None
        and json_destination == html_destination
    ):
        raise ValueError("JSON and HTML report paths must be different")
    return json_destination, html_destination


def build_fast_report(
    source_root: Path,
    candidate_root: Path,
    reduction: PreprocessingReductionResult,
    publication: PublishingResult,
    *,
    run_wall_clock_seconds: float,
) -> dict[str, object]:
    """Build one truthful report for a completed Fast-Mode attempt.

    Args:
        source_root: Protected source project supplied by the user.
        candidate_root: Accepted workspace before staging publication.
        reduction: Completed composed reduction metrics.
        publication: Publisher terminal result and final-verification facts.

    Returns:
        A JSON-serializable report mapping.  ``candidate`` describes the
        accepted workspace; ``published_output`` is present only after a
        verified publication.
    """
    budget = publication.budget
    attempts = publication.verification_attempts
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "mode": "fast",
        "strategy": "greedy",
        "size": _size_summary(
            _project_size(source_root),
            _project_size(candidate_root),
            (
                None
                if publication.output_path is None
                else _project_size(publication.output_path)
            ),
        ),
        "oracle": {
            "total_executions": budget.executions_started,
            "reduction_executions": reduction.executions,
            "budget": {
                "max_executions": budget.max_oracle_executions,
                "remaining_executions": budget.remaining_executions,
                "final_verifications_started": budget.final_verifications_started,
                "remaining_seconds": budget.remaining_seconds,
            },
        },
        "timing": {
            "reduction_wall_clock_seconds": reduction.wall_clock_seconds,
            "run_wall_clock_seconds": run_wall_clock_seconds,
        },
        "stages": _fast_stage_summaries(reduction),
        "final_verification": {
            "required_runs": 3,
            "completed_runs": len(attempts),
            "same_failure_runs": sum(
                attempt.outcome is not None and attempt.outcome.value == "same_failure"
                for attempt in attempts
            ),
            "passed": publication.verified,
            "attempts": [
                {
                    "outcome": (
                        None if attempt.outcome is None else attempt.outcome.value
                    ),
                    "return_code": attempt.return_code,
                    "timed_out": attempt.timed_out,
                    "failure_signature": _signature_data(attempt.signature),
                }
                for attempt in attempts
            ],
        },
        "status": {
            "terminal_state": publication.state.value,
            "verified": publication.verified,
            "published": publication.output_path is not None,
            "output_path": (
                None
                if publication.output_path is None
                else str(publication.output_path)
            ),
            "source_unchanged": publication.source_unchanged,
            "error_message": publication.error_message,
            "search_budget_exhausted": reduction.budget_exhausted,
        },
    }


def build_standard_report(
    source_root: Path,
    output_root: Path,
    file_result: ReductionResult,
    symbol_result: SymbolReductionResult | None,
    *,
    run_wall_clock_seconds: float,
) -> dict[str, object]:
    """Build one truthful report for a verified Standard-Mode output.

    Standard Mode verifies the copied output once, not through Fast Mode's
    independent staging 3/3 contract.  The report records that distinction.
    """
    reduction_executions = file_result.executions + (
        0 if symbol_result is None else symbol_result.executions
    )
    stages = [_stage_summary("file", file_result, "accepted_probes")]
    if symbol_result is not None:
        stages.append(_stage_summary("symbol", symbol_result, "accepted_removals"))
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "mode": "standard",
        "strategy": file_result.strategy,
        "size": _size_summary(
            _project_size(source_root),
            _project_size(output_root),
            _project_size(output_root),
        ),
        "oracle": {
            "total_executions": reduction_executions + 1,
            "reduction_executions": reduction_executions,
        },
        "timing": {
            "reduction_wall_clock_seconds": file_result.wall_clock_seconds
            + (0.0 if symbol_result is None else symbol_result.wall_clock_seconds),
            "run_wall_clock_seconds": run_wall_clock_seconds,
        },
        "stages": stages,
        "final_verification": {
            "required_runs": 1,
            "completed_runs": 1,
            "same_failure_runs": 1,
            "passed": True,
            "attempts": [],
        },
        "status": {
            "terminal_state": "completed",
            "verified": True,
            "published": True,
            "output_path": str(output_root),
            "source_unchanged": file_result.source_unchanged
            and (symbol_result is None or symbol_result.source_unchanged),
            "error_message": None,
            "search_budget_exhausted": False,
        },
    }


def write_reports(
    report: Mapping[str, object],
    json_path: Path | None,
    html_path: Path | None,
) -> None:
    """Atomically publish requested JSON and HTML reports without overwriting.

    Args:
        report: JSON-serializable report built by this module.
        json_path: Validated JSON destination, if requested.
        html_path: Validated HTML destination, if requested.

    Raises:
        OSError: If a requested report cannot be created.  Existing files are
            never overwritten.
    """
    if json_path is not None:
        _write_new_file(json_path, json.dumps(report, indent=2, sort_keys=True) + "\n")
    if html_path is not None:
        _write_new_file(html_path, render_html(report))


def render_html(report: Mapping[str, object]) -> str:
    """Render one report mapping as a small, escaped standalone HTML page."""
    title = "PyRepro reduction report"
    size = _mapping(report.get("size"))
    status = _mapping(report.get("status"))
    oracle = _mapping(report.get("oracle"))
    verification = _mapping(report.get("final_verification"))
    terminal_state = _html_value(status.get("terminal_state"))
    source_unchanged = _html_value(status.get("source_unchanged"))
    total_executions = _html_value(oracle.get("total_executions"))
    verification_runs = (
        f"{_html_value(verification.get('same_failure_runs'))}/"
        f"{_html_value(verification.get('required_runs'))} same-failure runs"
    )
    rows = "\n".join(
        _html_row(
            _text(stage.get("name")),
            _text(stage.get("candidate_attempts")),
            _text(stage.get("accepted")),
            _text(stage.get("rejected")),
            _text(stage.get("loc_removed")),
        )
        for stage in _mappings(report.get("stages"))
    )
    return "\n".join(
        (
            "<!doctype html>",
            '<html lang="en">',
            "<head>",
            '  <meta charset="utf-8">',
            f"  <title>{html.escape(title)}</title>",
            "  <style>body{font-family:sans-serif;max-width:960px;margin:2rem auto;"
            "padding:0 1rem}table{border-collapse:collapse;width:100%}"
            "th,td{border:1px solid #bbb;padding:.45rem;text-align:left}"
            "th{background:#f4f4f4}.status{font-weight:bold}</style>",
            "</head>",
            "<body>",
            f"  <h1>{html.escape(title)}</h1>",
            f"  <p>Schema version: {_html_value(report.get('schema_version'))}</p>",
            f"  <p>Mode: {_html_value(report.get('mode'))}; strategy: "
            f"{_html_value(report.get('strategy'))}</p>",
            "  <h2>Result</h2>",
            "  <ul>",
            _html_list_item(
                "Terminal state", f'<span class="status">{terminal_state}</span>'
            ),
            _html_list_item("Verified", _html_value(status.get("verified"))),
            _html_list_item("Published", _html_value(status.get("published"))),
            _html_list_item("Source unchanged", source_unchanged),
            _html_list_item("Output path", _html_value(status.get("output_path"))),
            _html_list_item("Error", _html_value(status.get("error_message"))),
            "  </ul>",
            "  <h2>Size</h2>",
            "  <table><thead><tr><th>Artifact</th><th>Python files</th>"
            "<th>LOC</th></tr></thead><tbody>",
            _size_row("Input", _mapping(size.get("input"))),
            _size_row("Accepted candidate", _mapping(size.get("candidate"))),
            _size_row("Published output", _mapping(size.get("published_output"))),
            "  </tbody></table>",
            "  <p>LOC removed: "
            f"{_html_value(size.get('loc_removed'))}; reduction rate: "
            f"{_html_value(size.get('loc_reduction_ratio'))}</p>",
            "  <h2>Oracle and verification</h2>",
            "  <ul>",
            _html_list_item("Total Oracle executions", total_executions),
            _html_list_item("Final verification", verification_runs),
            "  </ul>",
            "  <h2>Reduction stages</h2>",
            "  <table><thead><tr><th>Stage</th><th>Probes</th><th>Accepted</th>"
            "<th>Rejected</th><th>LOC removed</th></tr></thead><tbody>",
            rows or '    <tr><td colspan="5">No stage data available.</td></tr>',
            "  </tbody></table>",
            "</body>",
            "</html>",
            "",
        )
    )


def _validate_report_path(
    path: Path | None, source_root: Path, output_path: Path, label: str
) -> Path | None:
    if path is None:
        return None
    destination = path.expanduser().resolve()
    protected = source_root.expanduser().resolve()
    output = output_path.expanduser().resolve()
    try:
        destination.relative_to(protected)
    except ValueError:
        pass
    else:
        raise ValueError(f"{label} report path must be outside the source root")
    if destination == output:
        raise ValueError(f"{label} report path must differ from the output path")
    if destination.exists():
        raise ValueError(f"{label} report path already exists: {destination}")
    if not destination.parent.is_dir():
        raise ValueError(
            f"{label} report parent directory does not exist: {destination.parent}"
        )
    return destination


def _project_size(root: Path) -> dict[str, int]:
    files = tuple(
        path
        for path in root.rglob("*.py")
        if not any(part in DEFAULT_IGNORED_DIRECTORY_NAMES for part in path.parts)
    )
    return {
        "python_files": len(files),
        "python_loc": sum(_physical_lines(path) for path in files),
    }


def _physical_lines(path: Path) -> int:
    try:
        return len(path.read_text(encoding="utf-8").splitlines())
    except UnicodeDecodeError:
        return len(path.read_bytes().splitlines())


def _size_summary(
    source: Mapping[str, int],
    candidate: Mapping[str, int],
    published_output: Mapping[str, int] | None,
) -> dict[str, object]:
    removed = source["python_loc"] - candidate["python_loc"]
    ratio = None
    if source["python_loc"]:
        ratio = removed / source["python_loc"]
    return {
        "input": dict(source),
        "candidate": dict(candidate),
        "published_output": None
        if published_output is None
        else dict(published_output),
        "loc_removed": removed,
        "loc_reduction_ratio": ratio,
    }


def _fast_stage_summaries(
    reduction: PreprocessingReductionResult,
) -> list[dict[str, object]]:
    stages = [
        _stage_summary("import_pruning", reduction.import_pruning, "accepted_probes"),
    ]
    if reduction.coarse_reduction is not None:
        stages.append(
            _stage_summary("coarse", reduction.coarse_reduction, "accepted_probes")
        )
    stages.append(_stage_summary("file", reduction.file_reduction, "accepted_probes"))
    optional_stages = (
        ("symbol", reduction.symbol_reduction, "accepted_removals"),
        ("method", reduction.method_reduction, "accepted_removals"),
        ("if_statement", reduction.if_statement_reduction, "accepted_removals"),
        ("container_entry", reduction.container_entry_reduction, "accepted_batches"),
        ("list_entry", reduction.list_entry_reduction, "accepted_batches"),
    )
    for name, stage, accepted_field in optional_stages:
        if stage is not None:
            stages.append(_stage_summary(name, stage, accepted_field))
    return stages


def _stage_summary(name: str, result: Any, accepted_field: str) -> dict[str, object]:
    initial = getattr(result, "initial_python_lines", None)
    remaining = getattr(result, "remaining_python_lines", None)
    return {
        "name": name,
        "candidate_attempts": getattr(result, "candidate_attempts", None),
        "accepted": getattr(result, accepted_field, None),
        "rejected": getattr(result, "rejected_probes", None),
        "executions": getattr(result, "executions", None),
        "wall_clock_seconds": getattr(result, "wall_clock_seconds", None),
        "initial_python_loc": initial,
        "remaining_python_loc": remaining,
        "loc_removed": None
        if initial is None or remaining is None
        else initial - remaining,
        "budget_exhausted": getattr(result, "budget_exhausted", False),
    }


def _signature_data(signature: Any) -> dict[str, object] | None:
    if signature is None:
        return None
    return {
        "exception_type": signature.exception_type,
        "message": signature.normalized_message,
        "file": signature.file,
        "function": signature.function,
    }


def _write_new_file(destination: Path, content: str) -> None:
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, destination)
    except OSError:
        _remove_temporary_file(temporary)
        raise
    _remove_temporary_file(temporary)


def _remove_temporary_file(path: Path | None) -> None:
    if path is None:
        return
    try:
        path.unlink()
    except OSError:
        pass


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _mappings(value: object) -> Sequence[Mapping[str, object]]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        return ()
    return tuple(item for item in value if isinstance(item, Mapping))


def _text(value: object) -> str:
    return "" if value is None else str(value)


def _html_value(value: object) -> str:
    return html.escape(_text(value))


def _html_row(*values: str) -> str:
    return (
        "    <tr>"
        + "".join(f"<td>{html.escape(value)}</td>" for value in values)
        + "</tr>"
    )


def _html_list_item(label: str, value: str) -> str:
    """Return one escaped HTML list item with an already-rendered value."""
    return f"    <li>{html.escape(label)}: {value}</li>"


def _size_row(name: str, size: Mapping[str, object]) -> str:
    return _html_row(
        name, _text(size.get("python_files")), _text(size.get("python_loc"))
    )
