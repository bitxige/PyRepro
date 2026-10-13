# P7 atomic multiline import-surface pruning requirements

## Objective

P7 extends the existing target-aware, execution-verified import-pruning stage
to a deliberately small additional source shape: top-level multiline imports
and a single literal multiline ``__all__`` declaration that describes their
package re-exports.

The objective is not to infer that an import is safe to remove. Static analysis
continues to propose candidates and the existing strict failure oracle remains
the sole authority that accepts or rejects every edit.

```text
target-aware import candidates
        |
        v
atomic local import + __all__ edit
        |
        v
strict Oracle probe in the existing workspace
        |
        +-- same failure -> keep edit and run existing file cleanup
        |
        +-- any other result -> restore exact original source
```

P7 is motivated by the residual-file analysis in
`docs/analysis/residual-file-analysis.md`. That analysis found candidate-shape
evidence in Tactics2D and HTTPX, but no candidate evidence in Rich. P7 must not
claim that its syntax extension will improve every repository or reproduce the
manual HTTPX 13-file feasibility result.

## Scope

P7 changes only the source-local operation builder used by
`BatchImportPruner`. It reuses without modification:

- `ImportAnalyzer` target-aware candidate discovery;
- the existing batch/split search and its probe limit;
- `ReductionWorkspace`, source-integrity checks, and transaction rollback;
- `ExecutionBudget`, Fast Mode reservation semantics, and Oracle timeouts;
- the strict failure classifier and `ProbeRecord` format; and
- `PreprocessingFirstReducer`, coarse reduction, and greedy cleanup.

The public CLI and reducer ordering do not change. No new reducer, matching
mode, or benchmark strategy is introduced.

## Supported edit shape

P7 may construct an operation only when every affected construct meets all of
the following conditions:

1. The import is a top-level `ast.Import` or `ast.ImportFrom` selected by the
   existing analyzer. It may span multiple physical lines, including a
   parenthesized `from ... import (...)` form.
2. The import statement has no comment or semicolon in its complete source
   span. P7 may render the changed import canonically, but must not silently
   discard comments.
3. If a candidate has `all_line`, the referenced `__all__` is exactly one
   top-level `ast.Assign` statement with exactly one target,
   `ast.Name("__all__")`, even when multiline. Its value must be a literal list
   or tuple consisting only of string constants, and it must have no comments
   in its complete source span. Annotated assignments are skipped until their
   annotation semantics can be preserved exactly.
4. The import and `__all__` edits are produced and applied as one operation.
   Removing a re-export may never leave a dangling name in `__all__`.
   For `from .models import Response as PublicResponse`, the operation uses
   the binding/export name `PublicResponse` for both candidate removal and
   `__all__` removal; it must not remove the unrelated string `"Response"`.
5. All textual ranges are derived from the current parsed source and are
   non-overlapping. Edits are applied from the end of the file toward the
   beginning, preserving the existing newline convention.

If an operation removes every alias in an import statement, it removes the
whole statement and its following newline. If aliases remain, it renders only
the retained aliases. The corresponding literal `__all__` retains only names
that are not part of that operation's selected candidates.

Before any mutation, P7 must build one complete edit plan for the selected
batch. The plan groups candidates by source file, then by the concrete parsed
`__all__` assignment. It emits one replacement range for each import statement
and exactly one replacement range for each affected `__all__` assignment,
whose retained strings are computed from the union of selected bound names.
It must reject the plan rather than emit overlapping ranges. This permits a
batch to prune bindings from multiple import statements sharing one `__all__`
without producing conflicting replacements or skipping the entire initializer.

The plan is valid only for the current workspace text. Before every probe and
every recursive batch/split retry, P7 must reparse the current affected source
files and relocate each selected binding and its `__all__` assignment by stable
identity (path, bound/export name, and import context), not by a line number
captured before an earlier accepted edit. A missing or ambiguous binding is a
safe skip; it must never cause a stale range to edit a different construct.

AST column offsets are UTF-8 byte offsets, while ordinary Python string slices
use code-point indices. P7 therefore must derive and apply edit ranges in one
consistent unit: UTF-8 encoded bytes. It may decode only to parse and inspect
source, but must slice the original byte sequence with AST byte offsets and
encode replacements as UTF-8. This preserves non-ASCII text outside the edit,
handles multiline ranges correctly, and avoids mixing byte offsets with string
indices. CRLF remains part of the original byte sequence except where a
complete removed statement includes its following line ending.

## Conservative exclusions

P7 must continue to skip, with an explicit stable reason where discovery or
operation construction can report one:

- `import *`, dynamic imports, or imports not proposed by the analyzer;
- dynamic, computed, annotated, augmented, or multiple-target `__all__`
  assignments, including
  later `__all__.append`, `__all__.extend`, concatenation, or other writes;
- non-string or starred `__all__` values;
- comments, semicolons, invalid source, or tokenization ambiguity in an edited
  span;
- overlapping edits that cannot be composed deterministically; and
- any source construct outside the supported top-level import/re-export form.

An inability to construct a safe edit is not an Oracle failure and must not
modify the workspace. P7 must not add project-name, path-name, or repository-
specific rules for HTTPX, Tactics2D, Rich, or any other benchmark.

## Transaction and verification contract

P7 inherits the existing import-pruning transaction boundary:

1. Check the shared execution budget before changing the workspace.
2. Record exact original contents for every affected file before the first
   planned edit is written.
3. Apply the complete candidate batch to the active disposable workspace.
4. Run exactly one existing Oracle probe through the shared budget.
5. Keep the complete batch only for `SAME_FAILURE`; restore every affected file
   byte-for-byte for a different failure, timeout, execution exception, source
   edit error, or budget stop. A partial import/`__all__` restoration is never
   an allowed state.

An accepted P7 edit is an accepted intermediate candidate, not by itself a
verified published reproducer. Existing normal/final verification and Fast
Mode staging publication remain responsible for that stronger guarantee.

## Metrics and observability

No new benchmark accounting channel is needed. P7 continues to report the
existing `import_pruning` phase and records candidate descriptions that identify
the edited source path, original import line, and binding name.

For evaluation, record at least:

- discovered candidates, editable operations, and safely skipped candidates;
- attempted, accepted, and rejected import probes;
- final eligible Python file count and LOC after existing cleanup;
- total Oracle executions and wall-clock time; and
- strict final verification and source-integrity outcome.

Do not describe more editable candidates or accepted import edits as a success
unless existing file reduction subsequently removes files or the same result is
obtained at lower verified cost.

## Tests and completion criteria

P7 requires focused automated coverage before any repository benchmark:

1. A multiline parenthesized import can remove one alias while preserving the
   selected target failure.
2. A multiline literal list `__all__` and its re-export import are updated
   atomically on an accepted probe.
3. A multiline tuple `__all__` is supported under the same literal-only rules.
4. A rejected or budget-stopped multiline operation restores exact original
   contents of every edited file.
5. Two candidate import statements sharing one multiline `__all__` produce one
   composed `__all__` edit, not overlapping edits; accepted and rejected
   batch/split paths keep `__all__` consistent.
6. Comments, semicolons, dynamic `__all__` mutations (including `.extend()`),
   multiple `__all__` assignments, invalid syntax, and unsupported forms are
   conservatively skipped without workspace mutation.
7. CRLF input preserves valid newline boundaries after an accepted edit.
8. A non-ASCII line before a multiline candidate proves that AST byte offsets
   do not corrupt subsequent source or target the wrong range.
9. An accepted edit followed by a rejected edit and a later accepted edit in
   the same source file leaves earlier accepted changes intact, restores the
   rejected binding exactly, and rebuilds the shared multiline `__all__` from
   current source rather than stale coordinates.
10. Existing single-line import and `__all__` behavior remains covered and does
   not regress.
11. `PreprocessingFirstReducer` still shares its workspace/baseline with coarse
   and greedy stages, including Fast Mode budget-stop behavior.
12. Ruff and the complete test suite pass.

## Evaluation plan

After the implementation is frozen, use the already archived controlled cases
without changing their failure command, environment, matching mode, or source
snapshot:

| Case | Role | Required interpretation |
| --- | --- | --- |
| HTTPX #2998 | Development feasibility | Compare with its 23-file C baseline. The manual 13-file result is an upper-bound clue, not an acceptance target. |
| Tactics2D controlled case | Development feasibility | Compare with its 37-file C baseline and report whether multiline support releases additional files. |
| Rich #3115 | Negative control | Confirm zero candidates remains a safe no-op and report any added overhead. |
| One held-out case | Generalization check | Select before examining its P7 result; do not tune syntax rules from it. |

The evaluation reports file count first, then LOC, Oracle executions, complete
wall-clock, strict 3/3 verification, and source integrity. A result that helps
only HTTPX or only Tactics2D is a useful boundary finding, not evidence of a
universal improvement.

## Explicitly out of scope

- arbitrary Python rewriting, `ast.unparse`, or comment-preserving formatting
  frameworks;
- dynamic-import repair, import side-effect inference, or automatic import
  fixes;
- statement-, expression-, method-, or symbol-level reduction;
- new file reducers, new candidate ranking, or Tactics2D/HTTPX/Rich special
  cases;
- CLI, Fast Mode, Oracle, workspace, publisher, or benchmark-driver changes;
- claims of global minimality or a required final file-count target.
