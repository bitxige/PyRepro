"""Render optional terminal progress without affecting reduction decisions."""

from __future__ import annotations

import os
import shutil
import sys
from typing import TextIO


class TerminalProgress:
    """Display execution progress on one terminal line when enabled.

    The reporter observes Oracle command starts only. It does not estimate
    candidate success, mutate a workspace, or alter the shared execution
    budget. ``auto`` avoids control sequences in redirected output, while
    ``on`` permits an explicit interactive display.

    Args:
        mode: One of ``auto``, ``on``, or ``off``.
        total_executions: Known execution limit for a bounded run, if any.
        stream: Destination for terminal progress. Defaults to standard error.
        color: Whether to use ANSI color. Defaults to interactive terminals
            that do not request ``NO_COLOR``.

    Raises:
        ValueError: If the display mode or execution limit is invalid.
    """

    _VALID_MODES = frozenset({"auto", "on", "off"})

    def __init__(
        self,
        mode: str,
        *,
        total_executions: int | None = None,
        stream: TextIO | None = None,
        color: bool | None = None,
    ) -> None:
        """Initialize one presentation-only progress reporter."""
        if mode not in self._VALID_MODES:
            raise ValueError(f"unknown progress mode: {mode}")
        if total_executions is not None and total_executions <= 0:
            raise ValueError("total_executions must be positive when supplied")
        self._stream = sys.stderr if stream is None else stream
        interactive = self._stream.isatty()
        self._enabled = mode == "on" or (mode == "auto" and interactive)
        self._color = (
            interactive and not os.environ.get("NO_COLOR") if color is None else color
        )
        self._total_executions = total_executions
        self._executions_started = 0
        self._rendered = False

    def __enter__(self) -> TerminalProgress:
        """Start the optional display context."""
        return self

    def __exit__(self, *_: object) -> None:
        """Finish a rendered line before ordinary CLI output resumes."""
        self.close()

    def advance(self) -> None:
        """Record one started Oracle command and refresh the display."""
        self._executions_started += 1
        self._render(status="running")

    def close(self) -> None:
        """Finish the current display line without emitting when disabled."""
        if not self._rendered:
            return
        self._render(status="finished")
        self._write("\n")
        self._rendered = False

    def _render(self, *, status: str) -> None:
        if not self._enabled:
            return
        bar_width = _bar_width()
        bar, detail = self._bar(bar_width)
        prefix = _style("PyRepro", "36", self._color)
        rendered_bar = _style(bar, "34", self._color)
        rendered_status = _style(status, "32", self._color)
        self._write(f"\r{prefix}  {rendered_bar}  {detail} · {rendered_status}")
        self._rendered = True

    def _bar(self, width: int) -> tuple[str, str]:
        if self._total_executions is not None:
            completed = min(self._executions_started, self._total_executions)
            filled = round(width * completed / self._total_executions)
            return (
                f"[{('█' * filled).ljust(width, '░')}]",
                f"{completed}/{self._total_executions} Oracle runs",
            )
        position = self._executions_started % width
        pulse = "░" * position + "██" + "░" * max(0, width - position - 2)
        return f"[{pulse[:width]}]", f"{self._executions_started} Oracle runs"

    def _write(self, text: str) -> None:
        try:
            self._stream.write(text)
            self._stream.flush()
        except OSError:
            self._enabled = False


def _bar_width() -> int:
    columns = shutil.get_terminal_size(fallback=(80, 24)).columns
    return max(10, min(28, columns - 48))


def _style(text: str, color_code: str, enabled: bool) -> str:
    if not enabled:
        return text
    return f"\033[{color_code}m{text}\033[0m"
