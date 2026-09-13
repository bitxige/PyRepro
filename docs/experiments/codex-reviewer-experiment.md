# Retired Codex reviewer experiment

## Purpose

V0.2 validated a constrained Codex reviewer that could inspect repository
evidence through a local read-only MCP server. V0.3 then compared the
constrained workflow with direct read-only Codex review under a shared policy.

## Result

The constrained tool loop was technically feasible: it produced auditable
evidence calls and could identify the core issue in the smoke fixture.

The experiment did not demonstrate a stable review-quality advantage over
direct Codex review. Constraining access introduced additional latency and
made static evidence more likely to anchor the resulting review. The small
smoke comparison is not evidence that Codex review is generally poor; it is
evidence that this product did not establish enough differentiated value to
remain PyRepro's primary direction.

## Decision

ADR 0007 records the resulting pivot to command-driven, execution-verified
failure reduction. The former runtime and evaluation code are intentionally
removed from the mainline; Git history retains the implementation record.
