# PyRepro

**Execution-verified failure reduction for Python projects.**

PyRepro turns a failing, trusted local Python project into a smaller reproducer
while preserving a user-selected runtime behavior. It uses static analysis to
find candidates, but an execution oracle is the only authority that can accept
an edit.

```text
Trusted project + reproduction command
                 │
                 ▼
      Stable three-run failure baseline
                 │
                 ▼
   Execution-verified, reversible reduction
                 │
                 ▼
       Smaller verified reproducer
```

> Static analysis guides reduction; execution validates it.

## Why PyRepro

Reducing a real repository is more than deleting a single source file. PyRepro
works from a project root and a trusted argv command, preserves a stable
failure condition, reduces across repository and source-level boundaries, then
publishes only an independently verified result.

- **Repository-oriented:** works from a Python project directory, not just a
  standalone source file.
- **Execution-verified:** every accepted edit preserves the configured
  failure condition at runtime.
- **Flexible failure conditions:** preserve a Python exception, an exit code,
  or a literal/regular-expression marker in output.
- **Two execution policies:** use Fast Mode for bounded search or Standard
  Mode for a fixed point of the current production reducer set.
- **Safe publication:** source integrity checks, disposable workspaces,
  staging verification, and atomic no-clobber output publication.
- **Inspectable results:** JSONL probe telemetry plus JSON and HTML result
  reports.

PyRepro is not a sandbox. It repeatedly runs the command that you provide.
Only use it with local code and commands that you trust.

## Quick start

Install a development checkout with the quality tools:

```bash
python -m pip install -e ".[dev]"
```

Reduce a project that reproduces a Python exception:

```bash
pyrepro reduce ./my-project \
  --expect "expected failure message" \
  --output ./reduced-project \
  -- python -m pytest tests/test_feature.py::test_failure
```

PyRepro first establishes the same baseline three times. It then performs all
candidate executions in disposable copies and leaves the source directory
unchanged. The target output directory must be new and outside the source
tree.

See the [User Guide](docs/user-guide.md) for complete commands, failure-oracle
configuration, reports, platforms, and troubleshooting.

## Failure oracles

The default `exception` oracle preserves the established exception type,
normalized message, and repository-relative traceback frame. `--expect` is an
optional anchor for that baseline.

```bash
# Preserve a specific application exit status.
pyrepro reduce ./my-project \
  --oracle exit-code --expected-exit-code 42 \
  --output ./reduced-project \
  -- python reproduce.py

# Preserve a diagnostic in stderr.
pyrepro reduce ./my-project \
  --oracle output --output-stream stderr \
  --output-match literal --output-pattern "VALIDATION_FAILED" \
  --output ./reduced-project \
  -- python reproduce.py

# Preserve a variable diagnostic with a regular expression.
pyrepro reduce ./my-project \
  --oracle output --output-stream both \
  --output-match regex --output-pattern 'ERROR\\[PAYLOAD-\\d+\\]' \
  --output ./reduced-project \
  -- python reproduce.py
```

Each oracle returns `match`, `no_match`, or `inconclusive`. Only `match` can
retain an edit. A timeout, or a missing marker in truncated selected output, is
inconclusive and therefore cannot accept a candidate.

## Fast and Standard modes

| Mode | Use it when | Search policy |
| --- | --- | --- |
| **Fast** | You need a bounded, verified result promptly. | Explicit global Oracle/time budget and per-stage limits. |
| **Standard** | You want deeper reduction under the current reducers. | No default search limit; repeat sweeps until no stage accepts an edit. |

Both target-aware modes use the same production pipeline: import pruning,
coarse and file reduction, symbols, direct methods, complete `if` statements,
container/list entries, `__main__` guards, and constrained nested palette
entries. They share candidate rediscovery, rollback, reporting, final staging
verification, and publication behavior.

### Fast Mode

Fast Mode requires a target pytest node and an explicit global Oracle budget.
The final three executions are reserved for staging verification.

```bash
pyrepro reduce ./my-project \
  --mode fast \
  --pytest-node tests/test_feature.py::test_failure \
  --max-oracle-executions 630 \
  --timeout-seconds 15 \
  --progress on \
  --json-report ./fast-report.json \
  --html-report ./fast-report.html \
  --output ./reduced-fast \
  -- python -m pytest tests/test_feature.py::test_failure
```

Fast Mode's default production stage limits are import pruning `16`, coarse
reduction `16`, complete symbols `60`, direct methods `265`, complete `if`
statements `60`, container entries `60`, list entries `60`, `__main__` guards
`8`, and nested palette entries `12`. Set an individual `--max-*-probes` value
to `0` to disable that stage.

### Standard Mode

With `--pytest-node`, Standard Mode runs the same pipeline with unbounded
stage limits by default. It restarts from the first stage after any accepted
edit and stops only after a full sweep has no accepted edit. That fixed point
is relative to the current production reducers; it is not a global-minimum
claim.

```bash
pyrepro reduce ./my-project \
  --mode standard \
  --pytest-node tests/test_feature.py::test_failure \
  --timeout-seconds 15 \
  --progress on \
  --json-report ./standard-report.json \
  --html-report ./standard-report.html \
  --output ./reduced-standard \
  -- python -m pytest tests/test_feature.py::test_failure
```

For a controlled Fast/Standard comparison, pass identical stage-enablement
settings and add `--standard-stage-policy fast-config` to Standard Mode.

## Reports and progress

Use `--probe-records PATH` for one JSONL record per candidate probe. Use
`--json-report PATH` and `--html-report PATH` for a completed-run summary.
Reports include size reduction, Oracle accounting, stage and sweep metrics,
source integrity, final verification, publication state, and the configured
oracle. The HTML report is rendered from the same structured data as the JSON
report.

On an interactive terminal, `pyrepro reduce` displays live progress. Fast Mode
shows commands started against its budget. Standard Mode shows a pulse and the
actual started-command count because there is intentionally no invented total.
Use `--progress on` or `--progress off` to override automatic display.

## Platform support

Target-aware Fast and Standard runs publish verified outputs atomically without
overwriting an existing destination on **Linux**, **WSL**, and **Windows**.
Linux and WSL use `renameat2(RENAME_NOREPLACE)`; Windows uses its native
no-replace directory rename behavior. macOS currently rejects these
target-aware publication modes before any reproduction command is run.

## Documentation

- [User Guide](docs/user-guide.md) — installation, commands, modes, oracles,
  reports, platforms, and troubleshooting.
- [Project Overview](docs/project-overview.md) — product scope and delivery
  milestones.
- [Architecture](docs/architecture.md) — module responsibilities and trust
  boundaries.
- [Report Schema](docs/report-schema.md) — JSON report fields and accounting.
- [Requirements](docs/requirements/) — accepted stage contracts.
- [Evaluation](docs/evaluation/) — benchmark protocol, validation evidence,
  and competitor applicability analysis.

## Development

```bash
ruff check .
ruff format --check .
pytest
```

Contributions should preserve the execution boundary: use `subprocess` with
`shell=False`, execute only in disposable workspaces, preserve the source tree,
and accept edits only through the configured runtime oracle.
