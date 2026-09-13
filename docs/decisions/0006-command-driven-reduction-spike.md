# ADR 0006: Validate command-driven failure reduction in an isolated spike

- Status: Accepted
- Date: 2026-09-13

## Context

RepoSentinel's original architecture treats inspected repositories as
untrusted data and never executes their code. The project is evaluating a new
direction: reducing a Python project to a smaller disposable copy that
still reproduces a user-specified runtime failure.

This capability cannot be validated without executing a reproduction command.
It must therefore remain isolated from the read-only review architecture until
its core mechanism is proven useful.

## Decision

Create a P0 spike for command-driven, file-level failure reduction. P0 only
runs the repository-owned deterministic fixture in `examples/failing_project`.
It uses argv execution with `shell=False`, a finite timeout, and a temporary
workspace copied from the fixture. The original fixture is never modified.
P0 assumes that both the fixture and reproduction command are trusted.
`shell=False` avoids shell parsing; it is not a sandbox for arbitrary commands.

P0 establishes a baseline by running the command three times. A baseline is
stable only when each execution has the same exception type, normalized
message, and final in-repository traceback frame (file and function). A
candidate deletion is accepted only when that complete signature remains.

## Consequences

Positive:

- The project can test the execute-delete-verify-restore loop without
  weakening the V0.1 read-only inspection boundary.
- Matching a traceback frame prevents unrelated failures with the same
  exception text from being accepted as the original bug.
- The spike produces a greedy file-reduction baseline for later comparisons.

Limits:

- P0 does not execute arbitrary user repositories, install dependencies, use
  a sandbox, or support flaky failures.
- It does not introduce Codex, MCP, LLMs, ddmin, AST reduction, or custom
  behavior oracles.
