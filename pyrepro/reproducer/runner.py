"""Execute an argv reproduction command with bounded captured output."""

from __future__ import annotations

import locale
import os
import subprocess
from collections.abc import Callable, Sequence
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
        on_execution_start: Optional presentation callback invoked immediately
            before each trusted command starts.
    """

    def __init__(
        self,
        command: Sequence[str],
        timeout_seconds: float,
        *,
        on_execution_start: Callable[[], None] | None = None,
    ) -> None:
        """Initialize a runner with a fixed argv command and timeout.

        Args:
            command: Non-empty argv command.
            timeout_seconds: Positive timeout for each process execution.
            on_execution_start: Optional observer for terminal presentation.

        Raises:
            ValueError: If the command is empty or timeout is not positive.
        """
        if not command:
            raise ValueError("reproduction command must not be empty")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.command = tuple(command)
        self.timeout_seconds = timeout_seconds
        self._on_execution_start = on_execution_start

    def run(
        self, working_directory: Path, *, timeout_seconds: float | None = None
    ) -> ExecutionResult:
        """Run the configured command without invoking a shell.

        Args:
            working_directory: Existing directory used as the process cwd.
            timeout_seconds: Optional per-invocation timeout. When omitted, uses
                the configured runner timeout. It must be positive when supplied.

        Returns:
            Captured process result or a timeout result. Child output is
            decoded tolerantly: UTF-8 is tried first, then the platform locale
            encoding, and undecodable bytes are replaced so that one unusual
            stream cannot abort reduction.

        Raises:
            ValueError: If the supplied working directory is not a directory or
                the supplied per-invocation timeout is not positive.
        """
        cwd = working_directory.expanduser().resolve()
        if not cwd.is_dir():
            raise ValueError(f"working directory is not a directory: {cwd}")
        effective_timeout = (
            self.timeout_seconds if timeout_seconds is None else timeout_seconds
        )
        if effective_timeout <= 0:
            raise ValueError("timeout_seconds must be positive")
        if self._on_execution_start is not None:
            self._on_execution_start()
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
                timeout=effective_timeout,
            )
        except subprocess.TimeoutExpired as error:
            return ExecutionResult(
                command=self.command,
                return_code=None,
                stdout=_decode_output(error.stdout),
                stderr=_decode_output(error.stderr),
                timed_out=True,
            )
        return ExecutionResult(
            command=self.command,
            return_code=completed.returncode,
            stdout=_decode_output(completed.stdout),
            stderr=_decode_output(completed.stderr),
            timed_out=False,
        )


def _decode_output(
    data: bytes | str | None, *, preferred_encoding: str | None = None
) -> str:
    """Decode captured child output without failing on mixed encodings.

    A child process may write UTF-8 chosen by the program or a library, or the
    platform encoding (for example cp936 on Chinese Windows). Decoding all
    output with one strict encoding can abort an otherwise valid reduction, so
    this helper tries UTF-8 first, then the locale encoding, and finally
    replaces undecodable bytes. UTF-8 is attempted first because locale-encoded
    text that is not valid UTF-8 fails cleanly, while UTF-8 text decoded as a
    legacy multi-byte encoding often succeeds as mojibake.

    Args:
        data: Captured bytes from one output stream, an already decoded string,
            or ``None``.
        preferred_encoding: Optional encoding override for tests. Defaults to
            the process locale encoding.

    Returns:
        Decoded text with universal newlines, or an empty string for ``None``
        or empty input.
    """
    if data is None:
        return ""
    if isinstance(data, str):
        return _normalize_newlines(data)
    if not data:
        return ""
    candidates = [
        "utf-8",
        preferred_encoding or locale.getpreferredencoding(False),
    ]
    attempted: set[str] = set()
    for encoding in candidates:
        key = encoding.lower()
        if key in attempted:
            continue
        attempted.add(key)
        try:
            return _normalize_newlines(data.decode(encoding))
        except (LookupError, UnicodeDecodeError):
            continue
    return _normalize_newlines(data.decode("utf-8", errors="replace"))


def _normalize_newlines(text: str) -> str:
    """Apply the universal-newline translation used by subprocess text mode."""
    return text.replace("\r\n", "\n").replace("\r", "\n")
