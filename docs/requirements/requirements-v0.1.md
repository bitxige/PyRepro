# RepoSentinel V0.1 requirements

## Objective

Validate the technical route from a local Python repository to reliable,
evidence-oriented static facts and a Markdown profile.

## Functional requirements

1. Accept a local repository directory as input.
2. Scan its file tree and identify Python files, test files, README,
   `pyproject.toml`, requirements, Git metadata, CI, and pre-commit metadata.
3. Parse Python files with `ast` and report classes, functions, visibility,
   source line ranges, function argument counts, docstring presence, and
   imports. Visibility is only a naming-convention fact based on leading
   underscores; it is not language-enforced access control.
4. Provide read-only operations named `list_tree`, `read_file`, `search_code`,
   `get_ast_summary`, and `get_project_summary`.
5. Keep all inspected paths within the selected repository root.
6. Generate a Markdown report containing the project profile and evidence.
7. Never execute inspected Python code, install its dependencies, run its
   tests, or write into the inspected repository.

## Non-functional requirements

- Support Python 3.10 or newer, matching the course development environment.
- Prefer the standard library in the runtime implementation.
- Produce deterministic, repository-relative output suitable for tests.
- Keep static facts separate from contextual review conclusions.
- Provide unit tests, Ruff checks, pre-commit configuration, and minimal CI.

## Explicitly deferred

DeepSeek/API integration, Agent Loop, RAG, vector databases, embeddings,
multi-agent systems, automatic modification, patch generation, sandboxed
execution, PDF, web UI, database, and user accounts belong to later versions.
