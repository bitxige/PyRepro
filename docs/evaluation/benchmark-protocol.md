# PyRepro Cross-Repository Benchmark Protocol

## Status and scope

This document fixes the evaluation rules for PyRepro after the P6 Fast Mode
implementation. It defines how repositories, failures, configurations, and
results are selected and reported. Protocol v1 begins with three new real
repositories plus the separately reported archived Tactics2D controlled case.
It does not change a reducer, failure oracle, execution budget, publisher, or
CLI.

The protocol tests this claim rather than assuming it is true:

> For supported trusted Python repositories, static preprocessing and bounded
> group deletion may improve the cost-quality trade-off of execution-verified
> reduction.

The existing Tactics2D result is a retained, controlled single-case result. It
is not evidence that any configuration is faster or better on every Python
repository.

## Research questions

The formal evaluation answers the following questions.

1. Compared with blind greedy reduction, does target-aware import preprocessing
   improve final repository size, Oracle cost, or both?
2. Does bounded coarse file reduction reduce later greedy probes enough to
   justify its own probes?
3. Under a fixed global Oracle budget, can Fast Mode publish a final 3/3
   verified reproducer, and what size-quality trade-off does each budget make?
4. For which supported repository layouts or failure shapes do the approaches
   help, show no benefit, or fail safely?

No aggregate result may claim global minimality, universal speedup, or support
for arbitrary untrusted commands.

## Evaluation unit and repository selection

One evaluation unit is a tuple:

```text
repository identifier + immutable source commit + failure ID + trusted argv
    + environment manifest + configuration ID
```

The initial corpus contains three new real Python repositories and the archived
Tactics2D controlled case. Tactics2D is reported separately from aggregates for
the new real repositories. Each new repository starts with one stable failure;
a second, distinct failure is encouraged during formal evaluation but is not a
pilot entry requirement. Cases must be selected before comparing reduction
outcomes, not after observing which configuration performs well.

### Inclusion criteria

Each selected repository/failure pair must satisfy all of the following:

- a publicly identifiable repository and immutable commit, or an archived
  local fixture with an equivalent immutable source snapshot;
- Python source with a supported flat or `src`-layout package structure;
- a developer-provided argv reproduction command that is safe to repeatedly
  execute in disposable local workspaces and needs no network access or
  dependency installation during reduction;
- a three-run strict baseline with the same exception type, normalized message,
  and repository-relative traceback frame;
- a recorded command timeout that is large enough for the stable baseline but
  bounded enough for a practical experiment;
- an initial repository with at least one eligible Python candidate; and
- a recorded environment manifest sufficient for another developer to attempt
  the run.

The three new repositories should intentionally provide a small package, a
medium project with non-trivial package/import structure, and a more
dependency-heavy or test-complex project. Across the set, prefer variation in
flat and `src` layouts, conventional tests, package re-exports, and both
import-heavy and import-light cases. A repository name, directory name, or
business domain must never affect reducer behavior.

### Exclusions

Record and exclude a candidate from comparative results when its baseline is
unstable, its command requires network setup or installation, the source is
modified during a trial, the failure cannot be represented by the strict oracle,
or the required environment cannot be reproduced. Exclusions are reported with
their reason; they are not silently removed from the corpus.

## Failure provenance and controlled changes

Every case has one of these mutually exclusive provenance labels:

- **historical**: a documented upstream failure, including issue/commit or
  equivalent primary reference and the revision on which it reproduces;
- **controlled**: an intentionally introduced, minimal failure used because a
  stable historical failure is unavailable; or
- **fixture**: a repository-local deterministic project used only for focused
  functional coverage, not as a real-repository performance conclusion.

For a controlled case, archive a machine-applicable patch and describe the
injected behavior, affected files, and why the reproduction command exercises
it. The controlled patch must be applied before the initial source digest is
recorded. It must not be tailored to one reducer configuration.

## Fixed execution conditions

Each project may use its own compatible Python interpreter and fixed dependency
set. Every configuration of the same case must use that exact project-local
environment; the protocol does not force all repositories onto one Python
version. Record a lockfile when available, otherwise a dependency-version
snapshot.

For every configuration of a single case:

1. start from the same immutable source snapshot and controlled patch, if any;
2. use identical argv, working-directory semantics, environment variables,
   Python interpreter, dependency-version snapshot, timeout, strict
   failure-match mode, and candidate exclusion rules;
3. use a fresh disposable workspace and a unique, previously nonexistent output
   directory;
4. establish the same three-run baseline before reduction as required by that
   configuration; and
5. record source digests before and after the trial. A source mismatch
   invalidates that trial and prevents it from being compared with later runs
   from the same snapshot.

The reproduction command is stored as an argv array, not reconstructed from a
shell string. Commands remain trusted-local inputs; this protocol does not turn
PyRepro into a sandbox.

## Configurations

The initial comparison uses the following fixed configuration IDs. Any later
parameter change creates a new configuration ID and must not overwrite results.

| ID | Pipeline | Purpose |
| --- | --- | --- |
| A | Blind Greedy | File-level baseline without import preprocessing or coarse groups. |
| B | Import + Greedy | Measures target-aware import preprocessing before existing greedy cleanup. |
| C | Import + Coarse + Greedy | Measures the additional bounded coarse stage before greedy cleanup. |
| F6 | Fast Mode, 6 executions | Validates baseline/final reservation and verified publication with zero search probes. |
| F30 | Fast Mode, 30 executions | Low-budget quality and publication behavior. |
| F60 | Fast Mode, 60 executions | Medium-budget quality and publication behavior. |
| F100 | Fast Mode, 100 executions | Higher-budget quality and publication behavior. |

For A/B/C, use the fixed three-strategy benchmark driver and record its exact
arguments. A uses blind greedy; B uses import pruning plus greedy; C uses the
same import settings plus coarse reduction with `max_coarse_probes=16`. All use
the same normal reducer timeout and strict matching.

For F6/F30/F60/F100, use `pyrepro reduce --mode fast` with the same explicit
pytest node, command, timeout, match mode, `max_import_probes=16`, and
`max_coarse_probes=16`, changing only `max_oracle_executions`. Fast Mode uses
the published output only when its final staging verification succeeds. F6 is
a delivery-semantics check, not an additional-minimization benchmark.

Do not add ddmin, symbol reduction, dependency-aware ordering, or repository
specific options to one comparison arm unless all arms are redefined and the
protocol version is incremented.

## Measurements and accounting

All reports must preserve raw counts in addition to derived percentages.

### Size and correctness

- **initial/final Python files**: eligible Python files under the reducer's
  existing candidate rules, measured from the original snapshot and final
  accepted/published workspace respectively;
- **initial/final Python LOC**: physical Python LOC using the same scanner for
  both values;
- **LOC reduction ratio**: `(initial_loc - final_loc) / initial_loc`; and
- **strict verification**: each final verification run must be classified as
  `SAME_FAILURE` against the baseline signature.

For A/B/C, also run and record three independent final checks using the fixed
benchmark driver. For Fast Mode, the Publisher's staging final 3/3 is the
official verification; any optional post-publication check is reported
separately and does not change the configured budget result.

### Oracle executions

An Oracle execution is one reproduction command that actually starts. A command
that times out or exits abnormally still counts. Candidate generation, static
analysis, copying, and queue maintenance do not count as Oracle executions.

For A/B/C report separately:

- reducer-internal executions, broken down by phase;
- independent final verification executions; and
- their sum as total Oracle executions.

For Fast Mode report:

- baseline executions;
- import, coarse, and greedy probe executions;
- Publisher final-verification executions;
- total executions started from the shared `ExecutionBudget`; and
- configured execution limit and remaining budget snapshot.

Do not add the Fast Mode final 3/3 a second time. A comparison table must state
whether it reports reducer-only executions or complete trial executions; the
default primary metric is complete trial executions.

### Time

Record both per-phase Oracle duration from telemetry and complete wall-clock
duration. Complete wall-clock starts before source-integrity and initial
eligible-file scans and ends after final independent verification or final
publication outcome. It includes static analysis, workspace copying, staging,
and output handling. It does not include manual environment creation or result
analysis performed after the process exits.

## Trial outcomes and reporting

Every attempted configuration is reported with exactly one outcome:

| Outcome | Meaning | Comparable as successful reduction? |
| --- | --- | --- |
| `verified_published` | Fast Mode published after staging final 3/3. | Yes |
| `verified_unpublished` | Non-Fast configuration passed its independent final 3/3. | Yes |
| `budget_exhausted_unverified` | Budget/deadline prevented final verification or publication. | No |
| `final_verification_failed` | Final run produced a different result. | No |
| `baseline_failed` | Initial baseline was absent or unstable. | No |
| `source_changed` | Protected source digest differed from the fixed snapshot. | No |
| `runtime_error` | Operational error prevented a complete trial. | No |
| `skipped` | Trial was intentionally not started, with recorded reason. | No |

Unsuccessful runs retain their partial telemetry, elapsed time, raw output, and
reason. They must never be converted to zero LOC, zero executions, or a
successful reduction in aggregate tables.

## Repetition, order, and caching

Use one recorded pilot run on the first selected new repository to validate
command, reporting, environment capture, and asset capture. It is not used for
performance claims. Once the pilot is complete, run each primary A/B/C
configuration at least three times when practical. For key Fast budgets, run at
least three repetitions; if resource limits prevent this, report the single-run
limitation explicitly.

Randomize or rotate configuration order within each repetition. Record the
order, host load notes, and whether a warm-up run occurred. Do not clear shared
system caches by unsupported or privileged means. Instead, report wall-clock
median, minimum, maximum, and all raw observations; treat small differences as
inconclusive when variation overlaps.

## Asset archive

Store results outside both the source project and the PyRepro Git repository.
The default local root is `~/my_project/pyrepro-bench-results/`, with one
top-level manifest:

```text
pyrepro-bench-results/
  benchmark-protocol.md
  manifest.json
  <case-id>/<configuration-id>/<run-id>/
    metadata.json
    result.json
    stdout.log
    stderr.log
    probe-records.jsonl          # when enabled
    source.patch                 # controlled cases only
    adapter.py                   # if a local adapter is used
    environment.txt
    reproduce.argv.json
```

`metadata.json` records the repository URL/identifier, source commit, dirty
state, controlled-patch digest, PyRepro commit and dirty state, Python version,
platform, command timeout, argv, pytest node, matching mode, configuration
parameters, timestamps, and source digests. `manifest.json` indexes every case
and trial and records hashes for retained assets. Do not archive credentials,
private environment values, virtual environments, or an entire third-party
repository unless redistribution is explicitly permitted.

Aggregate metrics, charts, configuration metadata, repository URLs, commits,
and license information may be prepared for publication. Full third-party
repository copies, raw logs, reduced projects, patches, and adapters remain
local by default; review upstream licenses and remove sensitive paths or tokens
before publishing any of them.

## Execution sequence

Run the evaluation in bounded batches:

1. register candidate cases and validate their three-run strict baselines;
2. run one pilot configuration per case and inspect JSON/log completeness;
3. complete A/B/C repetitions for cases with valid pilots;
4. run Fast Mode budgets from F6 upward, stopping a case after a documented
   source-integrity or reproducibility failure;
5. perform independent result review before producing aggregate tables; and
6. publish both successful and excluded/failed case summaries.

Do not start all expensive repositories concurrently. Start with one complete
case, validate its artifacts, then add the next case. This keeps cost bounded
and catches protocol mistakes before they affect the corpus.

## Reporting template

The final report includes a per-case table with source size, final size,
complete Oracle executions, wall-clock statistics, final verification result,
publication result, and failure provenance. It also includes:

- aggregate medians only for clearly comparable successful trials;
- raw per-run values or a link to their archived JSON;
- a separate table for exclusions and unsuccessful runs;
- representative import-heavy, import-light, and non-beneficial cases; and
- a limitations section covering trusted execution, Python feature coverage,
  static-analysis conservatism, environment sensitivity, and non-global
  minimality.

## Protocol v1 decisions

- Start with three new real repositories plus the separately reported archived
  Tactics2D controlled case. Expand only after these four cases have complete,
  audited artifacts.
- Require one stable fault per new repository for the pilot. Seek a second
  distinct fault per repository during formal evaluation; distinguish historical
  and controlled faults in all tables.
- Lock Python and dependencies per project, not globally across projects. No
  reduction trial may install dependencies or change its recorded environment.
- Archive results outside PyRepro with a manifest and file hashes. Publish only
  metrics and metadata by default; release logs, patches, adapters, reduced
  projects, or third-party code only after sensitivity and license review.
