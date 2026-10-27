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
