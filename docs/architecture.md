# PyRepro Architecture

## Overview

PyRepro reduces a Python project while preserving a user-specified, stable
runtime failure. Its central principle is:

> Static analysis guides reduction; execution validates it.

P0 implements the execution-verified core with a trusted local fixture:

```text
Trusted source fixture + reproduction command
                    |
                    v
            ReductionWorkspace
           disposable project copy
                    |
                    v
              CommandRunner
                    |
                    v
           FailureSignature baseline
             exception + message + frame
                    |
                    v
            GreedyFileReducer
       remove candidate -> execute -> decide
                    |
                    v
          Verified reduced project copy
```

The original source project is never modified. P0 accepts a deletion only when
the candidate copy produces the same established failure signature.

## Package structure

```text
reposentinel/                  # Temporary internal package name
├── __main__.py                # PyRepro module entry point
├── reproducer/
│   ├── runner.py              # argv command execution and captured output
│   ├── failure.py             # failure signatures and outcome classification
│   ├── workspace.py           # disposable copies and source-integrity checks
│   └── reducer.py             # greedy file-level reduction
├── scanner/
│   ├── repository_scanner.py  # retained static repository inventory
│   └── ast_analyzer.py        # retained syntax-level facts
└── path_utils.py              # retained repository-path validation
```

The distribution and command are named `pyrepro`. The Python package remains
`reposentinel` temporarily so that this pivot does not mix product cleanup
with a broad mechanical import rename.

## P0 responsibilities

### `reproducer.runner`

`CommandRunner` executes an argv command in a candidate workspace using
`shell=False`. It records exit status, standard output, standard error, and
timeouts. It does not install dependencies or run shell text.

### `reproducer.failure`

`FailureSignature` identifies a Python exception by its exception type,
normalized message, and final repository-relative traceback frame. Line
numbers are deliberately excluded because reduction can move source lines.

P0 establishes this signature three times before reduction. A disagreement
aborts the run rather than treating a flaky failure as reducible.

### `reproducer.workspace`

`ReductionWorkspace` creates a temporary copy of the trusted source fixture.
It records a source-tree digest and copies the accepted result to a new output
directory only after final verification.

### `reproducer.reducer`

`GreedyFileReducer` is the P0 baseline algorithm. It temporarily removes one
Python file at a time, reruns the command, and retains the deletion only for a
matching failure. It intentionally does not claim global minimality.

## Retained static-analysis foundation

`RepositoryScanner`, `AstAnalyzer`, and `path_utils` are retained but are not
wired into P0's greedy reducer. A later stage may use their deterministic
facts to prioritize candidates; execution will remain the authority that
accepts or rejects every deletion.

## P0 trust boundary

P0 runs only the repository-owned `examples/failing_project` fixture. Both the
fixture and the argv reproduction command are trusted inputs for this spike.
`shell=False` avoids shell parsing; it is not a sandbox for arbitrary command
execution.

P0 must not:

- modify the source fixture;
- install dependencies;
- use an LLM, MCP server, or agent;
- use `shell=True`; or
- claim a globally smallest reproducer.

General trusted-local repository support and stronger process isolation are
future work, not P0 behavior.
