# ADR 0003: Use DeepSeek as the first LLM provider for the V0.2 experiment

- Status: Rejected
- Date: 2026-09-12

## Context

The project may add an LLM-powered Review Agent after the V0.1 static
evidence layer is stable. The project plan identifies DeepSeek as the first
provider to evaluate, while avoiding a large agent framework and keeping
provider-specific details out of repository-review logic.

## Decision

The DeepSeek feasibility branch validated the tool-driven review architecture,
but its implementation was not adopted into the mainline. RepoSentinel
subsequently chose Codex for the next reviewer feasibility experiment.

## Consequences

Positive:

- The experiment provided evidence that a tool-driven reviewer loop is viable.
- The unmerged implementation remains available as an isolated experiment.

Trade-off:

- DeepSeek is not the mainline reviewer integration. ADR 0005 records the
  subsequent Codex decision.
