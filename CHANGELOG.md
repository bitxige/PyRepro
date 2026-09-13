# PyRepro Change Log

All notable current changes are documented here. Earlier RepoSentinel review
experiments remain available through Git history and the experiment summary.

## [Unreleased]

### Added

- Added P2 grouped/ddmin-inspired file reduction with fresh candidate probes,
  greedy cleanup, explicit 1-minimal verification, and execution-cost metrics.
- Added a deterministic 33-file grouped-failure benchmark that distinguishes
  individual greedy deletion from grouped deletion of a coupled optional pair.
- Added P3 execution-verified top-level symbol reduction with AST source spans,
  decorator-safe deletion, phase-specific metrics, and `--max-granularity`.
- Added the deterministic P3 symbol-failure benchmark and regression coverage
  for source spans, decorators, syntax-error skips, and the file-to-symbol flow.
- Added P1 trusted-local command reduction with the `reduce` subcommand,
  optional `--expect` baseline anchor, default candidate exclusions, and a
  training-failure smoke fixture.
- Added the P0 command-driven failure-reduction workflow: a trusted fixture,
  three-run failure signature, disposable workspace, greedy file reduction,
  final verification, and regression tests.
- Added an ADR and an experiment summary documenting the product pivot to
  execution-verified failure reduction.

### Changed

- Renamed the project, distribution, command, and Python package to PyRepro.
- Reoriented current documentation, architecture, instructions, and CI toward
  command-driven failure reduction.
- Retained the repository scanner, AST analyzer, and path utilities as future
  static-analysis foundations for reduction guidance.

### Removed

- Retired the Codex/MCP review runtime, review profile CLI, review evaluation
  materials, and their dedicated dependencies and tests from the mainline.
