"""Tests for the RepoSentinel command-line interface."""

import sys

import pytest
from reposentinel.cli import main


def test_cli_rejects_report_inside_inspected_repository(fixture_repo, monkeypatch):
    """Reject output paths that would modify the inspected repository."""
    output = fixture_repo / "report.md"
    monkeypatch.setattr(
        sys,
        "argv",
        ["reposentinel", str(fixture_repo), "--output", str(output)],
    )

    with pytest.raises(SystemExit) as error:
        main()

    assert error.value.code == 2
    assert not output.exists()


def test_cli_writes_report_outside_inspected_repository(fixture_repo, monkeypatch):
    """Write a report successfully when the destination is outside the root."""
    output = fixture_repo.parent / "outside-report.md"
    monkeypatch.setattr(
        sys,
        "argv",
        ["reposentinel", str(fixture_repo), "--output", str(output)],
    )

    assert main() == 0
    assert output.exists()
