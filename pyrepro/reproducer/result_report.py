"""Build and publish optional JSON and HTML reduction-result reports.

Reports summarize results that existing reducers, the shared Fast-Mode budget,
and the Publisher already produced.  They never participate in candidate
selection or acceptance decisions.
"""

# ruff: noqa: E501
# The self-contained HTML/CSS template intentionally retains long literal lines
# so report source stays readable as a document rather than fragmented pieces.

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
    final_verification_executions = max(
        0, budget.executions_started - reduction.executions
    )
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
            "final_verification_executions": final_verification_executions,
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
            "oracle_executions": final_verification_executions,
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
            "final_verification_executions": 1,
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
            "oracle_executions": 1,
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
    """Render one accessible, self-contained HTML view of a report mapping.

    The JSON report remains the source of truth. This renderer only formats
    available values, labels missing values consistently, and escapes every
    report-supplied text value before it reaches the document.
    """
    title = "PyRepro reduction report"
    size = _mapping(report.get("size"))
    status = _mapping(report.get("status"))
    oracle = _mapping(report.get("oracle"))
    timing = _mapping(report.get("timing"))
    verification = _mapping(report.get("final_verification"))
    budget = _mapping(oracle.get("budget"))
    stages = _mappings(report.get("stages"))
    input_size = _mapping(size.get("input"))
    candidate_size = _mapping(size.get("candidate"))
    published_size = _mapping(size.get("published_output"))
    displayed_output = published_size or candidate_size
    status_class, status_label = _report_status(status)
    loc_ratio = _as_number(size.get("loc_reduction_ratio"))
    max_stage_loc = max(
        (_as_number(stage.get("loc_removed")) or 0.0 for stage in stages),
        default=0.0,
    )
    stage_rows = "\n".join(_stage_row(stage, max_stage_loc) for stage in stages)
    ratio_percent = _percent(loc_ratio)
    progress_width = _progress_width(loc_ratio)
    verification_runs = _verification_runs(verification)
    completed_runs = _html_value(verification.get("completed_runs"))
    terminal_state = _html_value(status.get("terminal_state"))
    error_message = _html_value(status.get("error_message"))
    return "\n".join(
        (
            "<!doctype html>",
            '<html lang="en">',
            "<head>",
            '  <meta charset="utf-8">',
            '  <meta name="viewport" content="width=device-width, initial-scale=1">',
            f"  <title>{html.escape(title)}</title>",
            "  <style>",
            _REPORT_STYLES,
            "  </style>",
            "</head>",
            "<body>",
            "  <main>",
            '    <header class="report-header">',
            "      <div>",
            '        <p class="eyebrow">PyRepro · reduction report</p>',
            f"        <h1>{html.escape(title)}</h1>",
            '        <p class="subtitle">'
            f"Schema v{_html_value(report.get('schema_version'))} · "
            f"{_html_value(report.get('mode'))} mode · "
            f"{_html_value(report.get('strategy'))} strategy</p>",
            "      </div>",
            f'      <p class="status-badge {status_class}">{status_label}</p>',
            "    </header>",
            '    <section aria-labelledby="metrics-heading">',
            '      <h2 id="metrics-heading">Reduction at a glance</h2>',
            '      <div class="metric-grid">',
            _metric_card("LOC reduction", ratio_percent, "of input Python LOC removed"),
            _metric_card(
                "LOC removed",
                _html_value(size.get("loc_removed")),
                "net physical lines",
            ),
            _metric_card(
                "Python files",
                f"{_html_value(input_size.get('python_files'))} → "
                f"{_html_value(displayed_output.get('python_files'))}",
                "input to reported output",
            ),
            _metric_card(
                "Oracle executions",
                _html_value(oracle.get("total_executions")),
                "reduction and final-verification commands",
            ),
            _metric_card(
                "End-to-end runtime",
                _duration(timing.get("run_wall_clock_seconds")),
                "including final verification",
            ),
            "      </div>",
            "    </section>",
            '    <section class="panel" aria-labelledby="comparison-heading">',
            '      <div class="section-heading">',
            "        <div>",
            '          <p class="eyebrow">Size comparison</p>',
            '          <h2 id="comparison-heading">From input to result</h2>',
            "        </div>",
            f"        <strong>{ratio_percent} LOC reduction</strong>",
            "      </div>",
            '      <div class="comparison-grid">',
            _size_card("Input", input_size),
            _size_card("Accepted candidate", candidate_size),
            _size_card("Published output", published_size),
            "      </div>",
            '      <div class="progress-label"><span>LOC reduction</span>'
            f"<span>{ratio_percent}</span></div>",
            '      <div class="progress-track" role="progressbar" '
            'aria-label="Python LOC reduction" '
            f'aria-valuemin="0" aria-valuemax="100" aria-valuenow="{progress_width}">'
            f'<span style="width:{progress_width}%"></span></div>',
            "    </section>",
            '    <section class="status-grid" aria-label="Verification and safety">',
            _status_card(
                "Final verification",
                verification_runs,
                f"{completed_runs} completed run(s); passed: "
                f"{_html_value(verification.get('passed'))}",
            ),
            _status_card(
                "Source integrity",
                _html_value(status.get("source_unchanged")),
                "protected input repository remained unchanged",
            ),
            _status_card(
                "Publication",
                _html_value(status.get("published")),
                "official output is created only after verification",
            ),
            "    </section>",
            '    <section class="panel" aria-labelledby="stages-heading">',
            '      <div class="section-heading">',
            "        <div>",
            '          <p class="eyebrow">Execution evidence</p>',
            '          <h2 id="stages-heading">Reduction stages</h2>',
            "        </div>",
            '        <p class="muted">Stage bars compare only recorded LOC removal.</p>',
            "      </div>",
            '      <div class="table-wrap">',
            "        <table>",
            "          <thead><tr><th>Stage</th><th>Candidate probes</th>"
            "<th>Accepted</th><th>Rejected</th><th>Oracle executions</th>"
            "<th>LOC removed</th></tr></thead>",
            "          <tbody>",
            stage_rows
            or '            <tr><td colspan="6">No stage data available.</td></tr>',
            "          </tbody>",
            "        </table>",
            "      </div>",
            "    </section>",
            f'    <details class="details"{" open" if status.get("error_message") is not None else ""}>',
            "      <summary>Execution details</summary>",
            "      <dl>",
            _detail_row("Terminal state", terminal_state),
            _detail_row("Output path", _html_value(status.get("output_path"))),
            _detail_row(
                "Reduction runtime",
                _duration(timing.get("reduction_wall_clock_seconds")),
            ),
            _detail_row("Budget maximum", _html_value(budget.get("max_executions"))),
            _detail_row(
                "Reduction Oracle executions",
                _html_value(oracle.get("reduction_executions")),
            ),
            _detail_row(
                "Final-verification executions",
                _html_value(oracle.get("final_verification_executions")),
            ),
            _detail_row(
                "Budget remaining", _html_value(budget.get("remaining_executions"))
            ),
            _detail_row(
                "Search budget exhausted",
                _html_value(status.get("search_budget_exhausted")),
            ),
            _detail_row("Error", error_message),
            "      </dl>",
            "    </details>",
            "  </main>",
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
    """Return eligible Python-file counts relative to one project root.

    Ignore rules apply to directories inside ``root`` only.  An output project
    may legitimately be named ``output``; checking absolute path components
    would otherwise hide every file in that published project.
    """
    files = tuple(
        path
        for path in root.rglob("*.py")
        if not any(
            part in DEFAULT_IGNORED_DIRECTORY_NAMES
            for part in path.relative_to(root).parts
        )
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
        ("main_guard", reduction.main_guard_reduction, "accepted_batches"),
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
    return "Unavailable" if value is None else str(value)


def _html_value(value: object) -> str:
    return html.escape(_text(value))


def _report_status(status: Mapping[str, object]) -> tuple[str, str]:
    """Return a controlled visual class and plain-language status label."""
    verified = status.get("verified") is True
    published = status.get("published") is True
    if verified and published:
        return "success", "Verified and published"
    if verified:
        return "warning", "Verified; not published"
    if published:
        return "danger", "Published without verification"
    return "danger", "Not verified or unpublished"


def _as_number(value: object) -> float | None:
    """Return a finite report number without treating booleans as counts."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _percent(value: float | None) -> str:
    if value is None:
        return "Unavailable"
    return f"{value * 100:.2f}%"


def _progress_width(value: float | None) -> int:
    """Clamp a data-derived ratio for a purely presentational CSS bar."""
    if value is None:
        return 0
    return round(min(1.0, max(0.0, value)) * 100)


def _duration(value: object) -> str:
    number = _as_number(value)
    return "Unavailable" if number is None else f"{number:.2f} s"


def _metric_card(label: str, value: str, description: str) -> str:
    """Render a metric card from pre-escaped values and fixed labels."""
    return "\n".join(
        (
            '        <article class="metric-card">',
            f"          <p>{html.escape(label)}</p>",
            f"          <strong>{value}</strong>",
            f"          <span>{html.escape(description)}</span>",
            "        </article>",
        )
    )


def _size_card(label: str, size: Mapping[str, object]) -> str:
    """Render one artifact's size with unavailable values made explicit."""
    return "\n".join(
        (
            '        <article class="size-card">',
            f"          <p>{html.escape(label)}</p>",
            f"          <strong>{_html_value(size.get('python_loc'))} LOC</strong>",
            f"          <span>{_html_value(size.get('python_files'))} Python files</span>",
            "        </article>",
        )
    )


def _status_card(label: str, value: str, description: str) -> str:
    """Render an explicit textual status card without relying only on color."""
    return "\n".join(
        (
            '      <article class="status-card">',
            f"        <p>{html.escape(label)}</p>",
            f"        <strong>{value}</strong>",
            f"        <span>{html.escape(description)}</span>",
            "      </article>",
        )
    )


def _stage_row(stage: Mapping[str, object], maximum_loc: float) -> str:
    """Render all existing stage values plus a data-backed LOC bar."""
    removed = _as_number(stage.get("loc_removed"))
    width = (
        0 if maximum_loc <= 0 or removed is None else round(removed / maximum_loc * 100)
    )
    return "\n".join(
        (
            "            <tr>",
            f'              <th scope="row">{_html_value(stage.get("name"))}</th>',
            f"              <td>{_html_value(stage.get('candidate_attempts'))}</td>",
            f"              <td>{_html_value(stage.get('accepted'))}</td>",
            f"              <td>{_html_value(stage.get('rejected'))}</td>",
            f"              <td>{_html_value(stage.get('executions'))}</td>",
            "              <td>",
            f"                <span>{_html_value(stage.get('loc_removed'))}</span>",
            '                <span class="stage-bar" aria-hidden="true">'
            f'<span style="width:{width}%"></span></span>',
            "              </td>",
            "            </tr>",
        )
    )


def _verification_runs(verification: Mapping[str, object]) -> str:
    """Format the available verification evidence without assuming success."""
    return (
        f"{_html_value(verification.get('same_failure_runs'))}/"
        f"{_html_value(verification.get('required_runs'))} same-failure runs"
    )


def _detail_row(label: str, value: str) -> str:
    return f"        <dt>{html.escape(label)}</dt><dd>{value}</dd>"


_REPORT_STYLES = """
    :root { color-scheme: light; --ink:#172033; --muted:#65708a; --line:#d9e0ec;
      --panel:#ffffff; --canvas:#f4f7fb; --blue:#245ac7; --blue-soft:#eaf1ff;
      --green:#14734a; --green-soft:#eaf8f1; --amber:#9a5b00; --amber-soft:#fff5df;
      --red:#b42318; --red-soft:#fff0ee; }
    * { box-sizing:border-box; }
    body { margin:0; background:var(--canvas); color:var(--ink); font:15px/1.55
      Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
    main { max-width:1120px; margin:0 auto; padding:40px 24px 56px; }
    h1,h2,p { margin:0; } h1 { margin-top:4px; font-size:clamp(2rem, 5vw, 3.25rem);
      line-height:1.08; letter-spacing:-.045em; } h2 { font-size:1.15rem; }
    .report-header,.section-heading { display:flex; align-items:flex-start; justify-content:space-between;
      gap:24px; } .report-header { margin-bottom:38px; }
    .eyebrow { color:var(--blue); font-size:.73rem; font-weight:750; letter-spacing:.12em;
      text-transform:uppercase; } .subtitle,.muted { margin-top:8px; color:var(--muted); }
    .status-badge { max-width:240px; margin:0; border:1px solid transparent; border-radius:999px;
      padding:8px 12px; font-size:.85rem; font-weight:750; text-align:center; }
    .status-badge.success { color:var(--green); background:var(--green-soft); border-color:#9cdec1; }
    .status-badge.warning { color:var(--amber); background:var(--amber-soft); border-color:#ead18f; }
    .status-badge.danger { color:var(--red); background:var(--red-soft); border-color:#efb1aa; }
    .metric-grid { display:grid; grid-template-columns:repeat(5,minmax(0,1fr)); gap:12px; margin:16px 0 30px; }
    .metric-card,.size-card,.status-card,.panel,.details { background:var(--panel); border:1px solid var(--line);
      border-radius:14px; box-shadow:0 6px 20px rgba(26,46,78,.045); }
    .metric-card { min-height:130px; padding:17px; } .metric-card p,.size-card p,.status-card p { color:var(--muted);
      font-size:.78rem; font-weight:650; } .metric-card strong,.size-card strong,.status-card strong { display:block;
      margin:8px 0 5px; font-size:1.35rem; line-height:1.15; letter-spacing:-.025em; overflow-wrap:anywhere; }
    .metric-card span,.size-card span,.status-card span { color:var(--muted); font-size:.76rem; }
    .panel { margin-top:22px; padding:22px; } .section-heading { margin-bottom:18px; }
    .section-heading strong { color:var(--blue); font-size:.9rem; }
    .comparison-grid,.status-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:12px; }
    .size-card,.status-card { padding:16px; } .size-card { border-top:3px solid var(--blue); }
    .progress-label { display:flex; justify-content:space-between; margin-top:20px; color:var(--muted); font-size:.82rem; }
    .progress-track,.stage-bar { display:block; overflow:hidden; background:#e7edf7; border-radius:999px; }
    .progress-track { height:10px; margin-top:7px; } .progress-track span,.stage-bar span { display:block;
      height:100%; background:linear-gradient(90deg, #245ac7, #4980e8); border-radius:inherit; }
    .status-grid { margin:22px 0; } .status-card strong { color:var(--blue); }
    .table-wrap { overflow-x:auto; } table { width:100%; min-width:760px; border-collapse:collapse; font-size:.87rem; }
    th,td { border-bottom:1px solid var(--line); padding:11px 10px; text-align:left; vertical-align:middle; }
    thead th { color:var(--muted); font-size:.73rem; letter-spacing:.04em; text-transform:uppercase; }
    tbody tr:last-child th,tbody tr:last-child td { border-bottom:0; } tbody th { font-weight:700; }
    .stage-bar { width:100%; min-width:80px; height:6px; margin-top:5px; }
    .details { margin-top:22px; padding:0 20px; } summary { cursor:pointer; padding:16px 0; font-weight:750; }
    dl { display:grid; grid-template-columns:max-content minmax(0,1fr); gap:9px 20px; margin:0; padding:0 0 20px; }
    dt { color:var(--muted); } dd { margin:0; overflow-wrap:anywhere; }
    @media (max-width:850px) { .metric-grid { grid-template-columns:repeat(3,minmax(0,1fr)); } }
    @media (max-width:620px) { main { padding:28px 16px 40px; } .report-header,.section-heading { display:block; }
      .status-badge { display:inline-block; margin-top:16px; } .metric-grid,.comparison-grid,.status-grid { grid-template-columns:1fr; }
      .panel { padding:17px; } dl { grid-template-columns:1fr; gap:3px; } dd { margin-bottom:10px; } }
    @media print { body { background:#fff; font-size:11pt; } main { max-width:none; padding:0; } .metric-card,.size-card,
      .status-card,.panel,.details { box-shadow:none; break-inside:avoid; } .details { display:block; } details:not([open]) > *:not(summary) { display:block; }
      .table-wrap { overflow:visible; } table { min-width:0; } }
"""
