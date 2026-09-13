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

P1 supports a developer-selected **trusted local** Python project and an argv
reproduction command. PyRepro establishes a stable Python failure signature,
works in a disposable copy, greedily removes candidate Python files, and
verifies the same failure in the final output.

PyRepro runs the supplied command repeatedly. It does not install dependencies
or modify the source project, but it is not an execution sandbox. Only use it
with code and commands you trust.

## Usage

```bash
python -m pip install -e ".[dev]"

pyrepro reduce ~/my_project \
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

## Architecture and roadmap

See [docs/architecture.md](docs/architecture.md) for the P1 data flow and
retained static-analysis foundations. The broader goals and staged roadmap are
in [docs/project-overview.md](docs/project-overview.md).

Planned work after P1:

- P2: grouped and delta-debugging file reduction, with oracle-execution-cost
  metrics and a dedicated grouped-failure benchmark (design defined);
- P3: static-analysis-guided candidate scheduling;
- P4: symbol-level reduction; and
- P5: reproducer packaging and reporting.

## Development

See [CHANGELOG.md](CHANGELOG.md) for notable current changes.

```bash
ruff check .
ruff format --check .
pytest
```
