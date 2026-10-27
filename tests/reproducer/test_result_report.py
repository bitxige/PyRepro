"""Tests for optional final JSON and HTML reduction reports."""

from pathlib import Path

import pytest
from pyrepro.reproducer.result_report import (
    render_html,
    validate_report_paths,
    write_reports,
)


def test_html_report_escapes_untrusted_status_text():
    """Error details cannot turn a static report into executable markup."""
    document = render_html(
        {
            "schema_version": 1,
            "mode": "fast",
            "strategy": "greedy",
            "size": {},
            "oracle": {},
            "final_verification": {},
            "stages": [],
            "status": {
                "terminal_state": "runtime_error",
                "error_message": "<script>alert('unsafe')</script>",
            },
        }
    )

    assert "<script>" not in document
    assert "&lt;script&gt;alert(&#x27;unsafe&#x27;)&lt;/script&gt;" in document


def test_html_report_renders_all_existing_stage_metrics_without_network_assets():
    """The polished view remains a self-contained representation of report data."""
    report = {
        "schema_version": 1,
        "mode": "fast",
        "strategy": "greedy",
        "size": {
            "input": {"python_files": 246, "python_loc": 66892},
            "candidate": {"python_files": 36, "python_loc": 5774},
            "published_output": {"python_files": 36, "python_loc": 5774},
            "loc_removed": 61118,
            "loc_reduction_ratio": 0.9138,
        },
        "oracle": {
            "total_executions": 296,
            "budget": {"max_executions": 450, "remaining_executions": 154},
        },
        "timing": {
            "reduction_wall_clock_seconds": 123.4,
            "run_wall_clock_seconds": 129.7,
        },
        "final_verification": {
            "required_runs": 3,
            "completed_runs": 3,
            "same_failure_runs": 3,
            "passed": True,
        },
        "stages": [
            {
                "name": "file",
                "candidate_attempts": 176,
                "accepted": 210,
                "rejected": 0,
                "executions": 176,
                "loc_removed": 56488,
            },
            {
                "name": "symbol",
                "candidate_attempts": 60,
                "accepted": 19,
                "rejected": 41,
                "executions": 60,
                "loc_removed": 1951,
            },
        ],
        "status": {
            "terminal_state": "completed",
            "verified": True,
            "published": True,
            "source_unchanged": True,
            "output_path": "/tmp/reduced-project",
            "error_message": None,
            "search_budget_exhausted": False,
        },
    }

    document = render_html(report)

    assert report["schema_version"] == 1
    assert "Verified and published" in document
    assert "Reduction at a glance" in document
    assert "91.38%" in document
    assert "129.70 s" in document
    assert '<th scope="row">file</th>' in document
    assert "<td>210</td>" in document
    assert "<span>56488</span>" in document
    assert '<details class="details">' in document
    assert "http://" not in document
    assert "https://" not in document


def test_html_report_labels_unpublished_and_missing_values_truthfully():
    """A failed Fast Mode result cannot receive a successful presentation."""
    document = render_html(
        {
            "schema_version": 1,
            "mode": "fast",
            "strategy": "greedy",
            "size": {"input": {}, "candidate": {}, "published_output": None},
            "oracle": {},
            "timing": {},
            "final_verification": {"required_runs": 3, "passed": False},
            "stages": [],
            "status": {
                "terminal_state": "final_verification_failed",
                "verified": False,
                "published": False,
                "source_unchanged": False,
                "output_path": None,
                "error_message": "<verification did not match>",
            },
        }
    )

    assert "Not verified or unpublished" in document
    assert "Verified and published" not in document
    assert "Unavailable" in document
    assert "&lt;verification did not match&gt;" in document
    assert '<details class="details" open>' in document


def test_report_paths_are_new_and_outside_source_root(tmp_path: Path):
    """Reports cannot overwrite files or be placed in the protected project."""
    source = tmp_path / "source"
    source.mkdir()
    output = tmp_path / "output"
    existing = tmp_path / "existing.json"
    existing.write_text("old\n", encoding="utf-8")

    with pytest.raises(ValueError, match="outside the source root"):
        validate_report_paths(source / "result.json", None, source, output)
    with pytest.raises(ValueError, match="already exists"):
        validate_report_paths(existing, None, source, output)
    with pytest.raises(ValueError, match="must be different"):
        validate_report_paths(
            tmp_path / "same.json", tmp_path / "same.json", source, output
        )


def test_write_reports_does_not_overwrite_existing_destination(tmp_path: Path):
    """Atomic report publication preserves pre-existing user files."""
    destination = tmp_path / "result.json"
    destination.write_text("existing\n", encoding="utf-8")

    with pytest.raises(OSError):
        write_reports({"schema_version": 1}, destination, None)

    assert destination.read_text(encoding="utf-8") == "existing\n"
