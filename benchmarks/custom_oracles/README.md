# Configured Oracle Benchmarks

These deterministic, standard-library-only fixtures exercise the configured
failure-oracle capabilities introduced in Oracle V1.1. They are separate from
the stage-oriented synthetic fixtures because their primary purpose is to
verify user-selected runtime behavior rather than one reducer's AST domain.

| Case | Oracle | Target behavior |
| --- | --- | --- |
| `case_exit_code` | `exit-code` | The validated payload returns exit code `42`. |
| `case_stdout_literal` | `output` / stdout / literal | A checksum mismatch prints `VALIDATION_FAILED`. |
| `case_stderr_regex` | `output` / stderr / regex | An invalid record emits an `ERROR[PAYLOAD-n]` marker. |

Every case has a frozen input tree, an adapter, a manifest, and 3/3 baseline
evidence. The adapters deliberately return normally or exit through a
business-result code: none relies on a Python exception as its target signal.

## Reproduction protocol

Use a fresh output directory for every trial. The `--pytest-node` argument
continues to scope static candidate analysis; the trusted adapter command and
the configured Oracle decide whether a candidate is accepted.

```bash
python -m pyrepro reduce benchmarks/custom_oracles/case_exit_code/input \
  --mode fast \
  --pytest-node benchmarks/regression_test.py::test_exit_code_failure \
  --oracle exit-code --expected-exit-code 42 \
  --max-oracle-executions 630 --timeout-seconds 15 \
  --output /new/exit-output -- python benchmarks/adapter.py

python -m pyrepro reduce benchmarks/custom_oracles/case_stdout_literal/input \
  --mode standard --standard-stage-policy fast-config \
  --pytest-node benchmarks/regression_test.py::test_stdout_failure \
  --oracle output --output-stream stdout --output-match literal \
  --output-pattern VALIDATION_FAILED --timeout-seconds 15 \
  --output /new/stdout-output -- python benchmarks/adapter.py

python -m pyrepro reduce benchmarks/custom_oracles/case_stderr_regex/input \
  --mode standard --standard-stage-policy fast-config \
  --pytest-node benchmarks/regression_test.py::test_stderr_failure \
  --oracle output --output-stream stderr --output-match regex \
  --output-pattern 'ERROR\\[PAYLOAD-\\d+\\]' --timeout-seconds 15 \
  --output /new/stderr-output -- python benchmarks/adapter.py
```

The benchmark projects are fixtures, not historical defects or general
performance claims. Complete Fast B and Standard B artifacts belong in the
external experiment archive, not in this repository.

The recorded six-run acceptance summary is in [RESULTS.md](RESULTS.md).
