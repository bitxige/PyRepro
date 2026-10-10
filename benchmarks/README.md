# Benchmark drivers

These drivers compare existing PyRepro configurations. They do not modify the
reducer algorithms or provide product CLI commands.

## Three-strategy preprocessing comparison

Run the comparison from the PyRepro repository root with a trusted local
repository and trusted argv reproduction command:

```bash
python benchmarks/compare_preprocessing_strategies.py /path/to/project \
  --pytest-node tests/test_example.py::test_failure -- \
  python run_target.py
```

The driver emits one JSON document on stdout for these configurations:

1. `blind_greedy`;
2. `import_then_greedy`; and
3. `import_coarse_then_greedy`.

It reports reducer-internal Oracle executions separately from three independent
final verification executions. `complete_wall_clock_seconds` starts before the
source-integrity and initial eligible-file scans, then includes workspace
creation, reduction, and independent final verification. The driver fixes one
source digest before running any strategy and checks it before and after every
strategy. A mismatch fails the current strategy and marks later strategies as
skipped, rather than comparing results from different source snapshots.
Redirect stdout to a results file outside the source project when retaining
experiment artifacts.

The driver is not a sandbox. It repeatedly executes the supplied command only
in disposable copies of a developer-selected trusted local project.
