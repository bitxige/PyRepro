# ADR 0004: Defer RAG until the read-only Agent is validated

- Status: Accepted
- Date: 2026-09-12

## Context

RepoSentinel may later use software-engineering guidelines such as PEP 8,
Google Python Style Guide, and a project-specific review guide. Adding RAG,
embeddings, or a vector database before validating repository exploration
would introduce infrastructure without proving that the core review workflow
works.

## Decision

Do not implement RAG, embeddings, or a vector database in V0.1. First validate
whether a read-only Agent can explore an unfamiliar Python repository through
the repository tools and produce evidence-backed review findings. Revisit RAG
only if that experiment shows a concrete need for retrieved guidance.

## Consequences

Positive:

- V0.1 remains small and easy to understand.
- The project can evaluate the core Agent workflow before adding retrieval
  infrastructure.

Trade-off:

- Early Agent experiments will use repository evidence and directly supplied
  guidance rather than a dedicated knowledge base.
