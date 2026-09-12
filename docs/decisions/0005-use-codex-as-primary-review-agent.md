# ADR 0005: Use Codex as the V0.2 review-agent feasibility experiment

- Status: Accepted
- Date: 2026-09-12

## Context

RepoSentinel needs to validate contextual repository review while preserving
its read-only evidence and path-safety boundaries. An earlier DeepSeek branch
validated the general tool-driven architecture but was not adopted into the
mainline.

Codex can run through the locally authenticated ChatGPT/Codex CLI, avoiding an
OpenAI Platform API key for this experiment. Codex is a capable Agent harness,
but RepoSentinel must not give it the target repository as a normal coding
workspace.

## Decision

Use `codex exec` from the Python runtime for the V0.2 feasibility spike. The
spike defaults to `gpt-5.6-luna` with high reasoning effort. It runs Codex in
an isolated temporary working directory and exposes the target repository only
through a required local STDIO MCP server backed by existing `RepositoryTools`.

The MCP server exposes only the five read-only evidence tools. The runtime
disables Codex shell, web search, apps, plugins, and multi-agent tools.

## Consequences

Positive:

- Codex owns the Agent loop while RepoSentinel owns repository evidence,
  tool policy, path safety, and the review contract.
- The target repository is not the Codex working directory and is not exposed
  through arbitrary shell or filesystem tools.
- The runner can audit Codex JSONL events and reject a review without evidence
  calls from the allowed RepoSentinel MCP tools.

Trade-off:

- The spike depends on a local Codex CLI installation and authenticated
  ChatGPT/Codex session.
- Model choice is a configurable default for this experiment, not a permanent
  claim that Luna is the best reviewer for every repository.
