# P1 trusted-local command reduction requirements

## Objective

Turn the P0 fixture-only spike into a trusted-local tool that can reduce a
developer-selected Python project while preserving a stable uncaught Python
failure.

## Command interface

P1 supports:

```bash
pyrepro reduce <source> [--expect TEXT] [--output PATH] -- <argv...>
```

- `<source>` must be an existing local directory selected by the developer.
- `<argv...>` is a non-empty reproduction command passed to `subprocess` with
  `shell=False`.
- `--expect` is optional normalized substring text that must occur in the
  stable baseline failure signature.
- Without `--output`, the result is placed at
  `<source-parent>/.pyrepro-output/<source-name>`.
- An output path must be non-existing and outside the source directory.

## Trust and execution boundary

P1 executes the supplied command repeatedly. It must print a warning that the
developer must trust both the source project and the command.

P1 is not an execution sandbox. It must not:

- use `shell=True`;
- install dependencies;
- configure network access;
- modify the original source directory; or
- claim to safely execute arbitrary untrusted projects.

Each execution remains timeout-bounded and runs only inside a disposable copy.

## Failure oracle

The P0 Python-exception signature remains the oracle:

- exception type;
- normalized exception message; and
- final in-project traceback frame: repository-relative file and function.

The baseline must match across three runs. `--expect`, when supplied, must
match the signature before candidate deletion begins. Candidate results must
still exactly match the full baseline signature; `--expect` does not weaken
that equality requirement.

## Candidate exclusions

P1 must not consider Python files under these default directory names as
deletion candidates:

```text
.git, .pytest_cache, .venv, __pycache__, build, checkpoints, data, dist,
env, models, node_modules, output, outputs, venv
```

Excluded files remain in the disposable workspace and may still be read by the
reproduction command.

## Training smoke fixture

Add `examples/training_failure` with 15 or more project files. Running
`python train.py` must consistently produce a project-relevant shape-mismatch
`ValueError` from `reward/shaping.py::weighted_reward`.

The fixture must include unrelated Python modules and at least one Python file
under an excluded data directory. Reduction must preserve the failure chain,
remove unrelated candidates, and leave excluded data untouched.

## Explicitly out of scope

- grouped reduction or ddmin;
- static candidate ranking or AST/symbol reduction;
- custom scripts, regex-only behavior oracles, or successful-but-interesting
  behavior;
- dependency, configuration, data, or environment reduction;
- Docker or another execution sandbox; and
- LLM, agent, MCP, UI, or automatic patch features.
