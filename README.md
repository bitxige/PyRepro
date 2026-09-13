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

P3 supports a developer-selected **trusted local** Python project and an argv
reproduction command. PyRepro establishes a stable Python failure signature,
works in a disposable copy, and verifies the same failure in the final output.
It provides P1 greedy and P2 grouped file strategies, plus optional P3
execution-verified reduction of complete top-level Python symbols.

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

The module entry point is equivalent:

```bash
python -m pyrepro reduce examples/training_failure \
  --expect "operands could not be broadcast" \
  -- python train.py
```

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

See [docs/architecture.md](docs/architecture.md) for the P3 data flow and
retained static-analysis foundations. The broader goals and staged roadmap are
in [docs/project-overview.md](docs/project-overview.md).

Planned work after P3:

- P4: static-analysis-guided candidate scheduling; and
- P5: reproducer packaging and reporting.

## Development

See [CHANGELOG.md](CHANGELOG.md) for notable current changes.

```bash
ruff check .
ruff format --check .
pytest
```
