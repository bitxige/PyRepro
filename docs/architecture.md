# RepoSentinel Architecture

## Overview

RepoSentinel separates repository evidence collection from contextual
software-engineering judgement.

The V0.1 architecture is:

```text
Target Python Repository
        |
        v
RepositoryScanner
        |
        +------> file-level repository facts
        |
        v
AstAnalyzer
        |
        +------> syntax-level Python facts
        |
        v
RepositoryTools
        |
        +------> safe read-only interface
        |
        v
MarkdownReportGenerator
        |
        +------> static evidence report
```

V0.1 does not perform LLM-based engineering judgement. Its purpose is to
provide reliable evidence for later Agent-based review.

## Package structure

```text
reposentinel/
├── __init__.py
├── __main__.py
├── cli.py
├── path_utils.py
├── scanner/
│   ├── repository_scanner.py
│   └── ast_analyzer.py
├── tools/
│   └── repository_tools.py
└── report/
    └── markdown_report.py
```

## `reposentinel.cli`

### Responsibility

Provides the command-line entry point for RepoSentinel V0.1. It accepts the
target repository and report output paths, constructs `RepositoryTools`,
obtains repository and AST evidence, prevents reports from being written
inside the inspected repository, and invokes the Markdown report generator.

The CLI coordinates components; it does not contain repository-analysis logic.

## `reposentinel.path_utils`

### Responsibility

Provides shared path-boundary validation for repository inspection. Its helper
ensures requested files use repository-relative paths, remain inside the
selected root, do not escape through `..` or external symbolic links, and are
regular files.

This module is part of RepoSentinel's security boundary.

## `reposentinel.scanner.repository_scanner`

### Responsibility

Collects file-level repository facts without executing repository code.
`RepositoryScanner` discovers regular files, Python files, pytest-style test
files, and root-level project signals such as a README, `pyproject.toml`,
requirements file, Git metadata, GitHub Actions workflows, and pre-commit
configuration.

It intentionally does not inspect Python syntax or make quality judgements.

### Main output

`RepositoryProfile` contains repository-level facts such as file counts,
discovered paths, and project metadata signals.

## `reposentinel.scanner.ast_analyzer`

### Responsibility

Extracts syntax-level facts from Python files using the standard-library
`ast` module. `AstAnalyzer` never imports or executes inspected Python code.

It extracts:

- classes, functions, and methods;
- nested lexical scopes and qualified names;
- source line ranges and function argument counts;
- module, class, and function docstring presence;
- imports and naming-convention visibility; and
- syntax or source-reading errors.

Static facts are evidence, not automatic findings. For example, a function
length, missing docstring, or argument count does not independently establish
that a function is poorly designed.

## `reposentinel.tools.repository_tools`

### Responsibility

Provides the read-only interface through which callers, and a future Review
Agent, can explore repositories:

```text
list_tree()
read_file(path)
search_code(keyword)
get_ast_summary(path)
get_project_summary()
```

`get_project_summary()` intentionally returns a compact repository overview.
Detailed AST evidence is requested separately through `get_ast_summary()`, so
a future Agent can explore repositories incrementally rather than loading an
entire repository into model context.

```text
Agent
  |
  +--> get_project_summary()
  |
  +--> decide what matters
  |
  +--> get_ast_summary(file)
  |
  +--> read_file(file)
  |
  +--> search_code(...)
```

## `reposentinel.report.markdown_report`

### Responsibility

Converts static repository evidence into a deterministic Markdown profile.
The V0.1 report may present repository statistics, project signals, Python
files, AST evidence, documentation facts, test-file counts, and static review
candidates.

It must not turn static signals into contextual engineering findings. A
function exceeding the current line threshold can be listed as a candidate for
later inspection, but V0.1 does not label it as a defect.

## Data flow

A normal V0.1 execution follows this flow:

```text
User selects repository
        |
        v
RepositoryTools
        |
        +--> RepositoryScanner
        |
        +--> AstAnalyzer
        |
        v
Static evidence
        |
        v
MarkdownReportGenerator
        |
        v
Markdown profile
```

The inspected repository is never executed or modified.

## Security boundary

RepoSentinel treats inspected repositories as untrusted input. V0.1 must not:

- execute inspected Python files;
- run inspected tests or install inspected dependencies;
- execute arbitrary shell commands;
- modify inspected files;
- write CLI reports into the inspected repository; or
- follow paths or symbolic links outside the repository root.

Files in an inspected repository are data to analyze, not instructions for
RepoSentinel itself.

## Future Agent layer

After V0.1, the planned architecture adds a Review Agent above the static
evidence layer:

```text
Target Repository
       |
       v
Static Evidence Layer
       |
       v
RepositoryTools
       |
       v
Review Agent
       |
       +--> chooses tools
       +--> collects relevant evidence
       +--> evaluates repository context
       |
       v
Evidence-backed Findings
       |
       v
Review Report
```

The Review Agent will be responsible for contextual judgement. The static
analysis layer remains responsible only for reliable evidence.
