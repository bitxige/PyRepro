# P3 execution-verified symbol reduction requirements

## Objective

P3 extends PyRepro from file-level reduction to execution-verified source-symbol
reduction. After the selected file reducer produces a verified workspace, P3
uses Python AST only to identify complete removable source ranges and uses the
existing runtime failure oracle as the sole acceptance criterion.

The P3 principle is:

> Static structure proposes complete symbols; execution validates every removal.

P3 must not use AST facts as evidence that a deletion is safe.

## Scope

P3 adds a greedy symbol phase after an existing file-reduction phase:

```text
trusted source project
        |
        v
existing greedy or ddmin file reduction
        |
        v
verified reduced workspace
        |
        v
AST symbol discovery
        |
        v
greedy symbol probes
        |
        v
final exact-signature verification
```

The public CLI contract becomes:

```bash
pyrepro reduce <source> \
  --strategy greedy|ddmin \
  --max-granularity file|symbol \
  [--expect TEXT] [--output PATH] -- <argv...>
```

`file` remains the default, preserving P2 behavior. `symbol` means that the
chosen file reducer runs first and the symbol phase runs only on its verified
workspace. It is not a separate entry point and it does not replace the P2
file strategy.

## Supported symbols

The initial P3 implementation supports only non-overlapping module-level
symbols:

- `ast.FunctionDef`;
- `ast.AsyncFunctionDef`; and
- `ast.ClassDef`.

Class methods, nested functions, nested classes, imports, assignments, control
flow blocks, expressions, and individual statements are not P3 mutation
candidates. A later, separately scoped extension may add methods; P3 must not
silently treat them as top-level symbols.

Every candidate records at least:

```python
SymbolCandidate(
    file_path="reward/shaping.py",
    qualified_name="normalize_reward",
    kind="function",
    start_line=18,
    end_line=34,
)
```

For a module-level symbol with decorators, `start_line` is the first decorator
line; otherwise it is the AST node's `lineno`. `end_line` is `end_lineno`.
Deleting a decorated symbol must remove the decorator lines with it. P3 uses
these ranges to remove lines from the original text; it must not mutate an AST
and regenerate a file with `ast.unparse`.

## Symbol discovery and mutation contract

P3 analyzes only P1-eligible Python files that remain after file reduction.
It reparses a file whenever an accepted deletion can have changed its line
ranges. Candidate ranges must therefore always come from the current source
text, never from stale line numbers captured before an earlier accepted probe.

For one candidate probe, the reducer must:

1. start from a disposable copy of the current reduced workspace;
2. discover or locate the current complete symbol range;
3. remove the inclusive source-line span from the copied file;
4. execute the same reproduction command; and
5. accept the source edit only when the result is `SAME_FAILURE` according to
   the existing exact failure signature.

`PASS`, `TIMEOUT`, syntax errors, import errors, a different traceback frame,
or any other non-matching outcome reject the probe. The active source project
must never be edited.

P3 uses greedy single-symbol probing only. It may finish with a final full
workspace oracle verification, but it does not claim a globally minimal symbol
set or a 1-minimal set across combinations of symbols.

If a remaining eligible file cannot be parsed, P3 must leave that file
unchanged, record that discovery was skipped, and continue with independently
parseable files. A parse failure must not be treated as evidence to remove any
source.

## Components

The implementation should add a focused module such as
`pyrepro/reproducer/symbol_reducer.py` rather than expanding the P2 file
reducer into unrelated AST logic. Keep the public pieces concrete and small:

```text
SymbolCandidate
    AST-derived source-range metadata

discover_symbols(path)
    current-file, module-level candidate discovery

GreedySymbolReducer
    copy -> remove complete range -> execute -> accept or reject
```

Do not introduce abstract reducer hierarchies, symbol ddmin, a generic AST
rewriter, or a static dependency graph in P3.

## Metrics

P3 preserves every P2 file-phase measurement and adds distinct symbol-phase
measurements. Do not merge the phases into one unexplained total.

| Metric | Definition |
| --- | --- |
| file-phase oracle executions | Existing selected file-reducer executions |
| symbol-phase oracle executions | Every symbol probe plus symbol final verification |
| total oracle executions | File-phase plus symbol-phase executions |
| file-phase wall-clock seconds | Existing selected file-reducer duration |
| symbol-phase wall-clock seconds | Duration of discovery, probes, and final verification |
| total wall-clock seconds | File-phase plus symbol-phase duration |
| eligible Python files | Before file reduction and after the complete pipeline |
| eligible Python LOC | Before file reduction, after file reduction, and after symbol reduction |
| supported symbols | Current module-level P3 candidates before and after symbol reduction |
| accepted symbol removals | Symbol probes accepted through `SAME_FAILURE` |
| rejected symbol probes | Symbol probes that do not preserve the signature |
| skipped unparsable files | Eligible remaining files for which discovery could not parse source |
| failure preserved | Final exact-signature verification result |
| source unchanged | Original source-tree digest result |

`total oracle executions` remains the primary cost metric. Symbol source
rewriting and AST parsing are local costs; rerunning a real reproduction command
can dominate total runtime.

## Symbol-failure benchmark design

P3 adds `examples/symbol_failure`, a deterministic standard-library-only Python
project with:

- 8 to 10 eligible Python files;
- approximately 650 to 1,200 physical Python LOC;
- at least 30 supported module-level P3 symbols; and
- a deterministic uncaught failure with a stable traceback frame.

The required failure chain should retain roughly four files after file-level
reduction, for example:

```text
reproduce.py
    -> training/trainer.py
    -> environment/road_env.py
    -> reward/shaping.py::weighted_reward
    -> ValueError: operands could not be broadcast ...
```

Each retained file must intentionally contain independent module-level
functions or classes that are not needed for the failure. At least one
removable function or class must be decorated, and at least one removable
function must be asynchronous or span multiple lines. File-level reduction
must not be able to remove these files wholesale; symbol reduction should be
able to remove substantial internal ballast while preserving the exact
signature.

The benchmark ground truth must specify:

- required failure-chain symbols that must remain;
- known removable top-level functions and classes;
- expected file-level and symbol-level reduction properties; and
- non-goals, including no claim that the final result is globally minimal.

The implementation should demonstrate a meaningful LOC and supported-symbol
reduction after file reduction. Exact percentage targets are deliberately not
fixed before implementation, so the fixture does not optimize for a fabricated
headline number.

## Tests and completion criteria

P3 implementation is complete only when tests demonstrate all of the
following:

1. Discovery returns correct type, qualified name, and inclusive span for
   top-level functions, async functions, and classes.
2. A removable top-level function and a removable class are accepted only when
   the exact failure remains.
3. A necessary failure-chain symbol is rejected and restored when its removal
   changes the outcome.
4. A same-type, same-message exception with a different traceback frame is
   rejected by the existing oracle.
5. Decorators are included in a deleted candidate's span.
6. Multi-line and asynchronous functions have correct source spans.
7. The final reduced files parse, the final workspace reproduces the baseline,
   and the original source tree remains unchanged.
8. CLI `--max-granularity file` preserves P2 behavior, while `symbol` runs the
   selected file strategy followed by the symbol phase.
9. Result metrics distinguish file and symbol phases and count every symbol
   oracle probe.
10. The `symbol_failure` benchmark demonstrates meaningful internal reduction
    in files that file-level reduction necessarily retains.

## Explicitly out of scope

- methods, nested symbols, and statement/expression-level reduction;
- grouped or ddmin symbol reduction;
- import, configuration, data, dependency, or environment reduction;
- static-analysis-guided candidate ordering or import-graph analysis;
- custom behavior oracles;
- execution sandboxing, parallel execution, LLMs, agents, MCP, and UI; and
- a claim of global minimum reduction.
