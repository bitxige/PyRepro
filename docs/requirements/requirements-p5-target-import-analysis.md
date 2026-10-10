# P5.2a/b target-aware import-candidate analysis requirements

## Objective

P5.2a/b narrows P5.1's repository-level import report to one explicit pytest
test-function entry. It identifies source edits that a later P5.2c batch
validator may try in a disposable workspace. This stage is read-only: it does
not execute a reproduction command, create a reduction workspace, or modify
source files.

The stage principle remains:

> Entry-aware static analysis proposes candidates; a later execution oracle
> decides whether an edit preserves the failure.

## Command interface

P5.2a/b extends the existing command with an explicit conventional pytest node:

```bash
pyrepro analyze-imports <source> --pytest-node FILE::TEST
pyrepro analyze-imports <source> --pytest-node FILE::CLASS::TEST
```

Parameterized suffixes select the same function body and may be supplied.
The command must reject module-only IDs, custom collector IDs, arbitrary
reproduction commands, absolute paths, and paths outside the repository rather
than guessing a failure entry.

## Target context

The analysis must preserve static import references used by:

- the selected test function or test method;
- statically reachable same-module helpers and fixtures named by a target
  function's direct calls or parameters;
- target and fixture decorators;
- class-definition expressions for a selected method; and
- module-level expressions that execute while Python imports the test module.

References from unrelated tests in the same module must not by themselves keep
a candidate import. This is a candidate-recall improvement, not a claim that
unrelated tests cannot influence collection or runtime behavior.

## Candidate discovery

P5.2a/b may propose:

1. A direct top-level test-module import unused by the target context.
2. A static package ``__all__`` re-export in a package reached from the target
   import surface, when the target context does not require that export.

Each static re-export candidate must carry the matching ``__all__`` line so a
later source-edit stage can update the import binding and export list as one
consistent edit.

Imports with obvious internal import-time side effects remain candidates only
with a ``side_effect_risk`` marker. The marker is not a safety exemption: a
later batch validator must report and execute-verify such candidates before it
can accept any edit. Dynamic imports, wildcard imports, dynamic or multiple
``__all__`` assignments, and unresolved imports remain conservative skips.

## Completion criteria

1. The command has no Oracle execution and does not modify the source tree.
2. Tests cover target functions in modules with unrelated tests, same-module
   fixtures, module-level context, class-method node IDs, static ``__all__``,
   and side-effect-risk metadata.
3. Flat and ``src`` repository support from P5.1 remains unchanged.
4. Candidate reports distinguish ordinary candidates from risk-marked ones and
   explain conservative skips.

## Explicitly out of scope

- extracting an entry point from an arbitrary command;
- source edits, batch validation, rollback, or candidate splitting;
- file/package deletion or reducer integration;
- changing failure-oracle behavior; and
- repository-specific paths, module names, or rules.
