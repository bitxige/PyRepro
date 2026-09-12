# ADR 0003: Use DeepSeek as the first LLM provider for the V0.2 experiment

- Status: Accepted
- Date: 2026-09-12

## Context

The project may add an LLM-powered Review Agent after the V0.1 static
evidence layer is stable. The project plan identifies DeepSeek as the first
provider to evaluate, while avoiding a large agent framework and keeping
provider-specific details out of repository-review logic.

## Decision

For the V0.2 feasibility experiment, evaluate DeepSeek first through its
OpenAI-compatible API. Keep the integration small and direct: it must not
introduce a provider framework or provider-specific logic into repository
analysis. API keys are supplied only through the runtime environment.

## Consequences

Positive:

- The first experiment has a concrete provider and a bounded scope.
- Repository tools and review logic can remain provider-independent.

Trade-off:

- This decision does not yet compare providers or guarantee that DeepSeek is
  the final production choice.
