# PyRepro Architecture

## Overview

PyRepro reduces a trusted local Python project while preserving a stable,
user-specified runtime failure. Its central principle is:

> Static analysis guides reduction; execution validates it.

P3 implements execution-verified file reduction followed by optional
source-symbol reduction:

```text
Trusted local project + argv reproduction command
                    |
                    v
             Stable baseline (3 runs)
     exception + normalized message + traceback frame
                    |
                    v
            ReductionWorkspace
           disposable project copy
                    |
                    v
    GreedyFileReducer or DdminFileReducer
       probe candidates -> execute -> decide
                    |
                    v
      GreedySymbolReducer (optional)
     complete symbol -> execute -> decide
                    |
                    v
          Verified reduced project copy
```

The source project is never modified. A deletion is accepted only when the
candidate copy produces the same established failure signature.

## Package structure

```text
pyrepro/
├── __main__.py                # PyRepro module entry point
├── reproducer/
│   ├── runner.py              # argv command execution and captured output
│   ├── failure.py             # failure signatures and outcome classification
│   ├── workspace.py           # disposable copies and source-integrity checks
│   ├── reducer.py             # greedy/grouped reduction and candidate exclusions
│   └── symbol_reducer.py      # AST source spans and greedy symbol reduction
├── scanner/
│   ├── repository_scanner.py  # retained static repository inventory
│   └── ast_analyzer.py        # retained syntax-level facts
└── path_utils.py              # retained repository-path validation
```

The distribution, command, and Python package are named `pyrepro`.

## P3 responsibilities

### `reproducer.__main__`

The CLI accepts:

```text
pyrepro reduce <source> [--expect TEXT] [--strategy greedy|ddmin]
    [--max-granularity file|symbol] [--output PATH] -- <argv...>
```

It warns that the command will be executed repeatedly and requires users to
provide trusted local code and a trusted argv command. Without `--output`, the
result is written to a sibling `.pyrepro-output/<source-name>` directory.

### `reproducer.runner`

`CommandRunner` executes the argv command in a candidate workspace using
`shell=False`. It records exit status, standard output, standard error, and
timeouts. It does not install dependencies or interpret shell text.

### `reproducer.failure`

`FailureSignature` identifies an uncaught Python exception by exception type,
normalized message, and final repository-relative traceback frame. Line
numbers are deliberately excluded because reduction can move source lines.

P1 establishes the signature three times before reduction. An optional
`--expect` text anchor must match that stable signature. A disagreement aborts
the run rather than treating a flaky or unintended failure as reducible.

### `reproducer.workspace`

`ReductionWorkspace` creates a temporary copy of the source project. It
records a source-tree digest and copies the accepted result only after final
verification.

### `reproducer.reducer`

`GreedyFileReducer` is the P1 baseline algorithm. It temporarily removes one
candidate Python file at a time, reruns the command, and retains the deletion
only for a matching failure. It excludes common cache, environment, generated
output, data, model, and checkpoint directories from candidate deletion.

`DdminFileReducer` is a ddmin-inspired grouped strategy. It probes retained
candidate subsets and complements from fresh copies of the original candidate
tree, then runs single-file cleanup and an explicit 1-minimal verification
pass. Every probe, including the final minimality checks, contributes to the
reported oracle-execution and wall-clock metrics.

Both strategies report candidate Python files and physical LOC before and
after reduction, probe counts, removed files, command executions, and elapsed
time. The grouped result is 1-minimal only with respect to individual
candidate-file removal; neither strategy claims global minimality.

### `reproducer.symbol_reducer`

`GreedySymbolReducer` is the optional P3 phase. It runs only after the selected
file reducer has preserved the baseline. It discovers module-level
`FunctionDef`, `AsyncFunctionDef`, and `ClassDef` nodes, then removes their
original inclusive source ranges from disposable candidate copies. Decorator
lines are included in a decorated symbol's range.

AST is used only for structural location. Every deletion is accepted only if
the existing exact failure signature remains after execution. The reducer
reparses current source after accepted deletions so later ranges are not stale.
It does not mutate ASTs with `ast.unparse`, delete methods or statements, or
claim global or symbol-level 1-minimality.

P3 reports file-phase and symbol-phase oracle execution counts and wall-clock
durations separately, as well as symbol counts, symbol probe outcomes, and
unparsable files skipped during discovery.

## Retained static-analysis foundation

`RepositoryScanner`, `AstAnalyzer`, and `path_utils` are retained but are not
wired into P3's reducers. A later stage may use their deterministic facts
to prioritize candidates; execution remains the authority that accepts or
rejects every deletion.

## P3 trust boundary

P3 accepts a developer-selected local source directory and argv command. Both
are trusted inputs: PyRepro is not a sandbox for third-party code or arbitrary
commands. `shell=False` avoids shell parsing; it does not make execution safe.

P3 must not:

- modify the source project;
- install dependencies or set up network access;
- use `shell=True`;
- accept a flaky baseline or a different failure; or
- claim a globally smallest reproducer.

Stronger process isolation, dependency reduction, custom behavior oracles,
method-level reduction, and static-analysis-guided scheduling are future work.
