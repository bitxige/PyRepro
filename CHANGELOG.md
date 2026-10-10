# PyRepro Change Log

All notable current changes are documented here. Earlier RepoSentinel review
experiments remain available through Git history.

## [Unreleased]

### Added

- Added `pyrepro prune-imports` for bounded, execution-verified batches of
  target-aware import and static `__all__` re-export edits. It works only in a
  disposable workspace, restores rejected batches before bounded splitting,
  keeps risk-marked candidates separate, and does not invoke file or symbol
  reduction.
- Extended optional JSONL probe telemetry with binding-level candidate details
  so source-edit probes can be inspected alongside file-reduction probes.
- Added target-aware, read-only `analyze-imports --pytest-node` analysis for
  explicit pytest function and method node IDs. It separates imports required
  by the target context from imports used only by unrelated tests, reports
  static `__all__` companion lines for consistent later re-export edits, and
  labels import-time side-effect uncertainty without accepting any source edit.
- Added `pyrepro analyze-imports`, a read-only generic analysis command for
  flat and `src` layouts that reports potential unused test imports and package
  re-exports with conservative skip reasons. It does not execute a command or
  modify the source project.
- Added optional `--probe-records` JSONL export for structured file-reduction
  telemetry, including per-probe outcome, timing, candidate LOC, and parsed
  failure details without changing reduction decisions. Reports are atomically
  published without overwriting an existing destination.
- Added structured per-probe telemetry for file reduction, including command
  duration, exit status, parsed exception details, failure signatures, and a
  compact command-line breakdown of different failures and timeouts.
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
- Added a research-only competitor comparison harness and recorded executable
  baseline runs against PyRepro and external reduction tools.
- Added source-integrity digests, three-run comparison verification, separated
  reducer-query and verification metrics, and an experiment-only message
  matching mode for fair reducer comparisons.

### Changed

- Reoriented the competitive-study roadmap toward repository-level dependency
  handling and failure-oracle research rather than native statement-level
  minimization.
- Renamed the project, distribution, command, and Python package to PyRepro.
- Reoriented current documentation, architecture, instructions, and CI toward
  command-driven failure reduction.
- Retained the repository scanner, AST analyzer, and path utilities as future
  static-analysis foundations for reduction guidance.

### Removed

- Removed retired RepoSentinel review ADRs, experiment documentation, and
  local review-era handoff artifacts after the PyRepro product pivot.
- Retired the Codex/MCP review runtime, review profile CLI, review evaluation
  materials, and their dedicated dependencies and tests from the mainline.
