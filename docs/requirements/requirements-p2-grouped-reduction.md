# P2 grouped and delta-debugging reduction requirements

## Objective

Add an execution-verified grouped file-reduction strategy while retaining P1's
single-file greedy reducer as the baseline. P2 investigates the trade-off
between reduction quality and expensive reproduction-command executions; it
does not assume that delta debugging is always faster.

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

P2 retains `GreedyFileReducer` unchanged as a baseline and adds a concrete
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

`DdminFileReducer` begins with all candidates retained. It partitions the
current retained set into non-empty groups, probes groups and their
complements, and adjusts granularity using the standard ddmin progression.
Each probe must be semantically equivalent to starting from a clean source
copy; no accepted or rejected deletion from a previous probe may contaminate a
later probe.

The final retained set must be **1-minimal with respect to candidate files**:
removing any one remaining candidate must fail to preserve the baseline. P2
must not call this globally minimal, because different multi-file combinations
may still exist.

## Metrics

Both strategies must expose the same measurements. Never estimate an
unavailable metric.

| Metric | Definition |
| --- | --- |
| strategy | `greedy` or `ddmin` |
| candidate Python files | P1-eligible files before and after reduction |
| candidate Python LOC | Physical lines in eligible Python files before and after reduction |
| oracle executions | All reproduction-command executions, including baseline and final verification |
| candidate attempts | Probe executions after baseline and before final verification |
| accepted deletions | Candidate files absent from the final verified workspace |
| rejected probes | Candidate probes that did not yield `SAME_FAILURE` |
| reduction wall-clock seconds | `perf_counter` duration from first baseline execution through final verification |
| failure preserved | Final exact-signature verification result |
| source unchanged | Source-tree digest result |

`oracle executions` is the primary cost metric because a real reproduction
command can dominate all local file-operation costs.

## Grouped-failure benchmark design

P2 implementation will add `examples/grouped_failure`; this design PR does
not create an empty placeholder fixture.

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
not depend on undeclared third-party packages.

This benchmark tests more than execution count: greedy reduction should retain
the coupled pair, while a valid grouped/ddmin reduction can remove both.

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

## Completion criteria for the later implementation PR

1. Existing greedy behavior and P1 tests remain intact.
2. `--strategy greedy` and `--strategy ddmin` share the same failure oracle
   and candidate exclusions.
3. The grouped fixture demonstrates the coupled-pair behavior defined above.
4. ddmin removes the coupled pair while preserving the exact failure.
5. Both strategy outputs are independently verified and leave sources
   unchanged.
6. Metrics include every field defined above and use actual measurements.
7. Tests cover partitioning, subset/complement acceptance, 1-minimal final
   verification, deterministic metrics, and source safety.

## Explicitly out of scope

- AST/symbol-level reduction;
- Scanner/AST-guided ordering or import-graph analysis;
- custom behavior oracles;
- dependency, configuration, data, or environment reduction;
- execution sandboxing;
- LLM, agent, MCP, UI, or automatic patch features; and
- a claim of global minimum reduction.
