# case_exit_code

This fixture models a validation command that reports a rejected payload with
process exit code `42`, without raising a Python exception. Its business rule
depends on both a status field and a deterministic checksum. Removing either
required condition changes the exit code and must be rejected by the Oracle.

The in-project `benchmarks/regression_test.py` is a fixture-owned overlay, not
an upstream test.
