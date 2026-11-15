# PyRepro project overview

## Purpose

PyRepro reduces a failing Python project to a smaller, execution-verified
reproducer. A user supplies a trusted local source tree and an argv
reproduction command. PyRepro works only in disposable copies and retains an
edit only when executing the command still satisfies the established failure
oracle.

```text
Project + reproduction command
             |
             v
  Establish a stable three-run baseline
             |
             v
   Propose an edit and execute the oracle
             |
             v
   Smaller, independently verified reproducer
```

The core principle is:

> Static analysis guides reduction; execution validates it.

PyRepro is not an execution sandbox. It repeatedly runs the supplied command,
so users must select code and commands they trust. It never installs
dependencies or mutates the protected source tree.

## Current product scope

The production pipeline supports greedy and grouped file reduction, optional
top-level symbol reduction, target-aware import pruning, coarse file groups,
direct class methods, complete `if` statements, constrained module containers
and lists, module-level `__main__` guards, and constrained nested palette-list
entries. AST and static analyses identify source-safe candidates; the runtime
oracle is the only acceptance authority.

Target-aware Standard and Fast modes use the same production reducer order,
workspace rules, rollback behavior, telemetry, staging verification, and
publication path:

- **Fast Mode** applies explicit global Oracle/time budgets and per-stage probe
  limits. Its default production allocation uses one shared budget across all
  enabled stages.
- **Standard Mode** has no default global or per-stage search cap. It repeats
  the complete pipeline until one full sweep accepts no edit. This is a fixed
  point for the current reducer set, not a claim of a globally smallest
  reproducer.

Both target-aware modes establish a baseline, verify a staged output three
times, and publish only after all three checks match. Publication is atomic and
no-clobber on Linux, WSL, and Windows. macOS does not currently support these
target-aware publication modes.

## Failure oracles

The default Python exception oracle preserves exception type, normalized
message, and a repository-relative traceback frame. Version 1.1 also supports
user-configured exit-code and output-text conditions:

- an exact process exit code;
- a literal or regular-expression marker in stdout, stderr, or either stream.

Every oracle returns `match`, `no_match`, or `inconclusive`. Only `match` can
retain an edit. Timeouts and absent markers in truncated selected output are
inconclusive, so incomplete evidence cannot accept a candidate. Version 1.1
does not execute user-supplied Python oracle callbacks.

## Reporting and integrity

`--probe-records` writes JSONL telemetry for individual candidate probes.
`--json-report` and `--html-report` write final reports with input and output
size, Oracle accounting, stage and sweep metrics, final verification,
publication state, and source-integrity evidence. Reports do not influence
reduction decisions.

The protected source tree is digested before and after a run. Version-control
metadata, caches, build outputs, and local environments are excluded from this
integrity digest; project data and model inputs remain covered.

## Completed delivery milestones

| Milestone | Delivered capability |
| --- | --- |
| P0–P3 | Command-driven file and top-level-symbol reduction |
| P4 | Probe telemetry and experimental dependency-aware ordering evidence |
| P5 | Read-only target import analysis and execution-verified preprocessing |
| P6 | Budgeted Fast Mode, verified publishing, and CLI delivery |
| P7 | Atomic multiline import and `__all__` pruning |
| Unified pipeline | Shared Fast/Standard production reducers and fixed-point Standard search |
| Oracle V1.1 | Exception, exit-code, and output-text failure conditions |
| Windows publication | Atomic no-clobber target-aware publication on Windows |

## Explicit non-goals

The current product does not provide:

- a general-purpose sandbox for untrusted repositories or commands;
- automatic dependency installation;
- automatic repair or patch generation;
- a claim of global minimum reduction;
- custom Python callback or third-party plugin loading for failure oracles;
- a web UI, LLM workflow, MCP integration, multi-agent system, or vector
  database.

See [README.md](../README.md) for user-facing commands,
[architecture.md](architecture.md) for component boundaries, and
[report-schema.md](report-schema.md) for report-field definitions.
