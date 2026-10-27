# Result report schema

`pyrepro reduce --json-report PATH` writes a versioned JSON summary of one
completed reduction attempt. The JSON document is the canonical report data;
the optional HTML report is a presentation of the same mapping.

This document describes schema version 1. An unavailable value is represented
as `null`; a missing optional stage is not invented by the reporter.

## Top-level fields

| Field | Meaning |
| --- | --- |
| `schema_version` | Integer report schema version. Current value: `1`. |
| `mode` | Reduction mode: `standard` or `fast`. |
| `strategy` | Requested file-reduction strategy. |
| `size` | Input, accepted-candidate, and—when published—output size facts. |
| `oracle` | Command-execution accounting. |
| `timing` | Reduction-only and end-to-end elapsed seconds when available. |
| `stages` | Per-stage metrics in pipeline order. |
| `final_verification` | Final output verification evidence. |
| `status` | Terminal publication and source-integrity state. |

## Size accounting

`size.input`, `size.candidate`, and `size.published_output` contain
`python_files` and `python_loc`. `published_output` is `null` for an
unpublished Fast Mode outcome. `loc_removed` is the input LOC minus accepted
candidate LOC. `loc_reduction_ratio` is `loc_removed / input.python_loc`, or
`null` when the input LOC is zero.

Stage `loc_removed` is measured at that stage's boundary using eligible Python
source lines. Stage metrics describe their own reducer operation; consumers
must not assume that counts such as `candidate_attempts` and `accepted` share a
common denominator across different reducer types.

## Oracle accounting

`oracle.total_executions` counts every Oracle command started during the report
scope. It is split into:

- `reduction_executions`: commands started while reducers establish and search
  the accepted candidate; and
- `final_verification_executions`: commands started after reduction to verify
  the final copied or staged result.

For a successful Standard Mode run, the copied-output verification contributes
one final-verification execution. Fast Mode obtains this value from the shared
execution budget after Publisher reaches its terminal state. The sum of the two
split fields equals `total_executions` whenever both fields are available.

`final_verification.oracle_executions` repeats the latter number beside the
verification evidence; it does not represent an additional command count.

## Verification and status

`final_verification.required_runs`, `completed_runs`, and
`same_failure_runs` record actual final checks. Standard Mode's verified copy
uses one run. Fast Mode records Publisher's independent staging checks and
does not report a publication as verified unless that contract succeeds.

`status.published` is true only when an official output path exists. An
unpublished Fast Mode terminal state remains visible in `status.terminal_state`
and must not be treated as a successful publication merely because an accepted
workspace candidate exists.
