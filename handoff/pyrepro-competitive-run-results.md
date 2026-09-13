# PyRepro Competitive Run Results

Date: 2026-09-13

This document records the first executable comparison against mature reducer
tools. It is a research handoff, not a product specification.

## Conditions

All runs used trusted local fixtures and exact argv commands. No LLM, Codex,
Terra, or external model service was used.

| Tool | Version / runtime | Oracle style |
| --- | --- | --- |
| PyRepro | current `main` after P3 | exception type, normalized message, traceback file, function |
| Perses | v2.7 release, OpenJDK 17 | executable test script |
| ShrinkRay | 26.7.8.0, Python 3.12 | executable interestingness script |

## PyRepro: multi-file project runs

| Case | Before | After | Oracle executions | Runtime | Failure preserved |
| --- | --- | --- | ---: | ---: | --- |
| `examples/symbol_failure` | 9 Python files / 650 LOC / 35 supported symbols | 4 Python files / 102 LOC / 4 symbols | 49 total | 1.234 s | Yes |
| `examples/training_failure` | 13 Python files / 61 LOC | 5 Python files / 33 LOC | 78 | 1.825 s | Yes |

The first case is the meaningful P3 result: file reduction produced four
necessary files, then symbol reduction reduced those files from 499 LOC to
102 LOC while preserving:

```text
ValueError: operands could not be broadcast together with shapes (4,) (3,)
reward/shaping.py::weighted_reward
```

The original projects were not modified. Reduced copies were independently
verified after reduction.

## Fair single-file adapter run

Because Perses' public input model is a source/test-script workflow, a small
single-file adapter was created for a capability comparison. This is not a
replacement for the multi-file project comparison.

| Tool | Input | Output | Oracle queries / executions | Runtime | Failure preserved |
| --- | --- | --- | ---: | ---: | --- |
| Perses | 49 LOC, 7 top-level symbols | 3 LOC, 0 top-level symbols | 24 test-script queries | about 2 s | Message oracle: Yes |
| PyRepro | 49 LOC, 7 top-level symbols | 27 LOC, 2 top-level symbols | 13 oracle executions | 0.269 s | Full signature: Yes |

Perses was more aggressive on this deliberately adapted single-file input.
The comparison is not an algorithmic win for PyRepro: Perses performs finer
grammar-level transformations, while the current PyRepro P3 reducer removes
whole top-level symbols. The Perses oracle for this adapter checked the exact
exception message; it did not enforce PyRepro's full traceback-frame identity.

## Perses on the original multi-file fixture

Perses v2.7 was also invoked directly with the original
`examples/symbol_failure` directory and then with all Python files passed as
repeated `--input-file` arguments. Both attempts failed during Perses
initialization with an `IllegalStateException: Check failed` in its input
initialization path, before reduction began.

Therefore there is no valid Perses multi-file result to compare. This is a
tool/workflow compatibility finding, not evidence that Perses cannot reduce
multi-file programs in every configuration.

## ShrinkRay

ShrinkRay 26.7.8.0 was installed in an isolated Python 3.12 environment and
invoked with a single-file adapter, `--no-llm`, serial execution, and a
custom exact-message interestingness script. It failed before the first
reduction because Trio could not create its epoll wakeup socket in the
execution container:

```text
PermissionError: [Errno 1] Operation not permitted
```

No ShrinkRay reduction result was produced. This must be reported as an
environment limitation, not as a reducer-quality result.

## What the comparison currently shows

1. PyRepro has a real project-level workflow: repository + argv command in,
   independently runnable reduced project out.
2. PyRepro's strict failure identity is stronger than a plain output-substring
   oracle, but it is also more restrictive and should become configurable in
   future experiments.
3. Perses is a strong single-file grammar-level baseline. Its 3-line result
   shows that PyRepro's current whole-symbol granularity is not competitive on
   fine-grained single-file minimization.
4. The current comparison does not establish that PyRepro's algorithm is
   better. It establishes a useful baseline and exposes the different input,
   oracle, and output contracts.

## P3.5 fair-oracle smoke

The hardened comparison harness was then used on the same 49 LOC adapter.
Both PyRepro modes completed three stable baseline runs and three stable
reduced-output verification runs:

| Mode | Match mode | After | Reducer queries | Verification executions | Runtime | Source unchanged |
| --- | --- | --- | ---: | ---: | ---: | --- |
| PyRepro-message | message | 27 LOC / 2 symbols | 13 | 6 | 0.332 s | Yes |
| PyRepro-strict | strict | 27 LOC / 2 symbols | 13 | 6 | 0.325 s | Yes |

For the previously completed direct Perses run, the baseline and reduced
output were each re-executed three times after the fact and produced the same
message each time. A second attempt to run Perses through the hardened
disposable-source wrapper failed during Perses initialization before any
reduction. The direct Perses result remains the valid single-file capability
result, while the wrapper incompatibility is recorded separately rather than
treated as a reducer-quality result.

## Recommended improvement priorities

### 1. Add finer reduction granularity

P3 removes complete functions, classes, and methods. Perses and AutoDD-style
 reducers can remove smaller syntax units. The next PyRepro improvement should
 be statement/block reduction, but it must preserve source formatting and use
 the execution oracle for every acceptance decision.

### 2. Make the oracle contract configurable

Keep the current strict signature as one mode, and add explicit modes for:

```text
type + message + frame
type + message
user-provided substring / predicate
```

The evaluation must measure how oracle strength changes reduction size,
false preservation, and execution cost.

### 3. Improve project-level dependency handling

The original multi-file workflow is PyRepro's strongest differentiator, but
blind probes can produce avoidable import/package failures. Investigate
Python-specific import topology, package initializers, re-exports, fixtures,
and symbol references for candidate grouping and scheduling. Static analysis
may prioritize or group candidates; runtime verification remains the final
authority.

This should be positioned as Python repository-specific scheduling/grouping,
not as the first dependency-aware reducer in the literature.

### 4. Emit comparable machine-readable metrics

The current CLI prints useful reduction summaries, but competitive studies
need stable JSON containing:

```text
before/after files, LOC, symbols
oracle executions and accepted/rejected probes
wall-clock time
failure signature
output verification status
```

### 5. Build a multi-file benchmark

The comparison exposed a real protocol gap: mature tools commonly expect a
single input file plus an oracle, while PyRepro starts from a runnable
repository. A small benchmark should include package imports, `__init__.py`,
re-exports, coupled modules, syntax-invalid candidates, timeouts, and stable
failure identity.

## Current conclusion

P3 is a strong engineering baseline and a useful research platform. The
comparison does not justify claiming a generic reduction algorithm novelty.
The most defensible next research direction is:

> execution-verified reduction of multi-file Python projects, with
> configurable failure identity and Python-specific dependency-coherent
> candidate scheduling.

That claim still requires a broader benchmark and controlled measurements.
