# RepoSentinel V0.3 evaluation design

V0.3 evaluates the trade-offs between a direct Codex repository review and
RepoSentinel's constrained, evidence-driven review. It does not introduce a
new reviewer capability.

The primary comparison uses the same model, reasoning effort, shared review
policy, target repository, and target scope for both conditions:

```text
Direct strong Codex                RepoSentinel
-------------------                ------------
target repository as cwd           isolated temporary cwd
read-only Codex exploration        shell disabled
ordinary repository commands       five read-only MCP evidence tools
```

This is intentionally not a single-variable comparison. It compares an open,
read-only coding-agent review with a constrained evidence-driven review across
quality, efficiency, control, and auditability.

## Inputs

The runtime configuration and rendered review policy have separate inputs:

```text
repository_root  local path used by a runner or the MCP server
PROJECT_NAME     project identifier rendered in the shared review policy
TARGET_SCOPE     repository-relative directory or module to review
```

`repository_root` must never be rendered into the shared review policy. This
preserves the V0.2 boundary in which the RepoSentinel reviewer does not receive
the target repository's local path.

For example:

```text
repository_root = /work/tactics2d
PROJECT_NAME = tactics2d
TARGET_SCOPE = tactics/map/generator/road_element
```

Use `TARGET_SCOPE = .` for a whole-repository review.

## Evaluation conditions

`direct-typical` is an illustrative baseline with a minimal user request.
`direct-strong` and `reposentinel` are the formal comparison conditions.

All formal runs use:

```text
model: gpt-5.6-luna
reasoning effort: high
output: codex exec --ephemeral --json
review policy: evaluation/review-policy.md
```

The direct modes run in the supplied target repository with a read-only
sandbox. The policy forbids target-code execution, test execution, dependency
installation, and file modification. Their JSONL traces are retained for
auditing because a direct Codex run has broader command access than the
RepoSentinel condition.

The RepoSentinel mode continues to use the existing temporary working
directory, disabled shell, required local MCP server, and five-tool read-only
allowlist.

## Planned artifacts

The implementation branch will add synthetic cases, an evaluation harness, and
uncommitted run results. This design branch intentionally creates none of
those placeholders.

See `docs/requirements/requirements-v0.3-evaluation.md` for research
questions, scoring criteria, metrics, and completion criteria.
