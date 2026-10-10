# P5.2c execution-verified batch import-pruning requirements

## Objective

P5.2c turns P5.2a/b target-aware import candidates into small, source-local
edits that are accepted only after the existing runtime failure oracle confirms
the established failure. It is a distinct preprocessing operation, not a file
reduction pipeline.

The stage principle is:

> Static target analysis proposes import edits; the execution oracle alone
> accepts or rejects each batch.

## Command interface

```bash
pyrepro prune-imports <source> --pytest-node FILE::TEST \
    [--max-import-probes N] [--probe-records PATH] -- <argv...>
```

`FILE::CLASS::TEST` is also accepted. The pytest node controls only static
candidate analysis; `<argv...>` remains the developer-selected trusted local
reproduction command. The command uses the strict failure match by default,
supports the same optional `--expect`, `--failure-match`, `--timeout-seconds`,
and output conventions as `reduce`, and establishes a three-run baseline.

## Candidate operations

P5.2c may edit only:

1. A simple, one-line, top-level `import` or `from ... import` statement with
   no inline comment or semicolon chaining.
2. A matching static, one-line list or tuple `__all__` assignment for a
   target-aware package re-export.

The re-export import and matching `__all__` update form one atomic operation.
The implementation must preserve all unrelated source bytes. It must not use
`ast.unparse` to rewrite a module. Complex/multiline statements, star imports,
dynamic imports, and dynamic or complex `__all__` definitions remain skips.

## Batch validation and rollback

The implementation must:

- make all edits only within `ReductionWorkspace`;
- group ordinary candidates into a batch before attempting individual changes;
- process `side_effect_risk` candidates in a separate batch;
- accept a batch only when the strict failure oracle reports the baseline;
- fully restore every edited file after rejection;
- split a rejected batch only while `--max-import-probes` allows it; and
- perform final strict verification before publishing the pruned output.

The source project must remain unchanged. A static candidate, including a
risk-marked candidate, is never deletion permission.

## Observability

Each dynamic candidate execution must emit a `ProbeRecord` with phase
`import_pruning`, source paths, binding-level candidate descriptions, outcome,
acceptance, duration, exception details, and proposed Python LOC. Optional
JSONL export must preserve those fields and must not alter pruning decisions.

## Completion criteria

1. A controlled fixture accepts multiple edits in one Oracle probe.
2. A rejected composite batch restores all source files before bounded splitting.
3. Static `__all__` re-export pruning updates the import and export list
   atomically.
4. The public CLI copies only a final-verified output and can export JSONL.
5. Existing file-reduction behavior remains unchanged.
6. Tests cover flat package and source-local target analysis without
   repository-specific paths or module names.

## Explicitly out of scope

- automatic import repair;
- arbitrary Python statement rewriting;
- Greedy/ddmin/symbol reduction integration;
- package or directory deletion;
- ranking, global time budgets, or Fast Mode; and
- Tactics2D-specific rules or directory handling.
