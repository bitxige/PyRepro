# RepoSentinel V0.3 review evaluation and calibration requirements

## Objective

Measure the quality, cost, control, and auditability trade-offs between a
direct Codex repository review and RepoSentinel's constrained,
evidence-driven review. V0.3 evaluates the V0.2 architecture; it does not add
new review capabilities.

## Research questions

### RQ1 — Review quality

With the same model and review policy, can RepoSentinel maintain competitive
software-engineering review quality?

### RQ2 — Evidence reliability

Does RepoSentinel reduce unsupported claims and improve the traceability from a
finding to concrete repository evidence?

### RQ3 — Engineering efficiency

What effect does constrained evidence retrieval have on runtime, token usage,
and repository-exploration cost?

### RQ4 — Control and auditability

Compared with direct Codex, does RepoSentinel provide clearer capability
boundaries, path safety, and an auditable review process?

## Shared inputs

Each evaluation run has three distinct inputs:

- `repository_root`: local repository path used only by the runner and, for
  RepoSentinel, the MCP server;
- `PROJECT_NAME`: project identifier rendered into the shared review policy;
  and
- `TARGET_SCOPE`: repository-relative review scope, using `.` for a full
  repository review.

`repository_root` must not be rendered into the shared review policy. The
policy in `evaluation/review-policy.md` is rendered identically for the formal
direct and RepoSentinel conditions.

## Evaluation conditions

| Condition | Prompt | Repository access | Purpose |
| --- | --- | --- | --- |
| `direct-typical` | Minimal review request | Target repository as Codex cwd | Illustrative baseline |
| `direct-strong` | Shared review policy | Target repository as Codex cwd | Formal direct baseline |
| `reposentinel` | Shared review policy | Existing read-only RepoSentinel MCP tools only | Formal constrained baseline |

`direct-strong` and `reposentinel` use the same target repository, target
scope, shared review policy, `gpt-5.6-luna` model, high reasoning effort, and
`codex exec --ephemeral --json` interface.

The comparison is deliberately not a claim that MCP is its only variable. It
compares open, read-only coding-agent exploration against constrained,
evidence-driven exploration.

Direct conditions use a read-only sandbox and their common policy forbids
target-code execution, test execution, dependency installation, and file
modification. The implementation must retain JSONL traces and record observed
policy violations. Direct conditions are evaluation baselines, not a new
RepoSentinel product capability, and may run only against explicitly supplied
evaluation repositories.

## Evaluation suite

The implementation must create four small synthetic Python cases:

1. `clean_project`: has no required findings and tests calibration against
   false positives.
2. `correctness_project`: contains a concrete boundary or validation defect
   that should be found with source evidence.
3. `testing_gap_project`: contains important validation behavior with a
   corresponding pytest coverage gap.
4. `misleading_signals_project`: includes static signals such as a justified
   long function or undocumented private helper that must not become automatic
   findings.

Every synthetic case must include a human-authored `expected-review.md` with
must-catch findings, acceptable secondary findings, and must-not-report
findings.

The harness must also support the external Tactics2D target without vendoring
that repository. Its intended initial scope is:

```text
PROJECT_NAME=tactics2d
TARGET_SCOPE=tactics/map/generator/road_element
```

The local Tactics2D root is supplied only at runtime through
`repository_root`.

## Measurements

Every run must save a final review, raw JSONL trace, and machine-readable
metrics. The metrics must record:

- case identifier, condition, run index, model, reasoning effort, and scope;
- wall-clock runtime using `perf_counter`;
- `input_tokens`, `cached_input_tokens`, `output_tokens`, and
  `reasoning_output_tokens` from Codex JSONL when available;
- completed MCP tool calls, completed command executions, and successful
  evidence calls;
- observed inspected files or evidence items, with unavailable values kept as
  `null` rather than estimated; and
- observed direct-mode policy violations, including target execution, test
  execution, dependency installation, and write attempts.

The initial violation classification may be human-audited from the raw trace;
it must not claim perfect automatic classification.

Human scoring must record:

- must-catch hits;
- false positives;
- evidence correctness;
- unsupported claims;
- finding relevance; and
- priority quality.

Control and auditability must be reported separately, including target-repo
cwd use, shell availability, modification capability, evidence-call trace,
finding-evidence requirement, and path-boundary enforcement.

## Repetition and reporting

Development uses one run only when necessary. Formal `direct-strong` and
`reposentinel` comparisons run three times per case. The comparison report
uses medians and min/max ranges for runtime and token metrics.

The first scoring process remains human-auditable. V0.3 must not add an
LLM-as-judge.

## Completion criteria

- The shared review policy is parameterized and used identically by the formal
  conditions.
- Four synthetic cases and their human ground truth are available.
- An external Tactics2D target can run without being copied into this project.
- Direct and RepoSentinel conditions run programmatically through Codex.
- Reviews, JSONL traces, runtime, usage, and exploration metrics are saved.
- Formal B/C runs have three repetitions per case.
- A human-auditable comparison report answers RQ1 through RQ4.

## Out of scope

V0.3 must not add RAG, embeddings, vector databases, fine-tuning, provider
frameworks, multi-agent orchestration, automatic patches, target-code
execution, web UI, persistence, authentication, or an LLM-as-judge.
