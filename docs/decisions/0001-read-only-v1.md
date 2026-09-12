# ADR 0001: Keep V0.1 read-only

- Status: Accepted
- Date: 2026-09-12

## Context

RepoSentinel inspects repositories supplied by users. The inspected code must
be treated as untrusted input, and the first version is intended to validate
the static-analysis workflow before adding automated review or repair.

## Decision

RepoSentinel V0.1 only reads, searches, parses, and reports on the selected
repository. It must not execute repository code, install repository
dependencies, run repository tests, modify repository files, or generate
patches for the repository.

Generated reports must be written outside the inspected repository.

## Consequences

Positive:

- The initial security boundary is small and testable.
- Results do not change the project being reviewed.
- Static-analysis behavior can be validated independently of execution.

Trade-off:

- V0.1 cannot verify runtime behavior or automatically apply suggestions.
