# ADR 0007: Pivot to execution-verified failure reduction

## Status

Accepted on 2026-09-13.

## Context

RepoSentinel initially explored static repository evidence and constrained LLM
software-engineering review. The Codex/MCP feasibility work proved that a
restricted evidence loop could operate, but the review comparison did not show
a reliable review-quality advantage over direct Codex use. The constrained
workflow also added latency and made static evidence prone to anchoring the
review.

The P0 command-driven reduction spike independently demonstrated a different
core mechanism: execution can verify whether a smaller Python project still
reproduces a stable failure.

## Decision

The project pivots to PyRepro, an execution-verified Python failure-reduction
tool. LLM-based repository-wide review is no longer the primary product
direction.

The new architectural principle is:

> Static analysis guides reduction; execution validates it.

P0's greedy reducer remains the baseline mechanism. Existing repository
scanning, AST analysis, and path utilities remain available for a later,
explicit static-guidance stage.

## Consequences

- Retire Codex/MCP review runtime code, review profiles, review evaluation,
  and their dedicated dependencies and tests from the mainline.
- Preserve prior ADRs and a concise experiment summary as historical evidence;
  do not rewrite past experiments as if they never occurred.
- Adopt PyRepro in user-facing documentation and distribution metadata. The
  subsequent package-rename refactor will align the internal import path.
- Do not add new reduction functionality in this pivot-only change.
