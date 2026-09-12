# RepoSentinel V0.2 Codex reviewer feasibility spike requirements

## Objective

Validate a constrained Codex reviewer that obtains target-repository evidence
only through RepoSentinel's read-only MCP tools.

## Functional requirements

1. Invoke the local `codex exec` non-interactive interface from Python.
2. Reuse the locally authenticated ChatGPT/Codex CLI session without requiring
   an OpenAI Platform API key.
3. Run Codex in an isolated temporary directory, not in the target repository.
4. Start a required local STDIO MCP server backed by existing `RepositoryTools`.
5. Expose only `get_project_summary`, `list_tree`, `get_ast_summary`,
   `read_file`, and `search_code` through MCP.
6. Mark every MCP tool read-only and preserve existing path-boundary checks.
7. Parse Codex JSONL events, record allowed MCP calls, and reject a final
   review that used no RepoSentinel evidence tool.
8. Keep review and trace output outside the inspected repository.

## Non-functional requirements

- Default to `gpt-5.6-luna` with high reasoning effort.
- Disable shell access, web search, apps, plugins, and multi-agent tools.
- Use a read-only sandbox and never request approval during review execution.
- Treat repository content and tool results as untrusted data, never
  instructions.
- Return only final evidence-backed review content without scratch work.
- Unit-test the MCP server and Codex runner without invoking Codex.

## Explicitly out of scope

DeepSeek runtime code, OpenAI Platform API keys, RAG, embeddings, vector
databases, provider frameworks, multi-agent orchestration, automatic patches,
inspected-code execution, web UI, persistence, authentication, and model
quality evaluation beyond the sample-project feasibility run.
