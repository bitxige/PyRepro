# RepoSentinel

RepoSentinel is a read-only, evidence-oriented software engineering review
platform for Python repositories. It combines repository structure, Python AST
facts, and (in a later version) contextual LLM review to help developers find
maintainability issues with concrete code locations.

The V0.1 development baseline is Python 3.10 or newer.

## Why

Code that runs is not necessarily easy to understand, test, or maintain.
Traditional linters are useful for objective rules, but questions about module
responsibility, public API documentation, duplication, and test quality need
repository context. RepoSentinel is designed to keep static evidence separate
from those later engineering judgements.

## V0.1 status

The current version is a technical-route validation release. It can:

- scan a local Python repository without executing its code;
- inventory files and basic project metadata;
- summarize Python classes, functions, naming-convention visibility, line ranges, arguments,
  docstrings, and imports using the AST;
- expose read-only repository tools (`list_tree`, `read_file`, `search_code`,
  `get_ast_summary`, and `get_project_summary`); and
- export a Markdown static profile with source-location evidence.

Run it from a checkout with:

```bash
python -m reposentinel examples/sample_project \
  --output reports/sample-project-profile.md
```

## Architecture

See [docs/architecture.md](docs/architecture.md) for module responsibilities,
data flow, security boundaries, and the planned Agent layer.

## Roadmap

V0.2 will explore a small, provider-independent DeepSeek integration and a
read-only tool loop that lets an agent select relevant evidence before writing
a contextual review. RAG, automatic fixes, execution of inspected projects,
and a web application are intentionally out of scope for V0.1.

## Development

See [CHANGELOG.md](CHANGELOG.md) for the current development history.

```bash
python -m pip install -e ".[dev]"
ruff check .
ruff format --check .
pytest
```
