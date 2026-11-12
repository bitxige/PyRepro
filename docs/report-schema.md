# Result report schema

`pyrepro reduce --json-report PATH` writes a versioned JSON summary of one
completed reduction attempt. The JSON document is the canonical report data;
the optional HTML report is a presentation of the same mapping.

This document describes schema version 4. An unavailable value is represented
as `null`; a missing optional stage is not invented by the reporter.

## Top-level fields

| Field | Meaning |
| --- | --- |
| `schema_version` | Integer report schema version. Current value: `4`. |
| `mode` | Reduction mode: `standard` or `fast`. |
| `strategy` | Requested file-reduction strategy. |
| `command` | Original argv reproduction command, or `null` when not supplied. |
| `size` | Input, accepted-candidate, and—when published—output size facts. |
| `oracle` | Command-execution accounting. |
| `timing` | Reduction-only and end-to-end elapsed seconds when available. |
| `pipeline` | Fixed-point policy, enabled stages, and termination facts for unified runs. |
| `stages` | Per-stage metrics in pipeline order. |
| `sweeps` | Per-sweep telemetry for unified Fast/Standard pipeline runs. |
| `final_verification` | Final output verification evidence. |
| `status` | Terminal publication and source-integrity state. |

## Size accounting

`size.input`, `size.candidate`, and `size.published_output` contain
`python_files` and `python_loc`. `published_output` is `null` for an
unpublished Fast Mode outcome. `loc_removed` is the input LOC minus accepted
candidate LOC. `loc_reduction_ratio` is `loc_removed / input.python_loc`, or
`null` when the input LOC is zero.

For a single sweep, stage `loc_removed` is measured at that stage's boundary
using eligible Python source lines. For a unified multi-sweep report, each
top-level stage `loc_removed` is the sum of that stage's own per-sweep changes;
it never includes edits accepted by other stages. Aggregated stage rows expose
`first_initial_python_loc` and `last_remaining_python_loc` as descriptive
endpoints only, not as operands for recomputing stage removal. Stage metrics
describe their own reducer operation; consumers must not assume that counts
such as `candidate_attempts` and `accepted` share a common denominator across
different reducer types.

## Fixed-point pipeline evidence

Unified Fast and target-aware Standard reports include `pipeline` and
`sweeps`. `pipeline.sweep_count`, `fixed_point_reached`, and
`termination_reason` (`fixed_point`, `budget_exhausted`, or `incomplete`) state
how search ended. `pipeline.stage_limits` records each production stage's
enabled state and configured probe limit (`null` means unbounded).

Every `sweeps` item contains input/output Python LOC, accepted edit count,
baseline/search/total Oracle executions, elapsed time, budget-stop state, and
the unaggregated stage rows for that sweep. Consumers should use this array,
not JSONL reconstruction, to inspect a fixed-point run.

## Oracle accounting

`oracle.type` identifies the configured failure Oracle and `oracle.config`
contains its bounded public configuration. `oracle.decisions` aggregates
`match`, `no_match`, and `inconclusive` decisions. Baseline runs count as
`match` only after the Oracle has accepted all baseline evidence. Probe JSONL
records contain the corresponding Oracle type, decision, short reason, and
bounded evidence; complete command output is never serialized.

`oracle.total_executions` counts every Oracle command started during the report
scope. It is split into:

- `baseline_executions`: commands that establish the stable failure signature;
- `search_executions`: candidate-probe commands after the baseline;
- `reduction_executions`: commands started while reducers establish and search
  the accepted candidate (`baseline_executions + search_executions`); and
- `final_verification_executions`: commands started after reduction to verify
  the final copied or staged result.

For successful target-aware Standard and Fast Mode runs, the shared Publisher
performs three final-verification executions on a sibling staging copy. Fast
Mode obtains this value from the shared execution budget after Publisher reaches
its terminal state; Standard Mode has no budget object. The sum of the two split
fields equals `total_executions` whenever both fields are available.

`final_verification.oracle_executions` repeats the latter number beside the
verification evidence; it does not represent an additional command count.

## Verification and status

`final_verification.required_runs`, `completed_runs`, and
`same_failure_runs` record actual final checks. Target-aware Standard and Fast
Mode record Publisher's independent staging checks and do not report a
publication as verified unless all three succeed. Legacy Standard reports retain
their historic single-copy verification semantics for CLI compatibility.

`status.published` is true only when an official output path exists. An
unpublished Fast Mode terminal state remains visible in `status.terminal_state`
and must not be treated as a successful publication merely because an accepted
workspace candidate exists.
