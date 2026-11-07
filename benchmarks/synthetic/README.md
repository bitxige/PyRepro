# Synthetic Controlled Benchmarks

This directory contains deterministic, local fixtures for exercising one
production reduction stage at a time. They complement, rather than replace,
the historical-bug and large-project evaluations.

Each case has a frozen `input/` project, a strict adapter, an environment
record, and a manifest. The required acceptance evidence is recorded only
after independent Fast B and Standard B trials both preserve the same failure
three times. A case is qualified only if its named stage accepts at least one
source edit.

| Case | Primary stage | Failure signature |
| --- | --- | --- |
| `case_method` | direct method | `method fixture failure` |
| `case_if` | complete if statement | `if fixture failure` |
| `case_container` | dictionary and list entries | `container fixture failure` |
| `case_main_guard` | `__main__` guard | `main guard fixture failure` |
| `case_nested_list` | nested `Palette` RGB entry | `nested palette fixture failure` |

These projects are deliberately small and use only the Python standard
library. Their results must not be presented as historical defects or as a
performance claim for arbitrary repositories.

## Reproduction protocol

Use a fresh output directory for each trial. Fast B uses the production Fast
defaults and an explicit shared 630-execution limit. Standard B uses the same
enabled-stage set through `fast-config`, but has no search budget:

```bash
python -m pyrepro reduce benchmarks/synthetic/case_method/input \
  --mode fast \
  --pytest-node benchmarks/regression_test.py::test_method_failure \
  --timeout-seconds 15 --failure-match strict \
  --expect "method fixture failure" --max-oracle-executions 630 \
  --output /new/fast-output --probe-records /new/fast-probes.jsonl \
  --json-report /new/fast-report.json -- python benchmarks/adapter.py

python -m pyrepro reduce benchmarks/synthetic/case_method/input \
  --mode standard --standard-stage-policy fast-config \
  --pytest-node benchmarks/regression_test.py::test_method_failure \
  --timeout-seconds 15 --failure-match strict \
  --expect "method fixture failure" \
  --output /new/standard-output --probe-records /new/standard-probes.jsonl \
  --json-report /new/standard-report.json -- python benchmarks/adapter.py
```

Replace the case-specific node and expected failure with values from its
manifest. `verification/` contains the frozen 3/3 baseline evidence; complete
reduction outputs and JSONL records are retained in the external experiment
archive so the repository does not duplicate generated projects.
