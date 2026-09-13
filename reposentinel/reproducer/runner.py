"""Execute an argv reproduction command with bounded captured output."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ExecutionResult:
    """Captured result of one reproduction-command execution.

    Attributes:
        command: Exact argv passed to ``subprocess.run``.
        return_code: Process exit code, or ``None`` after a timeout.
        stdout: Captured standard output.
        stderr: Captured standard error.
        timed_out: Whether the command exceeded the configured timeout.
    """

    command: tuple[str, ...]
    return_code: int | None
    stdout: str
    stderr: str
    timed_out: bool


class CommandRunner:
    """Run one argv command from a supplied working directory.

    Args:
        command: Non-empty argv command. It is never interpreted by a shell.
        timeout_seconds: Positive timeout applied to every execution.
    """

    def __init__(self, command: Sequence[str], timeout_seconds: float) -> None:
        """Initialize a runner with a fixed argv command and timeout.

        Args:
            command: Non-empty argv command.
            timeout_seconds: Positive timeout for each process execution.

        Raises:
            ValueError: If the command is empty or timeout is not positive.
        """
        if not command:
            raise ValueError("reproduction command must not be empty")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.command = tuple(command)
        self.timeout_seconds = timeout_seconds

    def run(self, working_directory: Path) -> ExecutionResult:
        """Run the configured command without invoking a shell.

        Args:
            working_directory: Existing directory used as the process cwd.

        Returns:
            Captured process result or a timeout result.

        Raises:
            ValueError: If the supplied working directory is not a directory.
        """
        cwd = working_directory.expanduser().resolve()
        if not cwd.is_dir():
            raise ValueError(f"working directory is not a directory: {cwd}")
        environment = dict(os.environ)
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        try:
            completed = subprocess.run(
                self.command,
                capture_output=True,
                check=False,
                cwd=cwd,
                env=environment,
                shell=False,
                text=True,
                timeout=self.timeout_seconds,
            )
        except subprocess.TimeoutExpired as error:
            return ExecutionResult(
                command=self.command,
                return_code=None,
                stdout=_as_text(error.stdout),
                stderr=_as_text(error.stderr),
                timed_out=True,
            )
        return ExecutionResult(
            command=self.command,
            return_code=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            timed_out=False,
        )


def _as_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return value
