# PyRepro Change Log

All notable current changes are documented here. Earlier RepoSentinel review
experiments remain available through Git history.

## [Unreleased]

### Changed

- Expanded the GitHub Actions test matrix to cover CPython 3.10, 3.11, and
  3.12.

### Added

- Added default-disabled Fast Mode module-list entry reduction through
  `--max-list-entry-probes`. The conservative stage recognizes only
  unambiguous multiline module-level lists with unique integer-tuple entries,
  probes whole batches before recursively splitting rejected batches, and uses
  exact source-range edits. It shares the existing Oracle/time budget, strict
  oracle, rollback telemetry, staging 3/3 verification, and no-clobber
  publication.

- Added default-disabled Fast Mode module-dictionary entry reduction through
  `--max-container-entry-probes`. The conservative stage recognizes only
  unambiguous multiline module dictionaries with string keys and static values,
  probes whole entry batches before recursively splitting rejected batches, and
  applies exact source-range edits rather than reformatting files. It shares
  the existing Oracle/time budget, strict oracle, rollback telemetry, staging
  3/3 verification, and no-clobber publication.

- Added default-disabled Fast Mode complete-`if` reduction through
  `--max-if-statement-probes`. It greedily probes whole ordinary source `if`
  statements only inside top-level functions and direct methods, re-discovers
  AST candidates after each accepted edit, preserves empty suites with `pass`,
  and skips ambiguous comment or semicolon source ranges. The stage uses the
  existing shared Oracle/time budget, strict failure oracle, rollback telemetry,
  staging 3/3 verification, and no-clobber publication.

- Added default-disabled Fast Mode direct-method reduction through
  `--max-method-probes`. It reuses the complete-symbol reducer only for direct
  methods of module-level classes, shares the existing Oracle/time budget and
  strict Oracle, skips sole methods to preserve valid class syntax, and remains
  subject to the existing staging 3/3 verification and no-clobber publication.
  JSONL probe records now expose whether a rejected source-edit candidate was
  rolled back without changing the active workspace.

- Added opt-in Fast Mode complete-symbol reduction through
  `--max-symbol-probes` and `--symbol-order`. The stage is disabled by default,
  shares the existing Oracle/time budget and probe telemetry, and leaves final
  staging verification and no-clobber publication under the existing Publisher.

- Extended execution-verified import pruning to safely compose top-level
  parenthesized multiline imports with one literal multiline `__all__` update.
  Plans use UTF-8 byte ranges, are rebuilt from current workspace source for
  every probe, and restore the complete edit on rejection or budget stop.
  Existing single-line edit shapes are scheduled as a compatibility cohort
  before P7-only multiline operations under the same bounded probe budget.

- Added opt-in `pyrepro reduce --mode fast` CLI integration for the existing
  preprocessing-first pipeline, shared Oracle/time budgets, staging 3/3
  verification, and verified no-clobber publication. Fast Mode requires an
  explicit pytest node and Oracle budget, reports structured terminal outcomes,
  and never claims an official output when final verification did not publish.

- Added the P5.3a `PreprocessingFirstReducer`, which reuses one disposable
  workspace and one established failure signature across verified import
  pruning and existing greedy file reduction while retaining phase telemetry.
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
