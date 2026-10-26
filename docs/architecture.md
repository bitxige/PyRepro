# PyRepro Architecture

## Overview

PyRepro reduces a trusted local Python project while preserving a stable,
user-specified runtime failure. Its central principle is:

> Static analysis guides reduction; execution validates it.

PyRepro implements execution-verified file reduction followed by optional
source-symbol reduction. Its opt-in Fast Mode composes target-aware import
pruning, bounded coarse deletion, greedy cleanup, optional complete-symbol,
direct-method, complete-if, and module-dictionary-entry reduction, and verified
publication:

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

pyrepro reduce <source> --mode fast --pytest-node FILE::[CLASS::]TEST
    --max-oracle-executions N -- <argv...>
                    |
                    v
  shared baseline -> import pruning -> coarse groups -> greedy cleanup -> optional symbols -> optional methods -> optional complete if -> optional container entries
                    |
                    v
      sibling staging -> independent 3/3 -> atomic no-clobber publication

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
│   ├── preprocessing.py        # shared-workspace preprocessing-first pipeline
│   ├── coarse_reducer.py       # bounded generic directory-group probes
│   ├── budget.py               # Fast-Mode shared Oracle/time budget
│   ├── publisher.py            # staging verification and verified publication
│   ├── probe_report.py         # atomic opt-in JSONL probe telemetry
│   ├── symbol_reducer.py      # AST source spans and greedy symbol reduction
│   ├── if_statement_reducer.py # bounded complete-if source reduction
│   └── container_entry_reducer.py # bounded module-dictionary entry reduction
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

`prune-imports` is the narrow P5.2c validation stage. The unreleased P7 work
extends its supported source shapes. It uses that explicit
pytest node only for syntax-level target scope; its supplied argv remains the
actual trusted reproduction command. The pruner establishes the existing
three-run failure baseline in a disposable workspace, constructs only
source-local edits for simple one-line imports, and tests candidate operations
in bounded batches. A failed batch is restored completely before a bounded
bisection attempt. A static `__all__` companion is updated in the same atomic
operation as its matching re-export. Ordinary and `side_effect_risk` candidates
are processed in separate batches. Static analysis only proposes edits: the
existing failure oracle remains the sole acceptance authority. P7 additionally
supports a deliberately narrow parenthesized multiline form with one static
literal list or tuple `__all__`; each probe reparses current workspace source,
and annotated or multiple-target `__all__` assignments remain unsupported.
When P7-only multiline operations coexist with prior single-line editor
shapes, it completes the prior low-risk/risk cohort first under the same shared
probe cap, then spends only any remainder on the P7-only cohort. This preserves
existing bounded-search opportunities without changing Oracle acceptance.

Inline comments, semicolon chaining, wildcard imports, dynamic imports, and
dynamic or complex `__all__` constructs are skipped rather than broadly
rewriting module source. This operation does not run file, grouped, or symbol
reduction; the preprocessing-first pipeline remains responsible for composing
verified preprocessing with repository reduction.

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
It does not mutate ASTs with `ast.unparse`, delete statements, or claim global
or symbol-level 1-minimality. Standard Mode continues to use only top-level
symbols.

Fast Mode may invoke the same reducer a second time with its deliberately
narrow direct-method scope. That scope contains only `FunctionDef` and
`AsyncFunctionDef` nodes immediately inside module-level classes; it excludes
nested classes and skips a class with a sole method, so it never creates an
empty class body. Rejected source edits exist only in a disposable probe copy,
and their JSONL telemetry marks `candidate_rolled_back`.

### Fast Mode composition and publishing

`PreprocessingFirstReducer` shares one workspace and baseline across verified
import pruning, optional `CoarseFileReducer` directory-group probes,
`GreedyFileReducer` cleanup, optional complete-symbol then direct-method
`GreedySymbolReducer` stages, optional `GreedyIfStatementReducer`
complete-source-if probes, and optional `GreedyContainerEntryReducer` probes.
All four source stages are disabled by default and
enabled only with positive `--max-symbol-probes`, `--max-method-probes`, or
`--max-if-statement-probes`, or `--max-container-entry-probes` values.
`--symbol-order span-desc` is a deterministic
advisory ordering, not an acceptance rule. Complete-if probes use a fixed
span-descending advisory order. They are limited to ordinary source `if`
statements within top-level functions and direct methods; `elif`, nested
definitions, module/class bodies, and comment/semicolon spans are skipped.
Deleting a sole statement from its direct parent suite inserts `pass` to retain
valid syntax. Container-entry probes are limited to source-safe multiline
module dictionaries with string keys and static values. They first probe whole
entry batches and recursively split rejected batches; comments, semicolon
chains, dynamic expressions, unpacking, duplicate keys, and rebound bindings
are skipped. Exact source-range edits preserve surrounding source. In Fast
Mode, all Oracle invocations pass through one
`ExecutionBudget`: it reserves three executions for final verification and uses
a monotonic deadline to bound each command timeout. A budgeted pipeline does not
repeat stage-final checks; it retains only individually accepted workspace changes.

The CLI is an orchestration layer. It passes the final workspace and established
signature to `verify_and_publish`, which creates sibling staging, runs the
independent final 3/3 there, and atomically publishes only on success. Linux
publication requires `renameat2(RENAME_NOREPLACE)`; there is no unsafe rename
fallback. The publisher owns output no-clobber and source-integrity rules; the
CLI maps its structured terminal states to user-facing output and exit status.

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
