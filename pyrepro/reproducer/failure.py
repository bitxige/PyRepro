"""Extract and compare deterministic uncaught Python failure signatures."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from pyrepro.reproducer.runner import ExecutionResult

_TRACEBACK_MARKER = "Traceback (most recent call last):"
_FRAME_PATTERN = re.compile(
    r'^\s*File "(?P<file>.+)", line \d+, in (?P<function>.+)$', re.MULTILINE
)
_EXCEPTION_PATTERN = re.compile(
    r"^(?P<exception_type>[A-Za-z_][A-Za-z0-9_.]*):\s*(?P<message>.*)$"
)


class ReductionOutcome(Enum):
    """Possible outcomes after evaluating a candidate command execution."""

    SAME_FAILURE = "same_failure"
    DIFFERENT_FAILURE = "different_failure"
    PASS = "pass"
    TIMEOUT = "timeout"


@dataclass(frozen=True)
class FailureSignature:
    """Stable identity for an uncaught Python exception.

    Attributes:
        exception_type: Final Python exception class name from stderr.
        normalized_message: Whitespace-normalized final exception message.
        file: Repository-relative file for the final in-repository traceback frame.
        function: Function name from the final in-repository traceback frame.
    """

    exception_type: str
    normalized_message: str
    file: str
    function: str

    @classmethod
    def from_result(
        cls, result: ExecutionResult, workspace_root: Path
    ) -> FailureSignature | None:
        """Extract a signature from an uncaught Python traceback.

        Args:
            result: Captured command result.
            workspace_root: Root used to convert traceback paths to relative paths.

        Returns:
            A complete signature, or ``None`` when stderr is not a supported
            uncaught Python traceback.
        """
        if result.timed_out or result.return_code == 0:
            return None
        if _TRACEBACK_MARKER not in result.stderr:
            return None
        exception = _last_exception(result.stderr)
        frame = _last_in_workspace_frame(result.stderr, workspace_root)
        if exception is None or frame is None:
            return None
        exception_type, message = exception
        file, function = frame
        return cls(
            exception_type=exception_type,
            normalized_message=" ".join(message.split()),
            file=file,
            function=function,
        )

    def describe(self) -> str:
        """Return a concise human-readable failure description.

        Returns:
            Exception and final traceback-frame summary.
        """
        return (
            f"{self.exception_type}: {self.normalized_message}\n"
            f"{self.file}::{self.function}"
        )


def classify_result(
    result: ExecutionResult, baseline: FailureSignature, workspace_root: Path
) -> ReductionOutcome:
    """Classify a command result against the required baseline failure.

    Args:
        result: Candidate command result.
        baseline: Stable failure that must remain present.
        workspace_root: Root for traceback-path normalization.

    Returns:
        The candidate reduction outcome.
    """
    if result.timed_out:
        return ReductionOutcome.TIMEOUT
    if result.return_code == 0:
        return ReductionOutcome.PASS
    signature = FailureSignature.from_result(result, workspace_root)
    if signature == baseline:
        return ReductionOutcome.SAME_FAILURE
    return ReductionOutcome.DIFFERENT_FAILURE


def _last_exception(stderr: str) -> tuple[str, str] | None:
    for line in reversed(stderr.splitlines()):
        match = _EXCEPTION_PATTERN.match(line.strip())
        if match is not None:
            return match["exception_type"], match["message"]
    return None


def _last_in_workspace_frame(
    stderr: str, workspace_root: Path
) -> tuple[str, str] | None:
    root = workspace_root.expanduser().resolve()
    final_frame: tuple[str, str] | None = None
    for match in _FRAME_PATTERN.finditer(stderr):
        frame_path = Path(match["file"]).expanduser().resolve()
        try:
            relative_path = frame_path.relative_to(root)
        except ValueError:
            continue
        final_frame = relative_path.as_posix(), match["function"]
    return final_frame
