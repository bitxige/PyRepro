# Configured Oracle Benchmark Results

Run date: 2026-11-12. All cases used their manifest-frozen input digest, the
trusted in-project adapter, a 15-second per-command timeout, and the Oracle
configuration stated below. Fast B used the production default stage limits
with a 630-execution ceiling. Standard used `--standard-stage-policy
fast-config`, preserving the same enabled stages without a search ceiling.

All six runs reached the active reducer-set fixed point, retained an unchanged
input tree, and passed independent final 3/3 verification. The generated
outputs, JSON reports, HTML reports, and JSONL probes are archived under
`pyrepro-bench-results/oracle-v1_1-custom-benchmarks-20261112/` outside this
repository.

| Case | Oracle | Fast B LOC | Standard LOC | Fast / Standard total Oracle | Fast / Standard sweeps |
| --- | --- | ---: | ---: | ---: | ---: |
| `case_exit_code` | exit code `42` | 51 → 38 | 51 → 38 | 34 / 34 | 2 / 2 |
| `case_stdout_literal` | stdout literal `VALIDATION_FAILED` | 50 → 39 | 50 → 39 | 33 / 33 | 2 / 2 |
| `case_stderr_regex` | stderr regex `ERROR[PAYLOAD-n]` | 49 → 38 | 49 → 38 | 33 / 33 | 2 / 2 |

The fixtures are intentionally small and deterministic. They validate the
configured Oracle feature end to end; they are not performance claims for
arbitrary repositories. Equal Fast and Standard results are expected because
each fixture reaches a fixed point well below Fast B's global budget.
