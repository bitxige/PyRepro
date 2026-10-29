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


def test_disabled_progress_stays_silent_when_forced_stream_is_available():
    """The explicit off mode always overrides a writable output stream."""
    stream = StringIO()

    with TerminalProgress("off", stream=stream) as progress:
        progress.advance()

    assert stream.getvalue() == ""


def test_bounded_progress_never_reports_more_than_its_oracle_limit():
    """A Fast-Mode display caps its visible count at the shared budget."""
    stream = StringIO()

    with TerminalProgress(
        "on", total_executions=2, stream=stream, color=False
    ) as progress:
        progress.advance()
        progress.advance()
        progress.advance()

    assert "2/2 Oracle runs" in stream.getvalue()
    assert "3/2 Oracle runs" not in stream.getvalue()
