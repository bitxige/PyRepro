"""Unified runtime-failure oracle contracts and Python exception support.

An oracle establishes the runtime behavior that a reduction must preserve and
then evaluates every candidate execution against that behavior.  Reducers
accept edits only for :class:`OracleDecision.MATCH`; a missing or incomplete
signal is deliberately not accepted.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Protocol

from pyrepro.reproducer.failure import (
    FailureMatchMode,
    FailureSignature,
    ReductionOutcome,
)
from pyrepro.reproducer.runner import ExecutionResult


class OracleDecision(str, Enum):
    """Possible conclusions from evaluating one candidate execution."""

    MATCH = "match"
    NO_MATCH = "no_match"
    INCONCLUSIVE = "inconclusive"


@dataclass(frozen=True)
class OracleEvaluation:
    """One oracle decision and its bounded diagnostic evidence.

    Attributes:
        decision: Whether the configured failure was preserved.
        reason: Short explanation suitable for telemetry and user diagnostics.
        evidence: Small structured facts supporting the decision.  It must not
            contain complete captured command output.
    """

    decision: OracleDecision
    reason: str
    evidence: Mapping[str, object]


@dataclass(frozen=True, eq=False)
class OracleBaseline:
    """Stable behavior established by one concrete failure oracle.

    ``state`` is intentionally opaque to reducers.  Only the originating
    oracle may interpret it, which keeps candidate acceptance independent of
    Python exception-specific data structures.

    Attributes:
        oracle: Oracle that established this baseline.
        state: Oracle-private stable baseline state.
        evidence: Bounded baseline facts for diagnostics and reporting.
    """

    oracle: FailureOracle
    state: object
    evidence: Mapping[str, object]

    def evaluate(
        self, result: ExecutionResult, workspace_root: Path
    ) -> OracleEvaluation:
        """Evaluate one candidate through the originating oracle."""
        return self.oracle.evaluate(result, self, workspace_root)

    def describe(self) -> str:
        """Return a concise baseline description for existing CLI summaries."""
        return str(self.evidence.get("description", self.oracle.name))

    @property
    def name(self) -> str:
        """Return the identifier of the oracle that established this baseline."""
        return self.oracle.name

    def __eq__(self, other: object) -> bool:
        """Preserve comparison with the legacy exception signature in V1.1."""
        if isinstance(other, OracleBaseline):
            return (
                self.oracle is other.oracle
                and self.state == other.state
                and self.evidence == other.evidence
            )
        return self.exception_signature == other

    @property
    def exception_signature(self) -> FailureSignature | None:
        """Return the legacy exception signature when this oracle provides one."""
        state = self.state
        return state if isinstance(state, FailureSignature) else None


class FailureOracle(Protocol):
    """Establish and evaluate one user-selected runtime failure condition."""

    @property
    def name(self) -> str:
        """Return the stable oracle identifier used in diagnostics."""

    def establish_baseline(
        self, results: Sequence[ExecutionResult], workspace_root: Path
    ) -> OracleBaseline:
        """Validate stable executions and return their shared baseline."""

    def evaluate(
        self,
        result: ExecutionResult,
        baseline: OracleBaseline,
        workspace_root: Path,
    ) -> OracleEvaluation:
        """Classify one execution against a baseline from this oracle."""


class OracleBaselineError(RuntimeError):
    """Raised when executions cannot establish a stable oracle baseline."""


class PythonExceptionOracle:
    """Preserve the established uncaught-Python-exception failure signature.

    This is the V1 compatibility oracle.  It retains the existing strict and
    message-only matching behavior, including the optional ``--expect`` text
    anchor, while exposing the generic three-state result contract.

    Args:
        match_mode: Strict signature or message-only comparison mode.
        expected_text: Optional required text in the stable baseline summary.
    """

    def __init__(
        self,
        match_mode: FailureMatchMode = FailureMatchMode.STRICT,
        expected_text: str | None = None,
    ) -> None:
        """Store the established exception-identity configuration."""
        self.match_mode = match_mode
        self.expected_text = _normalize_expected_text(expected_text)

    @property
    def name(self) -> str:
        """Return the public identifier for the compatibility oracle."""
        return "python_exception"

    def establish_baseline(
        self, results: Sequence[ExecutionResult], workspace_root: Path
    ) -> OracleBaseline:
        """Require stable uncaught Python failures across all baseline runs."""
        if not results:
            raise OracleBaselineError("baseline requires at least one execution")
        signatures: list[FailureSignature] = []
        for result in results:
            signature = FailureSignature.from_result(result, workspace_root)
            if signature is None:
                raise OracleBaselineError("baseline is not an uncaught Python failure")
            signatures.append(signature)
        baseline = signatures[0]
        if any(not self._matches(signature, baseline) for signature in signatures[1:]):
            raise OracleBaselineError("baseline failure signature is unstable")
        if (
            self.expected_text is not None
            and self.expected_text not in baseline.describe()
        ):
            raise OracleBaselineError(
                "baseline failure does not contain expected text: "
                f"{self.expected_text!r}"
            )
        return OracleBaseline(
            oracle=self,
            state=baseline,
            evidence={
                "description": baseline.describe(),
                "exception_type": baseline.exception_type,
                "message": baseline.normalized_message,
                "file": baseline.file,
                "function": baseline.function,
                "match_mode": self.match_mode.value,
                "config": {
                    "match_mode": self.match_mode.value,
                    "expected_text": self.expected_text,
                },
            },
        )

    def evaluate(
        self,
        result: ExecutionResult,
        baseline: OracleBaseline,
        workspace_root: Path,
    ) -> OracleEvaluation:
        """Evaluate one command result without accepting incomplete evidence."""
        if baseline.oracle is not self or not isinstance(
            baseline.state, FailureSignature
        ):
            raise ValueError("baseline was not established by this exception oracle")
        if result.timed_out:
            return _evaluation(
                OracleDecision.INCONCLUSIVE,
                "command timed out",
                return_code=result.return_code,
            )
        if result.return_code == 0:
            return _evaluation(
                OracleDecision.NO_MATCH,
                "command completed successfully",
                return_code=result.return_code,
            )
        signature = FailureSignature.from_result(result, workspace_root)
        if signature is None:
            return _evaluation(
                OracleDecision.NO_MATCH,
                "execution did not produce a supported Python exception signature",
                return_code=result.return_code,
            )
        if self._matches(signature, baseline.state):
            return _evaluation(
                OracleDecision.MATCH,
                "Python exception signature matches the established baseline",
                return_code=result.return_code,
                signature=signature,
            )
        return _evaluation(
            OracleDecision.NO_MATCH,
            "Python exception signature differs from the established baseline",
            return_code=result.return_code,
            signature=signature,
        )

    def _matches(self, candidate: FailureSignature, baseline: FailureSignature) -> bool:
        if self.match_mode is FailureMatchMode.MESSAGE:
            return candidate.normalized_message == baseline.normalized_message
        return candidate == baseline


class ExitCodeOracle:
    """Preserve one user-configured process exit code.

    Args:
        expected_exit_code: Process exit code that represents the target
            failure. A candidate is accepted only when it exits with this
            exact code and does not time out.
    """

    def __init__(self, expected_exit_code: int) -> None:
        """Store the user-defined target exit code."""
        self.expected_exit_code = expected_exit_code

    @property
    def name(self) -> str:
        """Return the public identifier for exit-code matching."""
        return "exit_code"

    def establish_baseline(
        self, results: Sequence[ExecutionResult], workspace_root: Path
    ) -> OracleBaseline:
        """Require every baseline run to exit with the configured code."""
        del workspace_root
        if not results:
            raise OracleBaselineError("baseline requires at least one execution")
        for result in results:
            if result.timed_out or result.return_code != self.expected_exit_code:
                raise OracleBaselineError(
                    "baseline did not exit with expected code "
                    f"{self.expected_exit_code}"
                )
        return OracleBaseline(
            oracle=self,
            state=self.expected_exit_code,
            evidence={
                "description": f"exit code {self.expected_exit_code}",
                "expected_exit_code": self.expected_exit_code,
                "config": {"expected_exit_code": self.expected_exit_code},
            },
        )

    def evaluate(
        self,
        result: ExecutionResult,
        baseline: OracleBaseline,
        workspace_root: Path,
    ) -> OracleEvaluation:
        """Classify one result against the configured exit code."""
        del workspace_root
        if baseline.oracle is not self or baseline.state != self.expected_exit_code:
            raise ValueError("baseline was not established by this exit-code oracle")
        if result.timed_out:
            return _evaluation(
                OracleDecision.INCONCLUSIVE,
                "command timed out",
                return_code=result.return_code,
            )
        if result.return_code == self.expected_exit_code:
            return _evaluation(
                OracleDecision.MATCH,
                "exit code matches the configured target",
                return_code=result.return_code,
            )
        return _evaluation(
            OracleDecision.NO_MATCH,
            "exit code differs from the configured target",
            return_code=result.return_code,
        )


class OutputTextOracle:
    """Preserve a configured literal or regular-expression output marker.

    A match in any selected stream is sufficient. A non-match is inconclusive
    when a selected stream was truncated because the marker might have occurred
    in discarded output.

    Args:
        stream: ``stdout``, ``stderr``, or ``both``.
        match_mode: ``literal`` or ``regex``.
        pattern: Non-empty text or regular expression to search for.
    """

    _VALID_STREAMS = frozenset({"stdout", "stderr", "both"})
    _VALID_MATCH_MODES = frozenset({"literal", "regex"})

    def __init__(self, stream: str, match_mode: str, pattern: str) -> None:
        """Validate and compile one output-matching configuration."""
        if stream not in self._VALID_STREAMS:
            raise ValueError("output stream must be stdout, stderr, or both")
        if match_mode not in self._VALID_MATCH_MODES:
            raise ValueError("output match mode must be literal or regex")
        if not pattern:
            raise ValueError("output pattern must not be empty")
        self.stream = stream
        self.match_mode = match_mode
        self.pattern = pattern
        try:
            self._regex = re.compile(pattern) if match_mode == "regex" else None
        except re.error as error:
            raise ValueError(f"invalid output regular expression: {error}") from error

    @property
    def name(self) -> str:
        """Return the public identifier for output-text matching."""
        return "output_text"

    def establish_baseline(
        self, results: Sequence[ExecutionResult], workspace_root: Path
    ) -> OracleBaseline:
        """Require every baseline result to contain the configured marker."""
        if not results:
            raise OracleBaselineError("baseline requires at least one execution")
        baseline = OracleBaseline(
            oracle=self,
            state=(self.stream, self.match_mode, self.pattern),
            evidence={
                "description": self._description(),
                "config": {
                    "stream": self.stream,
                    "match_mode": self.match_mode,
                    "pattern": self.pattern,
                },
            },
        )
        for result in results:
            evaluation = self.evaluate(result, baseline, workspace_root)
            if evaluation.decision is not OracleDecision.MATCH:
                raise OracleBaselineError(
                    "baseline did not match configured output pattern: "
                    f"{evaluation.reason}"
                )
        return baseline

    def evaluate(
        self,
        result: ExecutionResult,
        baseline: OracleBaseline,
        workspace_root: Path,
    ) -> OracleEvaluation:
        """Classify one command result by bounded selected-stream output."""
        del workspace_root
        if baseline.oracle is not self or baseline.state != (
            self.stream,
            self.match_mode,
            self.pattern,
        ):
            raise ValueError("baseline was not established by this output oracle")
        if result.timed_out:
            return _evaluation(
                OracleDecision.INCONCLUSIVE,
                "command timed out",
                return_code=result.return_code,
                extra_evidence=self._evidence(result),
            )
        if any(self._matches(text) for text in self._selected_streams(result)):
            return _evaluation(
                OracleDecision.MATCH,
                "configured output pattern was found",
                return_code=result.return_code,
                extra_evidence=self._evidence(result),
            )
        if self._selected_output_was_truncated(result):
            return _evaluation(
                OracleDecision.INCONCLUSIVE,
                "configured output pattern was not found in truncated output",
                return_code=result.return_code,
                extra_evidence=self._evidence(result),
            )
        return _evaluation(
            OracleDecision.NO_MATCH,
            "configured output pattern was not found",
            return_code=result.return_code,
            extra_evidence=self._evidence(result),
        )

    def _matches(self, text: str) -> bool:
        if self._regex is not None:
            return self._regex.search(text) is not None
        return self.pattern in text

    def _selected_streams(self, result: ExecutionResult) -> tuple[str, ...]:
        streams: list[str] = []
        if self.stream in {"stdout", "both"}:
            streams.append(result.stdout)
        if self.stream in {"stderr", "both"}:
            streams.append(result.stderr)
        return tuple(streams)

    def _selected_output_was_truncated(self, result: ExecutionResult) -> bool:
        return (self.stream in {"stdout", "both"} and result.stdout_truncated) or (
            self.stream in {"stderr", "both"} and result.stderr_truncated
        )

    def _description(self) -> str:
        return f"{self.stream} {self.match_mode} output pattern {self.pattern!r}"

    def _evidence(self, result: ExecutionResult) -> Mapping[str, object]:
        return {
            "stream": self.stream,
            "match_mode": self.match_mode,
            "pattern": self.pattern,
            "stdout_truncated": result.stdout_truncated,
            "stderr_truncated": result.stderr_truncated,
        }


def _evaluation(
    decision: OracleDecision,
    reason: str,
    *,
    return_code: int | None,
    signature: FailureSignature | None = None,
    extra_evidence: Mapping[str, object] | None = None,
) -> OracleEvaluation:
    evidence: dict[str, object] = {"return_code": return_code}
    if signature is not None:
        evidence["exception_type"] = signature.exception_type
        evidence["message"] = signature.normalized_message
        evidence["file"] = signature.file
        evidence["function"] = signature.function
    if extra_evidence is not None:
        evidence.update(extra_evidence)
    return OracleEvaluation(decision, reason, evidence)


def legacy_outcome(
    result: ExecutionResult, evaluation: OracleEvaluation
) -> ReductionOutcome:
    """Map a generic decision to the legacy telemetry outcome categories.

    ``ReductionOutcome`` remains in V1.1 records for report compatibility;
    reducers must make acceptance decisions from ``OracleDecision`` instead.
    """
    if evaluation.decision is OracleDecision.MATCH:
        return ReductionOutcome.SAME_FAILURE
    if evaluation.decision is OracleDecision.INCONCLUSIVE:
        return ReductionOutcome.TIMEOUT
    if result.return_code == 0:
        return ReductionOutcome.PASS
    return ReductionOutcome.DIFFERENT_FAILURE


def coerce_oracle_baseline(
    baseline: OracleBaseline | FailureSignature,
    match_mode: FailureMatchMode,
) -> OracleBaseline:
    """Adapt legacy exception-signature callers to the V1.1 baseline contract.

    Production pipeline paths establish an :class:`OracleBaseline` directly.
    This bridge exists only for retained public helper and test compatibility.
    """
    if isinstance(baseline, OracleBaseline):
        return baseline
    oracle = PythonExceptionOracle(match_mode)
    return OracleBaseline(
        oracle=oracle,
        state=baseline,
        evidence={
            "description": baseline.describe(),
            "exception_type": baseline.exception_type,
            "message": baseline.normalized_message,
            "file": baseline.file,
            "function": baseline.function,
            "match_mode": match_mode.value,
        },
    )


def _normalize_expected_text(expected_text: str | None) -> str | None:
    if expected_text is None:
        return None
    normalized = " ".join(expected_text.split())
    if not normalized:
        raise ValueError("expected_text must not be blank")
    return normalized
