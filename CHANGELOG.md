## [Unreleased]

### Fixed

- Corrected command-output decoding so UTF-8 child output no longer aborts a
  reduction on a non-UTF-8 locale such as Chinese Windows.

- Fixed coarse-group splitting for candidates in sibling directories,
  preventing Standard Mode from failing while computing relative probe paths.

- Target-aware Standard and Fast Mode now reject non-Linux platforms before
  any baseline or search command starts, with a message pointing to Linux/WSL
  or legacy Standard Mode. Previously the run consumed its baseline and
  search budget before the publisher failed on the unsupported platform.

### Changed

- Expanded the V1.1 failure-oracle contract into user-configurable product
  behavior. `reduce` and `prune-imports` now support exact exit-code matching
  and literal or regular-expression markers in stdout, stderr, or either
  stream. Timeouts and absent markers in truncated selected output remain
  inconclusive and cannot accept an edit. JSON/HTML reports and JSONL probe
  telemetry now identify the Oracle configuration and bounded decision evidence;
  the report schema is version 3.

- Introduced the internal V1.1 failure-oracle contract. Production reduction
  and staging publication now establish and evaluate a shared three-state
  Oracle baseline (`match`, `no_match`, or `inconclusive`) while retaining
  the existing Python exception CLI behavior and strict/message compatibility.

- Source-integrity digests now exclude version-control metadata, caches, build
  outputs, and local environments, and prune those directories during traversal.
  Data and model directories remain covered. This avoids false "source changed"
  results from `.git` or cache activity and reduces digest cost on real
  repositories.

- Bounded command execution in the runner. Each command now receives an empty
  standard input, a timed-out command has its descendant processes terminated,
  and each captured output stream retains only its final 4 MiB (including a
  truncation marker). A command that reads stdin, spawns workers, or prints
  excessive output no longer blocks or exhausts the reduction process.

- Expanded default-disabled Fast Mode module-dictionary entry reduction to
  retain unsupported or comment-adjacent entries while probing independently
  source-safe entries from the same dictionary. The stage still excludes
  ambiguous ranges, dynamic values, unpacking, duplicate keys, rebound
  bindings, and semicolon chains. Its initial LOC telemetry now snapshots the
  stage input before accepted edits.

- Promoted the Rich-tested Fast Mode B budget allocation to the default stage
  configuration: direct methods use 265 probes, and the production
  `__main__`-guard and nested Palette-list stages use 8 and 12 probes.
  Complete-symbol, complete-if, container-entry, and list-entry stages now
  default to 60 probes. The global Oracle budget remains explicit and every
  stage can still be disabled with a zero limit.

- Upgraded final reduction reports to schema v2. Unified Fast/Standard reports
  now serialize fixed-point policy and per-sweep telemetry, and stage LOC
  removal is accumulated only from that stage's own sweep-local changes.
  Standard Mode additionally supports `--standard-stage-policy fast-config`
  for controlled comparisons that match Fast Mode's enabled-stage set while
  leaving those stages unbounded.

- Unified target-aware Standard Mode and Fast Mode around one production reducer
  pipeline. Fast Mode retains its shared Oracle/time and per-stage budgets;
  Standard Mode runs the same stages to a reducer-set fixed point without a
  default search cap. Both now use staging 3/3 verification and atomic
  no-clobber publication. The legacy Standard CLI without `--pytest-node`
  retains its existing behavior.

- Corrected final Fast Mode report sizing when a published output directory is
  named `output`; ignored-directory filtering now applies only below the
  reported project root.

- Expanded the GitHub Actions test matrix to cover CPython 3.10, 3.11, and
  3.12.

### Added

- Added three deterministic configured-Oracle benchmark fixtures covering a
  business exit code, a successful command with a stdout validation marker,
  and a successful command with a stderr regular-expression marker. Each has
  a frozen input digest and non-exception 3/3 baseline evidence.

- Added five deterministic, standard-library-only synthetic benchmark fixtures
  for direct-method, complete-if, module-container/list-entry, `__main__`
  guard, and nested `Palette` RGB-list reduction. Each fixture records a
  strict 3/3 baseline and is qualified only when its target production stage
  accepts a verified edit in the retained Fast B/Standard B experiment archive.

- Added default-disabled Fast Mode nested `Palette([...])` RGB-list entry
  reduction through `--max-nested-list-entry-probes`. The stage preserves the
  direct module-level assignment and outer `Palette` call, identifies static
  three-integer tuple entries by source position, probes whole entry batches
  before recursively splitting rejections, and shares the existing
  Oracle/time budget, rollback telemetry, staging 3/3 verification, and
  no-clobber publication.

- Added an optional terminal progress display for `pyrepro reduce`. It is
  interactive-terminal-only by default, reports actual Oracle command starts,
  and supports `--progress auto|on|off` without affecting reduction decisions.

- Added an optional terminal progress display for `pyrepro reduce`. It is
  interactive-terminal-only by default, reports actual Oracle command starts,
  and supports `--progress auto|on|off` without affecting reduction decisions.

- Added default-disabled Fast Mode direct module-level `__main__` guard
  reduction through `--max-main-guard-probes`. The stage recognizes only the
  exact equality guard and its reversed form, runs after module-list reduction,
  and shares the existing Oracle/time budget, rollback telemetry, staging 3/3
  verification, and no-clobber publication.

- Extended default-disabled Fast Mode module-dictionary entry reduction to
  recognize direct integer values for string-keyed dictionaries. Booleans and
  other constant types remain conservatively excluded.

- Added optional final JSON and HTML reduction reports through `--json-report`
  and `--html-report`. Both formats share one truthful result schema covering
  size, Oracle and stage metrics, source integrity, verification, and
  publication status without changing reduction decisions or replacing JSONL
  probe telemetry. The schema now documents the boundary between reduction and
  final-verification Oracle executions.

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
