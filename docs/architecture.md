# PyRepro Architecture

## Overview

PyRepro reduces a trusted local Python project while preserving a stable,
user-specified runtime failure. Its central principle is:

> Static analysis guides reduction; execution validates it.

P3 implements execution-verified file reduction followed by optional
source-symbol reduction. P5.2c adds a deliberately separate, execution-
verified import-pruning operation before a later P5.3 composition stage:

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

pyrepro analyze-imports <source> [--pytest-node FILE::[CLASS::]TEST]
                    |
                    v
  Repository discovery + syntax-only import analysis
                    |
                    v
 candidates and conservative skips; no Oracle and no source edits

pyrepro prune-imports <source> --pytest-node FILE::[CLASS::]TEST -- <argv...>
                    |
                    v
  Stable baseline + target-aware candidates in a disposable workspace
                    |
                    v
 bounded ordinary batch -> strict Oracle -> accept or restore / split
                    |
                    v
 separate risk-marked batch -> strict Oracle -> verified pruned project
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
│   ├── import_pruner.py        # bounded verified source-local import pruning
│   ├── probe_report.py         # atomic opt-in JSONL probe telemetry
│   └── symbol_reducer.py      # AST source spans and greedy symbol reduction
├── scanner/
│   ├── repository_scanner.py  # retained static repository inventory
│   ├── ast_analyzer.py        # retained syntax-level facts
│   └── import_analyzer.py     # read-only import candidates and skip reasons
└── path_utils.py              # retained repository-path validation
```

The distribution, command, and Python package are named `pyrepro`.

## P3 responsibilities

### `reproducer.__main__`

The CLI accepts:

```text
pyrepro reduce <source> [--expect TEXT] [--strategy greedy|ddmin]
    [--max-granularity file|symbol] [--output PATH] -- <argv...>

pyrepro analyze-imports <source> [--pytest-node FILE::[CLASS::]TEST]

pyrepro prune-imports <source> --pytest-node FILE::[CLASS::]TEST
    [--max-import-probes N] [--probe-records PATH] -- <argv...>
```

It warns that the command will be executed repeatedly and requires users to
provide trusted local code and a trusted argv command. Without `--output`, the
result is written to a sibling `.pyrepro-output/<source-name>` directory.

`analyze-imports` is deliberately separate from `reduce`: it accepts no
reproduction command, never creates a reduction workspace, and only prints
syntax-derived import-pruning proposals with their conservative skip reasons.
When `--pytest-node` is supplied, it performs a target-scoped read-only pass:
the selected test, reachable same-module helpers/fixtures, decorators, and
module-load context define preserved import bindings; unrelated tests in the
same module do not. Static `__all__` candidates include a companion line for a
later consistent edit. Candidates carrying `side_effect_risk` remain proposals
only and require execution validation.

`prune-imports` is the narrow P5.2c validation stage. It uses that explicit
pytest node only for syntax-level target scope; its supplied argv remains the
actual trusted reproduction command. The pruner establishes the existing
three-run failure baseline in a disposable workspace, constructs only
source-local edits for simple one-line imports, and tests candidate operations
in bounded batches. A failed batch is restored completely before a bounded
bisection attempt. A static `__all__` companion is updated in the same atomic
operation as its matching re-export. Ordinary and `side_effect_risk` candidates
are processed in separate batches. Static analysis only proposes edits: the
existing failure oracle remains the sole acceptance authority.

Complex or multiline import statements, inline comments, semicolon chaining,
wildcard imports, dynamic imports, and dynamic or complex `__all__` constructs
are skipped rather than broadly rewriting module source. This operation does
not run file, grouped, or symbol reduction; P5.3 remains responsible for
composing verified preprocessing with repository reduction.

### `reproducer.runner`

`CommandRunner` executes the argv command in a candidate workspace using
`shell=False`. It records exit status, standard output, standard error, and
timeouts. It does not install dependencies or interpret shell text.

### `reproducer.failure`

`FailureSignature` identifies an uncaught Python exception by exception type,
normalized message, and final repository-relative traceback frame. Line
numbers are deliberately excluded because reduction can move source lines.

The strict signature is the product default. A message-only matching mode is
available for controlled external-tool comparisons and is not the default
acceptance policy.

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
file reducer has preserved the baseline. It discovers only module-level
`FunctionDef`, `AsyncFunctionDef`, and `ClassDef` nodes, then removes their
original inclusive source ranges from disposable candidate copies. Class
methods, nested symbols, statements, and expressions are not P3 candidates.
Decorator lines are included in a decorated symbol's range.

AST is used only for structural location. Every deletion is accepted only if
the existing exact failure signature remains after execution. The reducer
reparses current source after accepted deletions so later ranges are not stale.
It does not mutate ASTs with `ast.unparse`, delete methods or statements, or
claim global or symbol-level 1-minimality.

P3 reports file-phase and symbol-phase oracle execution counts and wall-clock
durations separately, as well as symbol counts, symbol probe outcomes, and
unparsable files skipped during discovery.

## Retained static-analysis foundation

`RepositoryScanner`, `AstAnalyzer`, `ImportAnalyzer`, and `path_utils` provide
read-only structural facts. `ImportAnalyzer` discovers flat / `src` source
roots, imports, conventional test modules, and package re-exports without
executing code. Its target-aware mode accepts only an explicit conventional
pytest function node and derives entry-scoped candidates. It treats wildcard
imports, dynamic imports, unresolved modules, and complex `__all__`
declarations as conservative skips; obvious import-time side effects are
reported as risk metadata in target mode. It is not wired into the reducers in
P5.2a/b. P5.2c consumes only those deterministic facts to construct narrow
import-edit candidates, while execution remains the authority that accepts or
rejects every edit.

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
