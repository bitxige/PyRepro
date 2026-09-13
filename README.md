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

P0 validates the smallest useful end-to-end workflow against a trusted local
fixture. PyRepro establishes a stable Python failure signature, works in a
disposable copy, greedily removes irrelevant Python files, and verifies the
same failure in the final reduced output.

P0 is a controlled spike, not yet a general-purpose sandbox for arbitrary
repositories or commands. It does not install dependencies or modify the
source project.

## Try the P0 fixture

From a checkout:

```bash
python -m pip install -e ".[dev]"
pyrepro examples/failing_project \
  --output /tmp/pyrepro-reduced \
  -- python reproduce.py
```

Until the internal package rename is complete, the equivalent module command
is:

```bash
python -m reposentinel examples/failing_project \
  --output /tmp/pyrepro-reduced \
  -- python reproduce.py
```

The expected fixture result preserves `KeyError: 'width'` at
`app/parser.py::parse_lane` while reducing 12 Python files to the three files
needed for reproduction.

## Architecture and roadmap

See [docs/architecture.md](docs/architecture.md) for the implemented P0 data
flow and retained static-analysis foundations. The broader goals and staged
roadmap are in [docs/project-overview.md](docs/project-overview.md).

Planned work, after P0:

- P1: trusted-local command support and more explicit failure matching;
- P2: grouped and delta-debugging file reduction;
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
