# P0 Command-driven Failure Reduction Spike

## Objective

Validate the minimal reduction loop for a deterministic uncaught Python
exception:

```text
copy fixture -> establish baseline -> remove one file -> rerun -> accept or
restore -> final verification
```

## Inputs and execution boundary

- Accept the repository-owned `examples/failing_project` source root, an
  output directory, and an argv command after `--`.
- Execute argv with `shell=False` from a disposable workspace.
- Use a finite timeout and capture return code, stdout, and stderr.
- Run only the repository-owned `examples/failing_project` fixture in P0.
- Assume that the fixture and argv command are trusted developer inputs.
  `shell=False` prevents shell parsing but does not sandbox the command.
- Never install dependencies, use a network setup, modify the original source,
  or invoke an external agent or LLM service.

## Failure oracle

P0 supports an uncaught Python-exception oracle only. A stable
`FailureSignature` contains:

- exception type;
- normalized exception message; and
- final in-repository traceback frame: repository-relative file and function.

The baseline command runs three times. Reduction aborts when any baseline
signature differs or an execution passes, times out, or does not expose a
Python traceback.

## Reduction behavior

- Copy the fixture to a temporary workspace.
- Enumerate Python files in deterministic repository-relative order.
- Temporarily remove one candidate file at a time.
- Accept removal only for `SAME_FAILURE`.
- Restore files after `PASS`, `DIFFERENT_FAILURE`, or `TIMEOUT`.
- Run a final verification after all candidates are considered.
- Copy the verified reduced workspace to the requested output directory.

## Completion criteria

1. `python reproduce.py` produces the same baseline signature three times.
2. The fixture contains 10 to 12 Python files and reduction removes at least
   five unrelated files.
3. Removing a required file is rejected when it changes the failure.
4. A source-tree digest confirms that the original fixture is unchanged.
5. The output directory independently reproduces the baseline failure.
6. Tests cover runner results, signature parsing, baseline instability,
   accepted removal, rejected removal, final verification, and source safety.

## Explicitly out of scope

- arbitrary repository execution;
- custom oracles, regex matching, or successful-but-interesting behavior;
- ddmin, static ranking, AST or symbol reduction;
- configuration, data, dependency, or environment reduction;
- Docker or another execution sandbox; and
- external agent integrations, web UI, or an internal Python package rename.
