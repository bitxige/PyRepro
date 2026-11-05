# Automated Regression Validation — 2026-11-05

## Scope and target

- Validation target: `a167169`
  (`feat: unify bounded and exhaustive reduction pipelines`).
- Branch: `feature/fast-budget-b-default`.
- Scope: shared Fast/Standard production pipeline, Fast B default allocation,
  shared execution budget, fixed-point control, staging publication, report
  schema v2, CLI compatibility, the merged runner governance changes from
  PR #48 and PR #49, and core reducer regression coverage.

## Automated checks

| Check | Result |
| --- | --- |
| Test collection | 228 tests collected |
| Full unit and integration suite | 228 passed |
| `ruff check .` | passed |
| `ruff format --check .` | passed; 120 files already formatted |
| `git diff --check` | passed |

The suite covers the core file/symbol reducers, import and coarse stages,
methods, statements, container/list entries, Fast and Standard pipeline
behavior, execution-budget accounting, failure-oracle matching, CLI behavior,
source integrity, staging publication, and final verification.

## Regression evidence

- Fast B stage defaults and global-budget compatibility are covered by CLI and
  pipeline tests.
- Standard Mode is covered for unbounded execution, repeated pipeline sweeps,
  fixed-point termination, and final strict verification.
- Publisher tests cover staging, strict 3/3 verification, atomic no-clobber
  publication, and protected-source behavior.
- A new coarse-reduction regression test covers rejected groups containing
  files under sibling directories. This fixes the Tactics2D Standard failure
  where an arbitrary sibling parent was incorrectly treated as the shared
  ancestor during split generation.
- Post-rebase runner/CLI coverage passes all 58 tests, including descendant
  process termination on timeout, non-blocking stdin, bounded output capture,
  and non-UTF-8 output handling. The remaining 170 tests also pass.

## CI status

`.github/workflows/ci.yml` runs the same Ruff and pytest quality gates on
CPython 3.10, 3.11, and 3.12. Remote CI has not yet been triggered for this
branch; it should be checked after the branch is pushed.

## Release decision

No known P0 or P1 issue remains in the validated scope. The automated testing
and regression-acceptance work package is complete for commit `a167169`.
Any later issue discovered by a new real-project case should be handled as a
separate bug fix with targeted regression coverage.
