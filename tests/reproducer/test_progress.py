"""Tests for presentation-only terminal reduction progress."""

from __future__ import annotations

from io import StringIO

from pyrepro.reproducer.progress import TerminalProgress


def test_forced_progress_renders_bounded_oracle_count():
    """Forced progress gives Fast Mode a truthful execution-limit display."""
    stream = StringIO()

    with TerminalProgress(
        "on", total_executions=6, stream=stream, color=False
    ) as progress:
        progress.advance()
        progress.advance()

    assert "PyRepro" in stream.getvalue()
    assert "2/6 Oracle runs" in stream.getvalue()
    assert stream.getvalue().endswith("\n")


def test_auto_progress_stays_silent_for_noninteractive_streams():
    """Redirected output remains clean unless the user explicitly enables it."""
    stream = StringIO()

    with TerminalProgress("auto", stream=stream) as progress:
        progress.advance()

    assert stream.getvalue() == ""
