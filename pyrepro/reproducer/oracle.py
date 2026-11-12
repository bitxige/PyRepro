"""Unified runtime-failure oracle contracts and Python exception support.

An oracle establishes the runtime behavior that a reduction must preserve and
then evaluates every candidate execution against that behavior.  Reducers
accept edits only for :class:`OracleDecision.MATCH`; a missing or incomplete
signal is deliberately not accepted.
"""

from __future__ import annotations

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


def _evaluation(
    decision: OracleDecision,
    reason: str,
    *,
    return_code: int | None,
    signature: FailureSignature | None = None,
) -> OracleEvaluation:
    evidence: dict[str, object] = {"return_code": return_code}
    if signature is not None:
        evidence["exception_type"] = signature.exception_type
        evidence["message"] = signature.normalized_message
        evidence["file"] = signature.file
        evidence["function"] = signature.function
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
