# PyRepro

PyRepro automatically reduces a failing Python project into a smaller,
execution-verified reproducing case.

```text
Large failing project
        |
        v
      PyRepro
        |
        v
Smaller verified reproducer
```

Its guiding principle is:

> Static analysis guides reduction; execution validates it.

## Current status

PyRepro supports a developer-selected **trusted local** Python project and an
argv reproduction command. It establishes a stable Python failure signature,
works in a disposable copy, and verifies the same failure in the final output.
It provides greedy and grouped file strategies, optional top-level symbol
reduction, and an opt-in Fast Mode that composes import pruning, bounded coarse
file reduction, greedy cleanup, optional complete-symbol, direct-method, and
complete-`if` reduction, final staging verification, and safe output
publication.

PyRepro runs the supplied command repeatedly. It does not install dependencies
or modify the source project, but it is not an execution sandbox. Only use it
with code and commands you trust.

## Usage

```bash
python -m pip install -e ".[dev]"

pyrepro reduce ~/my_project \
  --strategy ddmin \
  --max-granularity symbol \
  --expect "operands could not be broadcast" \
  -- python train.py --config configs/debug.yaml
```

`--expect` is optional. When supplied, its normalized text must occur in the
established failure signature before reduction begins. This prevents reduction
from starting against an unintended baseline failure.

`--failure-match strict` is the default and preserves the complete failure
identity: exception type, normalized message, and final traceback frame. The
`message` mode is reserved for controlled reducer comparisons; it intentionally
does not change the default product behavior.

By default, the verified output is written outside the source project at:

```text
<source-parent>/.pyrepro-output/<source-name>/
```

Use `--output <path>` to choose another non-existing directory outside the
source project.

Candidate deletion skips common environment, generated-output, data, model,
and cache directories. Those files remain available in each disposable copy so
the reproduction command can still use them.

`--strategy` accepts `greedy` (the default) and `ddmin`. The latter uses fresh
candidate copies for grouped probes, then verifies that no remaining candidate
file can be removed independently. It reports candidate Python files and LOC,
oracle executions, probe outcomes, removed files, and wall-clock duration. It
does not claim a globally smallest reproducer.

`--max-granularity` accepts `file` (the default) and `symbol`. Symbol mode first
runs the selected file strategy, then greedily probes complete module-level
functions, async functions, and classes within the retained files. AST only
locates original source ranges, including decorators; the runtime failure oracle
is still the only acceptance criterion.

`--probe-records <path>` optionally writes one JSONL object for each
execution-verified candidate probe. Each record includes the phase, proposed
candidate paths and optional binding-level details, oracle outcome, acceptance
decision, command duration, cumulative command time, proposed candidate Python
LOC, return code, parsed exception details, failure signature, and whether a
rejected source-edit candidate was rolled back. The path
must be new and outside the source project. This observability output does not
alter reduction decisions.

`--json-report <path>` and `--html-report <path>` optionally write final
result reports. They are separate from probe telemetry: each report summarizes
the completed reduction's size, Oracle cost, stage metrics, source integrity,
publication status, and final verification. Both paths must be new and outside
the source project. The HTML report is rendered from the same data as the JSON
report. In Fast Mode, an unpublished terminal state remains explicitly marked
as unverified and unpublished.
See [`docs/report-schema.md`](docs/report-schema.md) for field meanings and
Oracle-counting boundaries.

The module entry point is equivalent:

```bash
python -m pyrepro reduce examples/training_failure \
  --probe-records /tmp/pyrepro-probes.jsonl \
  --expect "operands could not be broadcast" \
  -- python train.py
```

## Fast Mode

Fast Mode is an explicit, budgeted workflow for producing a verified
reproducer. It uses target-aware import pruning, optional coarse file probes,
and greedy cleanup under one global Oracle-command budget. The output is copied
to staging and independently verified three times before PyRepro publishes it.

```bash
pyrepro reduce ~/my_project \
  --mode fast \
  --pytest-node tests/test_example.py::test_failure \
  --max-oracle-executions 60 \
  --max-time-seconds 120 \
  --max-import-probes 16 \
  --max-coarse-probes 16 \
  --max-symbol-probes 60 \
  --max-method-probes 60 \
  --max-if-statement-probes 60 \
  --max-container-entry-probes 60 \
  --max-list-entry-probes 60 \
  --symbol-order span-desc \
  --json-report /tmp/reduced-example.json \
  --html-report /tmp/reduced-example.html \
  --output /tmp/reduced-example \
  -- python run_target.py
```

`--mode fast` requires both `--pytest-node` and
`--max-oracle-executions`. It supports greedy file cleanup and optional,
default-disabled complete-symbol, direct-method, complete-`if`,
module-dictionary-entry, and module-list-entry stages.
`--max-symbol-probes 0`, `--max-method-probes 0`, and
`--max-if-statement-probes 0`, `--max-container-entry-probes 0`, and
`--max-list-entry-probes 0` disable
their respective stages; positive values bound their probes. Method reduction
is deliberately limited to direct methods
of module-level classes and skips a sole method rather than creating an empty
class body. Complete-`if` reduction considers only complete source `if`
statements in top-level functions and direct methods. It excludes source
`elif` nodes, nested definitions, module/class bodies, comments, and semicolon
chains; it inserts `pass` only when removal would otherwise empty the direct
parent suite. Its fixed span-descending order is advisory, not deletion
permission. Container-entry reduction runs after complete-if reduction. It
only considers unambiguous multiline module-level dictionaries with string
keys and either string or integer literals (excluding booleans), or direct named
constructor calls whose
arguments are static literals. It skips comments, semicolon chains, duplicate
or rebound bindings, unpacking, and dynamic values. It probes whole entry
batches and recursively splits rejected batches; static facts never accept a
deletion on their own. List-entry reduction runs after module-dictionary
reduction. It only considers unambiguous multiline module-level lists whose
unique entries are tuples of integer literals. It skips comments, semicolon
chains, duplicate or rebound bindings, dynamic items, and all other list
shapes. It probes whole entry batches and recursively splits rejected batches;
static facts never accept a deletion on their own. `--symbol-order span-desc`
probes larger source spans first, with stable path and source-position
tiebreakers, for every enabled symbol stage. All five stages share the Fast
Mode budget, strict Oracle, rollback, and final Publisher verification; none
uses `--max-granularity symbol`.
`--strategy ddmin` and `--max-granularity symbol` remain rejected in Fast Mode,
and `--max-coarse-probes 0` disables the optional coarse stage.

The command budget reserves three executions for final independent verification.
The minimum budget is six executions: three to establish the baseline and three
to verify the staged output. A six-execution run has no search probes available;
it can safely publish the unchanged accepted workspace after final 3/3
verification, but does not promise additional minimization.

Fast Mode prints one of these user-visible outcomes:

- `completed`: reduction finished and a final 3/3-verified reproducer was
  published.
- `budget_exhausted_verified`: search stopped for the configured budget, but
  the accepted candidate passed final 3/3 verification and was published.
- an unpublished failure: no official reproducer is created when final
  verification cannot complete, fails to match, the source changes, or a
  runtime/publication error occurs.

On Linux, publication uses an atomic no-clobber operation. The requested
output path must be new and outside the source project. Fast Mode fails safely
on platforms or filesystems that cannot provide that publication guarantee.

## Read-only import analysis

Use `analyze-imports` to inspect generic preprocessing candidates before any
reduction. It supports common flat and `src` layouts, package re-exports, and
relative imports, while reporting conservative skips for uncertain structures.
It does not execute a reproduction command or modify the source project.

```bash
pyrepro analyze-imports ~/my_project
```

The report lists potential unused test-module imports and package re-exports,
alongside explanations for skips such as dynamic imports, `import *`, unresolved
modules, and obvious import-time side effects. A listed candidate is not proof
that deletion is safe; a later reduction phase must validate any edit with the
failure oracle.

For a conventional pytest failure, scope analysis to the exact target test so
imports used solely by unrelated tests in the same file can become candidates:

```bash
pyrepro analyze-imports ~/my_project \
  --pytest-node tests/test_example.py::test_failure
```

Class-method nodes use `FILE::CLASS::TEST`. This remains a read-only command:
it neither executes pytest nor changes source. Re-export candidates show an
associated static `__all__` line when a later verifier must update both
structures together. A `side_effect_risk` label means the static analyzer found
an import-time uncertainty; it is not approval to remove the import.

## Execution-verified import pruning

`prune-imports` converts target-aware import candidates into narrowly scoped,
source-local edits in a disposable workspace. It first establishes the normal
three-run strict failure baseline, then tries ordinary candidates in a batch.
Rejected batches are restored and split only up to `--max-import-probes`.
Candidates carrying `side_effect_risk` are tried separately after ordinary
candidates; neither group is accepted without the same runtime failure.

```bash
pyrepro prune-imports ~/my_project \
  --pytest-node tests/test_example.py::test_failure \
  --max-import-probes 16 \
  --probe-records /tmp/import-pruning.jsonl \
  -- python run_target.py
```

The unreleased P7 implementation extends this stage to top-level single-line
and parenthesized multiline `import` / `from ... import` statements, plus one
static literal `__all__` list or tuple. It skips any edited span with comments
or semicolon chaining. For a package re-export, all selected import bindings
and their shared `__all__` entries form one atomic proposal. Dynamic imports,
wildcard imports, dynamic exports, annotated or multiple-target `__all__`
assignments, and source shapes that cannot be safely composed are skipped rather
than rewritten. `prune-imports` does not run greedy, ddmin, or symbol reduction;
the preprocessing-first reducer composes verified preprocessing with file
reduction.

## Included smoke fixtures

- `examples/failing_project`: preserves `KeyError: 'width'` at
  `app/parser.py::parse_lane` and reduces 12 candidate Python files to 3.
- `examples/training_failure`: simulates a training reward-vector mismatch and
  preserves `ValueError: operands could not be broadcast...` at
  `reward/shaping.py::weighted_reward`.
- `examples/grouped_failure`: contains 33 eligible Python files, including an
  optional pair that greedy retains individually but the grouped strategy can
  remove together while preserving `RuntimeError: grouped reduction failure`.
- `examples/symbol_failure`: a 9-file, 650-LOC fixture that first reduces to
  four required files, then removes internal top-level symbol ballast while
  preserving the deterministic reward shape mismatch.

## Architecture and roadmap

See [docs/architecture.md](docs/architecture.md) for the reduction and
retained static-analysis foundations. The broader goals and staged roadmap are
in [docs/project-overview.md](docs/project-overview.md).

See `docs/requirements/requirements-p6-fast-mode.md` for Fast Mode's budget,
verification, and publication contract.

## Development

See [CHANGELOG.md](CHANGELOG.md) for notable current changes.

```bash
ruff check .
ruff format --check .
pytest
```
