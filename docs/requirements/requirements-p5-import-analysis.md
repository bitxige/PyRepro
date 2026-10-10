# P5.1 generic static import-analysis requirements

## Objective

P5.1 adds a read-only, repository-structure-neutral analysis step for future
preprocessing-first reduction. It identifies *candidates* for later
execution-verified import pruning; it does not edit source files, run a
reproduction command, or decide that an import is safe to remove.

The stage principle is:

> Static analysis proposes import candidates; a later execution oracle may
> validate a source edit.

## Command interface

P5.1 adds:

```bash
pyrepro analyze-imports <source>
```

The command accepts only an existing local repository directory. It prints a
deterministic analysis report and must not require a reproduction argv command.
It must never instantiate `CommandRunner`, execute an Oracle, create a
workspace, or modify `<source>`.

## Repository discovery

The analyzer must use repository-relative Python paths and support these
common layouts without repository-name or directory-name special cases:

- flat packages rooted at the repository root;
- projects with Python source below `src/`;
- ordinary packages with `__init__.py`; and
- namespace-style source directories without `__init__.py`.

It must report its detected layout, source roots, package modules, and
conventional pytest-style test module paths. Module resolution must be
deterministic and must treat ambiguous or unresolved internal imports as
conservative skips.

## Candidate discovery

P5.1 may propose only these source structures:

1. Direct, top-level import bindings in conventional test modules with no
   statically observed name load.
2. Direct, top-level bindings in package `__init__.py` files that behave as
   re-exports and have no statically observed consumer.

Each candidate must include its category, source path, line, bound name,
resolved imported module, optional imported name, and an explanation. These
are proposals for P5.2; P5.1 must not rewrite source text or call an Oracle.

## Conservative handling

The analyzer must report, rather than guess about, unsupported or risky cases.
It must conservatively skip at least:

- `import *`;
- dynamic imports such as `__import__` and `importlib.import_module`;
- unresolved or ambiguous internal imports;
- external imports outside the repository module index;
- package re-exports made public through static or dynamic `__all__`; and
- imports whose resolved internal module has obvious import-time side effects.

Static facts are not proof of runtime safety. Import-time registration,
reflection, custom import hooks, conditional imports, and other Python runtime
features remain outside P5.1's guarantee.

## Completion criteria

1. Analysis is deterministic and leaves the inspected source-tree digest
   unchanged.
2. Tests cover flat, `src`, package-relative, and namespace-style layouts.
3. Tests cover unused bindings, static re-exports, dynamic import, wildcard
   import, side-effect risk, unresolved imports, and syntax errors.
4. The public command reports candidates and conservative skips without
   executing a reproduction command.
5. Existing reduction CLI behavior and tests remain unchanged.

## Explicitly out of scope

- import or re-export rewriting;
- batch candidate validation, rollback, or splitting;
- file, package, or directory deletion;
- Greedy/ddmin ordering changes;
- failure-oracle changes;
- Tactics2D-specific paths or rules; and
- execution budgets or Fast Mode.
