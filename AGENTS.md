# PyRepro Development Instructions

## Project purpose

PyRepro is an execution-verified failure-reduction tool for Python projects.
It reduces a failing project to a smaller reproducer while preserving a stable
user-specified runtime behavior.

Its core design principle is:

> Static analysis guides reduction; execution validates it.

Static analysis may prioritize candidates, but only an execution oracle may
accept or reject a reduction.

## Source of truth

Before making non-trivial changes, inspect the documents relevant to the task:

- `docs/project-overview.md` for product goals and roadmap;
- `docs/architecture.md` for implemented responsibilities and boundaries;
- `docs/requirements/` for accepted stage requirements;
- `docs/decisions/` for architectural decisions;
- `docs/experiments/` for concise retired-experiment conclusions;
- `README.md` for user-facing behavior; and
- `CHANGELOG.md` for notable current changes.

The explicit user request or current issue defines the immediate task. Do not
infer a later roadmap stage or broaden scope from future plans alone.

## Scope discipline

Implement only functionality required by the current task, requirement, or
accepted architectural decision. Prefer simple working mechanisms over
speculative abstractions.

Do not introduce ddmin, symbol-level reduction, candidate ranking, custom
oracles, dependency reduction, execution sandboxes, web applications, LLMs,
MCP, RAG, multi-agent systems, automatic fixes, or provider frameworks unless
the current task explicitly requires them.

Do not create base classes, factories, or interfaces solely for possible future
implementations.

## Execution boundary

Running a reproduction command is an intentional product capability, not a
general permission to execute arbitrary code.

P1 accepts a developer-selected trusted local source directory and its trusted
argv command. It must:

- use `subprocess` with `shell=False`;
- run candidates only in disposable workspaces;
- preserve the original source tree unchanged;
- bound every execution with a timeout;
- avoid dependency installation and network setup; and
- reject unstable baselines and different failures.

`shell=False` prevents shell parsing; it is not a sandbox. Do not claim P1 is
safe for arbitrary third-party repositories or commands.

## Design rules

- Keep module responsibilities narrow and explicit.
- Use `pathlib` for filesystem paths.
- Treat the established failure signature as the reduction oracle.
- Do not call a greedy result globally minimal.
- Do not add static analysis to the acceptance decision without an accepted
  design change.
- Preserve useful Scanner, AST, and path-validation infrastructure until a
  concrete reduction stage integrates it.
- Avoid unrelated refactoring during feature work.

## Python style and documentation

Use common Python engineering conventions and the Google Python Style Guide as
the primary reference. Tactics2D may be a useful style reference when it fits
this project.

- Every non-trivial module needs a concise responsibility docstring.
- Public APIs document behavior, constraints, and meaningful edge cases.
- Use Google-style `Args`, `Returns`, `Raises`, and `Attributes` only when
  applicable.
- Private helpers need documentation only when their intent is non-obvious.
- Use descriptive PEP 8 names: `CapWords` classes, `snake_case` functions and
  variables, and `UPPER_CASE` constants.

## Change and validation discipline

Before a non-trivial change, identify the requirement or decision it serves,
inspect the affected code and tests, and keep the patch limited to that scope.

After relevant code changes, run:

```bash
ruff check .
ruff format --check .
pytest
```

Use feature branches and pull requests; keep `main` runnable. Before each
substantive commit, decide whether `CHANGELOG.md` needs an update. Include one
for user-visible behavior, CLI changes, CI policy, requirements, ADRs, or
stable documentation. Do not create manual code-diff Markdown files; Git and
pull requests are the source of truth for line-level history.
