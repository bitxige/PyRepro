# Synthetic Controlled Benchmark Results

Run date: 2026-11-07. All trials used the frozen input digests in the case
manifests, a 15-second per-command timeout, strict failure matching, and the
same trusted adapter for Fast B and Standard B. Every published output passed
the staging final verification 3/3; every input digest remained unchanged.

Fast B used its production defaults with `--max-oracle-executions 630`.
Standard B used `--standard-stage-policy fast-config`, retaining the same
enabled stages while removing search limits. Complete generated artifacts are
in `pyrepro-bench-results/synthetic-controlled-benchmarks-20261107-r2/`.

| Case | Primary accepted stage | Fast B LOC | Standard B LOC | Fast total Oracle | Standard total Oracle | Sweeps |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| `case_method` | Method: 3 edits | 45 → 36 | 45 → 36 | 33 | 33 | 2 |
| `case_if` | If: 2 edits | 36 → 32 | 36 → 32 | 32 | 32 | 2 |
| `case_container` | Container: 3; List: 3 | 48 → 40 | 48 → 40 | 46 | 46 | 2 |
| `case_main_guard` | MainGuard: 1 edit | 39 → 34 | 39 → 34 | 31 | 31 | 2 |
| `case_nested_list` | Nested Palette: 2 probes / 3 entries | 54 → 51 | 54 → 51 | 44 | 44 | 2 |

All five are **fixture** provenance: they verify targeted stage behavior, not
historical-bug realism or general repository performance. The identical Fast B
and Standard B results are expected for these small deterministic inputs; the
separate Rich, Tactics2D, and historical-bug experiments evaluate the
cost-quality difference at larger scale.
