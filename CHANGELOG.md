# Change Log

All notable changes to RepoSentinel are documented in this file.

## [Unreleased]

### Added

- Added the initial V0.1 Python project structure with
  `pyproject.toml`, pytest, Ruff, pre-commit, and a minimal GitHub Actions CI
  workflow.
- Added `RepositoryScanner` for a deterministic, read-only inventory of
  repository files, Python files, test files, README, `pyproject.toml`,
  requirements, Git, CI, and pre-commit metadata.
- Added `AstAnalyzer` for syntax-only Python analysis, including classes,
  functions, public-looking name convention, source line ranges, function
  argument counts, docstring presence, imports, and syntax-error evidence.
- Added the first read-only repository tool surface:
  `list_tree`, `read_file`, `search_code`, `get_ast_summary`, and
  `get_project_summary`.
- Added repository-root path validation so file reads do not accept traversal,
  absolute paths, or symlinks escaping the inspected repository.
- Added `MarkdownReportGenerator` and a small CLI for exporting V0.1 static
  repository profiles with file and symbol evidence.
- Added a small `examples/sample_project` fixture with deliberate, mild review
  candidates for later contextual-review experiments.
- Added V0.1 requirements, initial review specification, contributor guidance,
  and project-level Codex development instructions.
- Added stable project-overview and V0.1 architecture documentation covering
  module responsibilities, data flow, security boundaries, and the planned
  Agent layer.
- Added the V0.2 Codex reviewer feasibility spike with a required local STDIO
  MCP server exposing only the existing read-only repository tools.
- Added Codex JSONL trace auditing, output-path protection, and a requirement
  that final reviews use at least one RepoSentinel evidence tool.
- Added Codex MCP-server and runner tests, including tool metadata, path
  boundary, restricted command, and zero-evidence regression coverage.
- Added unit tests covering scanner, AST analysis, read-only tools, path safety,
  and Markdown report generation.

### Changed

- Updated the README to describe RepoSentinel's motivation, current V0.1
  capabilities, and the boundary between static evidence and future contextual
  review.
### Changed

- Updated the README to describe RepoSentinel's motivation, current V0.1
  capabilities, and the boundary between static evidence and future contextual
  review.
- Updated the README with an entry point to the V0.1 architecture guide.
- Updated the V0.2 plan from the rejected DeepSeek experiment to the Codex
  reviewer experiment and recorded the decision history in ADRs 0003 and 0005.
- Expanded GitHub Actions validation into a dedicated lint job and pytest jobs
  for Python 3.10 and 3.12. Push validation now runs only for `main`.
- Updated CI test jobs to install the Codex optional dependency required by
  the MCP-server and reviewer tests.
- Defined the V0.3 review-evaluation design, including a shared parameterized
  review policy, direct-versus-constrained comparison conditions, research
  questions, metrics, and human-auditable scoring criteria.
- Kept the V0.1 report explicitly free of mechanical quality scores and
  contextual findings; static observations are presented as evidence for a
  future review agent.
- Kept the V0.1 report explicitly free of mechanical quality scores and
  contextual findings; static observations are presented as evidence for a
  future review agent.

### Removed

- No existing functionality was removed.

### Fixed

- No pre-existing defects were fixed; this is the initial implementation.

## Release notes template

Future released versions should include the version number and release date,
followed by the sections above. New findings should identify the affected
module or user-visible behavior and include the validation performed.
