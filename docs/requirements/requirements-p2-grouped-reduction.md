# P2 grouped and delta-debugging reduction requirements

## Objective

P2 adds an execution-verified grouped file-reduction strategy while retaining P1's
single-file greedy reducer as the baseline. P2 investigates the trade-off
between reduction quality and expensive reproduction-command executions; it
does not assume that delta debugging is always faster or globally minimal.

## Scope

P2 remains file-level reduction. It reuses P1's:

- trusted-local argv command boundary;
- three-run stable Python failure signature;
- optional `--expect` baseline anchor;
- disposable workspace and source-integrity check; and
- default candidate-directory exclusions.

No P2 acceptance decision may rely on a static signal. A candidate deletion is
accepted only when executing the command produces the exact P1 baseline
signature.

## Strategy contract

P2 retains `GreedyFileReducer` as a baseline and adds a concrete
`DdminFileReducer`. Do not introduce an abstract reducer hierarchy unless a
real second shared behavior requires it.

The CLI will support:

```bash
pyrepro reduce <source> --strategy greedy -- <argv...>
pyrepro reduce <source> --strategy ddmin -- <argv...>
```

`greedy` remains the default during P2 so existing P1 commands keep their
behavior.

### ddmin configuration

Let `C` be the P1-eligible candidate Python files. A ddmin probe selects a
subset `S` of `C` to retain; every file in `C - S` is removed from a fresh
candidate workspace. Files excluded by P1 directory rules remain present in
every probe.

The interestingness predicate is:

```text
F(S) = running the command with retained candidates S yields SAME_FAILURE
```

`DdminFileReducer` is a ddmin-inspired grouped reducer. It begins with all
candidates retained, partitions the current retained set into non-empty groups,
probes groups and their complements, and adjusts granularity using a
deterministic ddmin-style progression. Each probe must be semantically
equivalent to starting from a clean source copy; no accepted or rejected
deletion from a previous probe may contaminate a later probe.

The reducer then performs a single-file greedy cleanup over the retained set,
followed by an explicit 1-minimal verification pass. The final retained set is
**1-minimal with respect to candidate files** only when removing each remaining
candidate independently fails to preserve the baseline. P2 must not call this
globally minimal, because a different multi-file combination may still be
removable.

The grouped search is responsible for discovering opportunities such as a
coupled subsystem that can be removed only as a group. The final greedy cleanup
and verification establish the separate 1-minimality property. Do not claim
that textbook ddmin alone guarantees removal of every removable coupled pair.

## Metrics

Both strategies must expose the same measurements. Never estimate an
unavailable metric.

| Metric | Definition |
| --- | --- |
| strategy | `greedy` or `ddmin` |
| candidate Python files | P1-eligible files before and after reduction |
| candidate Python LOC | Physical lines in eligible Python files before and after reduction |
| oracle executions | All reproduction-command executions, including baseline, grouped search, greedy cleanup, 1-minimal verification, and final verification |
| candidate attempts | All grouped, complement, cleanup, and 1-minimality probe executions; excludes baseline and final full-workspace verification |
| accepted probes | Candidate probes yielding `SAME_FAILURE` that cause a grouped or single-file removal decision |
| removed candidate files | Candidate files absent from the final verified workspace |
| rejected probes | Candidate probes that did not yield `SAME_FAILURE` |
| reduction wall-clock seconds | `perf_counter` duration from first baseline execution through final verification, including every minimality probe |
| failure preserved | Final exact-signature verification result |
| source unchanged | Source-tree digest result |

`oracle executions` is the primary cost metric because a real reproduction
command can dominate all local file-operation costs.

## Grouped-failure benchmark design

P2 adds `examples/grouped_failure` with no empty placeholder fixtures.

The completed fixture must contain 30 to 50 eligible Python files:

- a five-file failure chain with a deterministic uncaught Python exception;
- at least 25 independent ballast modules; and
- a coupled two-file optional subsystem that is irrelevant to the final
  failure but cannot be removed one file at a time.

The coupled subsystem must have these observable properties:

```text
remove optional_a.py only  -> DIFFERENT_FAILURE
remove optional_b.py only  -> DIFFERENT_FAILURE
remove both together        -> SAME_FAILURE
```

For example, a loader may require an optional pair to be either fully present
or fully absent before the independent failure chain executes. The fixture must
not depend on undeclared third-party packages. Its deterministic candidate path
order and partitioning scenario must expose a probe that removes the coupled
subsystem together.

This benchmark tests more than execution count: greedy reduction should retain
the coupled pair, while the documented grouped search scenario must remove both
before final 1-minimal verification.

## Evaluation protocol

Compare `greedy` and `ddmin` using the same:

- source fixture and source copy;
- argv command, timeout, `--expect`, baseline-run count, and exclusions; and
- final exact failure-signature verification.

During development, one smoke run per strategy is sufficient. For the formal
benchmark, run each strategy three times and report median, minimum, and
maximum wall-clock duration plus median oracle executions. The fixture is
deterministic, but repeated runs distinguish algorithmic behavior from host
timing variation.

Do not claim ddmin is categorically faster. Report the measured trade-off:
reduction quality, retained files/LOC, oracle executions, and wall-clock time.

## P2 completion criteria

1. Existing greedy behavior and P1 tests remain intact.
2. `--strategy greedy` and `--strategy ddmin` share the same failure oracle
   and candidate exclusions.
3. The grouped fixture demonstrates the coupled-pair behavior defined above.
4. The deterministic grouped-search scenario removes the coupled pair while
   preserving the exact failure.
5. Both strategy outputs are independently verified and leave sources
   unchanged.
6. Metrics include every field defined above and use actual measurements.
7. Final 1-minimal verification probes every retained candidate and counts all
   of those probes toward oracle executions, candidate attempts, and
   wall-clock time.
8. Tests cover partitioning, subset/complement acceptance, greedy cleanup,
   1-minimal verification, deterministic metrics, and source safety.

## Explicitly out of scope

- AST/symbol-level reduction;
- Scanner/AST-guided ordering or import-graph analysis;
- custom behavior oracles;
- dependency, configuration, data, or environment reduction;
- execution sandboxing;
- LLM, agent, MCP, UI, or automatic patch features; and
- a claim of global minimum reduction.
