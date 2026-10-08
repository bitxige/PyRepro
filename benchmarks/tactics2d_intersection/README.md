# Tactics2D Large-Repository Controlled Benchmark

This benchmark measures PyRepro's repository-level failure reduction on a
real Python project with a controlled business-logic regression. It is a
**large-repository controlled benchmark**, not a historical real-world bug.

## Fixed input

- Tactics2D commit: `23d81691fd1c297c987918d7936f9b3db123a696`
- Eligible Python files: 246
- Eligible Python lines: 66,892 (PyRepro's physical-line counter)
- Controlled change: [`controlled.patch`](controlled.patch)
- Target test function:
  `tests/test_map_generator.py::test_intersection_asymmetric_arm_geometry`

The patch changes the `TwoWay.build()` validation boundary from accepting one
forward lane to incorrectly rejecting it. The original test constructs a
one-lane intersection arm, so the regression naturally raises:

```text
ValueError: forward_lane_num must be >= 1.
tactics2d/map/generator/road_segment/two_way.py::build
```

## Reproduce the controlled failure

Clone Tactics2D at the fixed commit and apply the patch outside this
repository:

```bash
git clone https://github.com/bitxige/tactics2d.git tactics2d-pyrepro-bench
cd tactics2d-pyrepro-bench
git checkout 23d81691fd1c297c987918d7936f9b3db123a696
git apply /absolute/path/to/PyRepro/benchmarks/tactics2d_intersection/controlled.patch
```

Run the adapter from the Tactics2D root:

```bash
env PYTHONPATH=. MPLCONFIGDIR=/tmp/tactics2d-pyrepro-mpl \
  python /absolute/path/to/PyRepro/benchmarks/tactics2d_intersection/adapter.py
```

`adapter.py` loads and directly invokes the original zero-argument pytest
test function. It does not reproduce its business logic independently. The
adapter is outside the candidate repository so file reduction cannot delete
it. Direct invocation leaves the `ValueError` uncaught, which is required by
the current ExceptionOracle. Native pytest reporting writes its failure report
to stdout and is therefore not currently supported by that oracle.

## P3.5 greedy baseline

The recorded P3.5 result is in
[`p3_5_baseline.json`](p3_5_baseline.json). It was produced with strict failure
matching, a 15-second per-run timeout, `--strategy greedy`, and
`--max-granularity file` only.

```text
Files:       246 -> 87
Python LOC:  66,892 -> 20,846
Oracle runs: 250
Accepted:    159
Rejected:    87
Timeouts:    0
Runtime:     363.594 seconds
Failure:     preserved; final output verified 3/3
Source:      unchanged
```

The complete run log and reduced project are intentionally external experiment
artifacts and are not committed. P3.5 records rejected probes only as
`different_failure`; the breakdown of dependency-related exception types is
therefore unavailable in this baseline.

## Comparison rules

Future dependency-aware experiments must reuse the same Tactics2D commit,
controlled patch, adapter, failure signature, timeout, and command. Compare
both reduction quality (remaining files and LOC) and execution cost (oracle
runs, runtime, and rejected probes). Do not infer a global minimum from this
greedy result.
