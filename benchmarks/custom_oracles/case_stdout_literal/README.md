# case_stdout_literal

This fixture models a command that completes successfully but writes a stable
validation marker to standard output. The marker depends on a mismatched
expected checksum; deleting the relevant comparison changes the output and is
not a valid reduction.

The in-project `benchmarks/regression_test.py` is a fixture-owned overlay, not
an upstream test.
