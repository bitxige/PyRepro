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
- Added unit tests covering scanner, AST analysis, read-only tools, path safety,
  and Markdown report generation.

### Changed

- Updated the README to describe RepoSentinel's motivation, current V0.1
  capabilities, and the boundary between static evidence and future contextual
  review.
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
