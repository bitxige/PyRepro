# ADR 0002: Separate static facts from contextual LLM judgement

- Status: Accepted
- Date: 2026-09-12

## Context

Static analysis can reliably report facts such as file counts, AST symbols,
line ranges, imports, and docstring presence. It cannot reliably decide that
every long function, missing docstring, or absent CI workflow is an
engineering defect without repository context.

## Decision

Static analyzers produce objective evidence and candidate signals. A future
Review Agent is responsible for contextual engineering judgement. A signal is
not automatically a finding, and V0.1 does not produce a mechanical quality
score.

Important findings should identify a file, symbol, and line or code region
whenever possible.

## Consequences

Positive:

- Findings remain explainable and evidence-backed.
- The system avoids mechanically penalizing harmless style differences.
- Static analysis can be tested independently from model behavior.

Trade-off:

- A useful contextual review requires a later exploration and judgement layer.
