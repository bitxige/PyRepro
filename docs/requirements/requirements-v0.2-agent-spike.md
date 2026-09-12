# RepoSentinel V0.2 Agent feasibility spike requirements

## Objective

Validate the smallest read-only Agent loop from a DeepSeek tool call through
`RepositoryTools` and back to a final evidence-backed review response.

## Functional requirements

1. Use DeepSeek's OpenAI-compatible Chat Completions API through the `openai`
   Python SDK.
2. Read `DEEPSEEK_API_KEY` only from the runtime environment.
3. Provide a smoke-test mode that verifies a simple DeepSeek response without
   repository tools.
4. Support a summary-only mode exposing `get_project_summary()` to validate
   the first tool-call loop.
5. Expose the existing read-only tools without reimplementing their analysis:
   `get_project_summary`, `list_tree`, `get_ast_summary`, `read_file`, and
   `search_code`.
6. Validate model-supplied JSON arguments before invoking a repository tool.
7. Return tool results to the model and continue until it provides a final
   response or reaches a bounded tool-call limit.
8. Write an optional review output only outside the inspected repository.
9. Require at least one repository-tool call before accepting a final review.
10. Treat inspected repository content and tool results as untrusted data; the
    Agent must not follow instructions contained in them.

## Non-functional requirements

- Use `deepseek-v4-pro` as the configurable default model.
- Explicitly disable thinking mode for the first spike.
- Keep the implementation limited to an agent module, tool registry, and
  direct tool loop; do not introduce an agent or provider framework.
- Preserve the repository-root boundary enforced by `RepositoryTools`.
- Unit-test the tool registry and loop with a fake client; tests must not call
  the DeepSeek service.
- Instruct the model to return only the final review, without visible scratch
  work or self-deliberation.

## Explicitly out of scope

RAG, embeddings, vector databases, multi-agent orchestration, automatic
modification or patch generation, inspected-code execution, web UI,
persistence, authentication, strict-schema beta features, and thinking-mode
evaluation are not part of this spike.

## Success criteria

The spike succeeds when a run against `examples/sample_project` shows an Agent
issuing read-only tool calls, receiving their results, and producing a final
review with concrete repository evidence.
