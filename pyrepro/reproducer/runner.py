"""Execute an argv reproduction command with bounded captured output."""

from __future__ import annotations

import locale
import os
import signal
import subprocess
import threading
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from time import monotonic
from typing import BinaryIO

_OUTPUT_CHUNK_BYTES = 64 * 1024
_DEFAULT_MAX_OUTPUT_BYTES = 4 * 1024 * 1024
_READER_JOIN_SECONDS = 5.0
_TRUNCATION_MARKER = b"\n[pyrepro] output truncated; showing the tail\n"


@dataclass(frozen=True)
class ExecutionResult:
    """Captured result of one reproduction-command execution.

    Attributes:
        command: Exact argv passed to the child process.
        return_code: Process exit code, or ``None`` after a timeout.
        stdout: Captured standard output tail.
        stderr: Captured standard error tail.
        timed_out: Whether the command exceeded the configured timeout.
        stdout_truncated: Whether standard output exceeded the retained tail.
        stderr_truncated: Whether standard error exceeded the retained tail.
    """

    command: tuple[str, ...]
    return_code: int | None
    stdout: str
    stderr: str
    timed_out: bool
    stdout_truncated: bool = False
    stderr_truncated: bool = False


class CommandRunner:
    """Run one argv command from a supplied working directory.

    Args:
        command: Non-empty argv command. It is never interpreted by a shell.
        timeout_seconds: Positive timeout applied to every execution.
        on_execution_start: Optional presentation callback invoked immediately
            before each trusted command starts.
        max_output_bytes: Maximum bytes retained per output stream. Only the
            tail is kept because uncaught tracebacks are printed last.
    """

    def __init__(
        self,
        command: Sequence[str],
        timeout_seconds: float,
        *,
        on_execution_start: Callable[[], None] | None = None,
        max_output_bytes: int = _DEFAULT_MAX_OUTPUT_BYTES,
    ) -> None:
        """Initialize a runner with a fixed argv command and timeout.

        Args:
            command: Non-empty argv command.
            timeout_seconds: Positive timeout for each process execution.
            on_execution_start: Optional observer for terminal presentation.
            max_output_bytes: Positive retained tail size per output stream.

        Raises:
            ValueError: If the command is empty, timeout is not positive, or
                the output limit is not positive.
        """
        if not command:
            raise ValueError("reproduction command must not be empty")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if max_output_bytes <= 0:
            raise ValueError("max_output_bytes must be positive")
        self.command = tuple(command)
        self.timeout_seconds = timeout_seconds
        self._on_execution_start = on_execution_start
        self.max_output_bytes = max_output_bytes

    def run(
        self, working_directory: Path, *, timeout_seconds: float | None = None
    ) -> ExecutionResult:
        """Run the configured command without invoking a shell.

        The command receives an empty standard input. A timed-out command and
        its descendants are terminated, and each captured stream retains only
        its final ``max_output_bytes`` bytes.

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
        process = subprocess.Popen(
            self.command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=cwd,
            env=environment,
            shell=False,
            start_new_session=os.name == "posix",
            creationflags=_creation_flags(),
        )
        stdout_capture = _StreamCapture(self.max_output_bytes)
        stderr_capture = _StreamCapture(self.max_output_bytes)
        readers = [
            threading.Thread(
                target=_drain_stream,
                args=(process.stdout, stdout_capture),
                daemon=True,
            ),
            threading.Thread(
                target=_drain_stream,
                args=(process.stderr, stderr_capture),
                daemon=True,
            ),
        ]
        for reader in readers:
            reader.start()
        timed_out = False
        try:
            return_code = process.wait(timeout=effective_timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            _terminate_process_tree(process)
            return_code = process.wait()
        _finish_readers(readers, process)
        return ExecutionResult(
            command=self.command,
            return_code=None if timed_out else return_code,
            stdout=_render(stdout_capture),
            stderr=_render(stderr_capture),
            timed_out=timed_out,
            stdout_truncated=stdout_capture.truncated,
            stderr_truncated=stderr_capture.truncated,
        )


@dataclass
class _StreamCapture:
    """Retain only the tail of one child output stream.

    Attributes:
        limit: Maximum retained bytes.
        chunks: Retained chunks in output order.
        size: Total retained bytes.
        truncated: Whether earlier bytes were discarded.
    """

    limit: int
    chunks: deque[bytes] = field(default_factory=deque)
    size: int = 0
    truncated: bool = False

    def append(self, chunk: bytes) -> None:
        """Append one chunk and discard bytes beyond the retained tail."""
        self.chunks.append(chunk)
        self.size += len(chunk)
        while self.size > self.limit and len(self.chunks[0]) <= self.size - self.limit:
            removed = self.chunks.popleft()
            self.size -= len(removed)
            self.truncated = True
        excess = self.size - self.limit
        if excess > 0:
            self.chunks[0] = self.chunks[0][excess:]
            self.size -= excess
            self.truncated = True

    def to_bytes(self) -> bytes:
        """Return the retained tail as one byte string."""
        return b"".join(self.chunks)


def _creation_flags() -> int:
    """Return platform flags that keep the child in its own process group."""
    if os.name == "nt":
        return subprocess.CREATE_NEW_PROCESS_GROUP
    return 0


def _drain_stream(stream: BinaryIO | None, capture: _StreamCapture) -> None:
    """Read one child stream into a bounded tail buffer until EOF."""
    if stream is None:
        return
    try:
        while True:
            chunk = stream.read(_OUTPUT_CHUNK_BYTES)
            if not chunk:
                break
            capture.append(chunk)
    except (OSError, ValueError):
        return


def _finish_readers(
    readers: Sequence[threading.Thread], process: subprocess.Popen[bytes]
) -> None:
    """Wait for output readers and close pipes if a descendant holds them."""
    deadline = monotonic() + _READER_JOIN_SECONDS
    for reader in readers:
        reader.join(timeout=max(0.0, deadline - monotonic()))
    for stream in (process.stdout, process.stderr):
        if stream is not None:
            try:
                stream.close()
            except OSError:
                pass
    for reader in readers:
        if reader.is_alive():
            reader.join(timeout=1.0)


def _terminate_process_tree(process: subprocess.Popen[bytes]) -> None:
    """Terminate the command and its descendants after a timeout."""
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
            )
        except (OSError, subprocess.SubprocessError):
            pass
    else:
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        except OSError:
            pass
    try:
        process.kill()
    except OSError:
        pass


def _render(capture: _StreamCapture) -> str:
    """Decode a capture and mark output that exceeded the retained tail."""
    text = _decode_output(capture.to_bytes())
    if capture.truncated:
        return _decode_output(_TRUNCATION_MARKER) + text
    return text


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
