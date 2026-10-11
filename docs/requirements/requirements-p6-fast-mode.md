# P6 Fast Mode requirements

## Status

P6 is implemented in small, separately reviewable changes. P6a defines the
execution-budget contract only; it does not change a reducer's candidate
ordering or acceptance rule. P6b makes existing reduction probes transactional
at a shared budget boundary. P6c provides staging verification and verified
publication. P6d exposes the existing composition through `pyrepro reduce
--mode fast` without duplicating reducer, budget, source-integrity, or
publication decisions in the CLI.

## Objective

Fast Mode lets a trusted user bound the cost of a reduction while preserving
the existing execution-verified failure contract. It may stop searching early,
but it must never publish a result as verified unless an independent final
three-run verification succeeds.

```text
stable baseline -> bounded reduction probes -> staging verification -> publish
       3 runs             shared global budget             3 runs
```

Static analysis continues to guide candidate generation. The established
runtime failure oracle remains the only authority that accepts a change.

## Budget contract

Fast Mode uses one `ExecutionBudget` for the entire pipeline. It is created
once per run and is the only permitted Fast-Mode entry point for starting an
Oracle command.

- `max_oracle_executions` counts every command actually started, including a
  command that later times out or exits with an error.
- Three execution slots are reserved for final independent verification.
  Ordinary candidate probes cannot consume those slots.
- Six executions is the theoretical minimum: three stable baseline executions
  and three final independent verification executions. It permits no ordinary
  probe.
- Fast Mode must not run the normal Import or Greedy stage-final verification
  calls. They are redundant with the final three-run staging verification.
  Direct reducer APIs retain their existing stage-final behavior.
- A time budget uses a monotonic deadline. Before each command starts, its
  effective timeout is the smaller of the runner timeout and remaining global
  time. No command starts once the deadline has passed.
- Execution-count limits are strict. A time limit is best-effort for final
  verification: if the remaining deadline cannot complete all three final
  executions, the outcome is unverified and no official output is published.

## Transaction and publication contract

Every candidate probe is transactional in the disposable workspace. Before a
probe mutation, Fast Mode checks its budget. If a budget stop or other runner
exception occurs after a temporary mutation, the unaccepted mutation is
restored. Earlier accepted mutations remain available as the current best
candidate.

The current best candidate is copied to a sibling staging directory. PyRepro
runs the independent final verification there three times. Only after all
three results match is the staging directory atomically published at the user
requested output path. An unverified staging directory is never presented as a
verified reproducer.

## Terminal states

| State | Meaning | Official output |
| --- | --- | --- |
| `completed` | Search completed and final verification passed 3/3. | Published |
| `budget_exhausted_verified` | Search stopped for budget, then final verification passed 3/3. | Published |
| `budget_exhausted_unverified` | Budget/deadline stopped work before final 3/3 completed. | Not published |
| `final_verification_failed` | Final verification completed with a different result. | Not published |
| `baseline_failed` | Initial baseline was absent or unstable. | Not published |
| `source_changed` | The protected source digest changed. | Not published |
| `runtime_error` | A non-budget operational error interrupted the run. | Not published |

Source integrity failure takes precedence over ordinary reducer failure.

## P6a scope

P6a adds the reusable execution-budget contract, monotonic-time accounting,
effective per-command timeout support, and focused tests. It does not integrate
the budget into Import, Coarse, Greedy, CLI, staging, or publication.

## Later P6 slices

- P6b: make Import, Coarse, and Greedy cooperative and transactional at a
  Fast-Mode budget boundary. Each stage shares the same budget, does not repeat
  a baseline, and stops before a new probe when only final slots remain. A
  budgeted composition skips its normal stage-final checks; direct reducer use
  retains them. A stopped stage may retain only edits or deletions already
  accepted by its strict probe Oracle. This establishes a safe workspace, not
  a publishable reproducer.
- P6c: `verify_and_publish` copies the accepted workspace to a sibling staging
  directory, runs three independent budgeted checks there, and atomically
  renames it into a new output directory only when all checks preserve the
  baseline and the source digest remains unchanged. On Linux, publication uses
  `renameat2(RENAME_NOREPLACE)` so a concurrently created destination is never
  replaced. Platforms or filesystems without that no-clobber guarantee fail
  with `runtime_error`; they do not fall back to ordinary `rename`. It returns
  a structured terminal result and removes every unpublished staging directory.
  It does not add a CLI entry point.
- P6d: explicit CLI integration, reporting, and end-to-end tests.

## CLI contract

Fast Mode is opt-in through the existing `reduce` command. It requires an
explicit pytest node and a global Oracle-command budget:

```text
pyrepro reduce SOURCE --mode fast --pytest-node FILE::[CLASS::]TEST
    --max-oracle-executions N [--max-time-seconds SECONDS] -- ARGV...
```

The CLI is an orchestration and display layer only. It creates the shared
budget, invokes the existing preprocessing-first reducer, then passes the
accepted workspace to `verify_and_publish`. In particular, output no-clobber
and source-integrity safety remain publisher responsibilities.

`completed` and `budget_exhausted_verified` exit successfully only after an
official output was published. The latter message must explicitly state that
search stopped for the budget but the candidate passed final independent 3/3
verification. All unpublished terminal states exit nonzero and state that no
official reproducer was created. Fast Mode rejects incompatible `ddmin` and
symbol-reduction arguments rather than silently ignoring them.

## Non-goals

P6 adds no reduction strategy, candidate ranking, custom Oracle, dependency
algorithm, dependency installation, or repository-specific rule. It continues
to run only developer-selected trusted local commands with `shell=False`.
