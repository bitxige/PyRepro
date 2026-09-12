# ADR 0003: Use DeepSeek as the first LLM provider for the V0.2 experiment

- Status: Proposed
- Date: 2026-09-12

## Context

The project may add an LLM-powered Review Agent after the V0.1 static
evidence layer is stable. The project plan identifies DeepSeek as the first
provider to evaluate, while avoiding a large agent framework and keeping
provider-specific details out of repository-review logic.

## Decision

For the V0.2 feasibility experiment, evaluate DeepSeek first. The provider
integration must remain replaceable, and no DeepSeek dependency, API key, or
agent loop belongs in V0.1.

## Consequences

Positive:

- The first experiment has a concrete provider and a bounded scope.
- Repository tools and review logic can remain provider-independent.

Trade-off:

- This decision does not yet compare providers or guarantee that DeepSeek is
  the final production choice.
