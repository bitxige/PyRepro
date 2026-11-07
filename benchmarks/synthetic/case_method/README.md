# case_method

Deterministic fixture for the production direct-method reduction stage. The
strict failure is raised only by `Scenario.trigger`; three unrelated direct
methods are intentionally available for execution-verified removal.

The in-project overlay is `input/benchmarks/regression_test.py`. It is a
fixture-owned regression test, not an upstream test.
