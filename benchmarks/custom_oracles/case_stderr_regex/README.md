# case_stderr_regex

This fixture models an invalid-record log whose payload number may vary while
its error class remains stable. The configured regular expression preserves
the error family instead of requiring a fixed full message. The adapter exits
successfully and writes the target marker only to standard error.

The in-project `benchmarks/regression_test.py` is a fixture-owned overlay, not
an upstream test.
