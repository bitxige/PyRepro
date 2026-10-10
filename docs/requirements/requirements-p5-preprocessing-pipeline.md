# P5.3a preprocessing-first composition requirements

## Objective

P5.3a composes existing target-aware import pruning with the existing greedy
file reducer. It verifies that accepted import edits are visible to later file
reduction without creating a second baseline or a second workspace.

> Import preprocessing must be execution-verified before it can guide existing
> repository reduction.

## Required behavior

The composed operation must:

1. Create one `ReductionWorkspace` and establish one three-run baseline.
2. Run `BatchImportPruner` in that workspace using the existing strict oracle.
3. Pass the established signature and same workspace to `GreedyFileReducer`.
4. Avoid a second three-run baseline in the file stage.
5. Preserve separate import-pruning and greedy `ProbeRecord` phases while
   exposing aggregate execution and wall-clock metrics.
6. Preserve source-tree integrity and perform each stage's existing final
   verification.

## Completion criteria

1. Flat and `src` layout fixtures demonstrate that a target-unneeded import
   can be pruned and then unlock a file removal.
2. The fixture uses a package re-export needed by the target to verify that
   target-context analysis does not remove required imports.
3. Tests prove the import stage reports three baseline runs and the greedy
   stage reports zero additional baseline runs.
4. Existing direct import-pruning and greedy behavior remains unchanged.

## Explicitly out of scope

- CLI integration and output packaging for the composed operation;
- directory/package grouping or dependency-aware scheduling;
- ddmin or symbol-reduction composition;
- broadening supported import or `__all__` source syntax; and
- large-repository performance claims or Tactics2D greedy experiments.
