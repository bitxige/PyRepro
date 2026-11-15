# PyRepro User Guide

This guide explains how to reduce a **trusted local** Python project while
preserving a selected runtime behavior. PyRepro repeatedly executes the command
you supply. It creates disposable copies for search, but it is not a security
sandbox and must not be used with code or commands you do not trust.

## 1. Install and inspect the CLI

PyRepro requires Python 3.10 or later.

```bash
python -m pip install -e ".[dev]"
pyrepro --help
pyrepro reduce --help
```

The project does not install target-project dependencies for you. Prepare the
target environment first, then pass the interpreter and argv command that
already reproduce the behavior.

## 2. Prepare a stable reproduction

Before reduction, confirm that your command fails or emits the target behavior
reliably. PyRepro runs its baseline three times and refuses to reduce an
unstable baseline.

Use an argv command after `--`; do not put a shell command string there:

```bash
pyrepro reduce ./project \
  --output ./reduced-project \
  -- python -m pytest tests/test_example.py::test_failure
```

The output path must not exist and must be outside `./project`. If omitted,
PyRepro uses a sibling `.pyrepro-output/<project-name>` directory.

## 3. Choose a failure oracle

An oracle determines whether a candidate still exhibits the behavior you want
to preserve. Every evaluation is one of:

| Decision | Meaning | Can retain an edit? |
| --- | --- | --- |
| `match` | The target behavior is present. | Yes |
| `no_match` | The behavior is absent or changed. | No |
| `inconclusive` | Timeout or incomplete evidence. | No |

### Python exception oracle

This default oracle preserves exception type, normalized message, and the
final repository-relative traceback frame. `strict` is the normal mode;
`message` is intended for controlled comparisons.

```bash
pyrepro reduce ./project \
  --oracle exception \
  --failure-match strict \
  --expect "invalid configuration" \
  --output ./reduced-project \
  -- python -m pytest tests/test_example.py::test_failure
```

`--expect` and `--failure-match` apply only to `--oracle exception`.

### Exit-code oracle

Use this when the application signals the target condition with a specific
process exit status.

```bash
pyrepro reduce ./project \
  --oracle exit-code \
  --expected-exit-code 42 \
  --output ./reduced-project \
  -- python reproduce.py
```

Matching a generic nonzero exit status is usually too broad. Prefer a
purposeful exit code emitted by a trusted adapter or application command.

### Output-text oracle

Use an output marker when the target condition is represented by stdout or
stderr rather than a Python exception.

```bash
# Literal marker in stderr.
pyrepro reduce ./project \
  --oracle output \
  --output-stream stderr \
  --output-match literal \
  --output-pattern "VALIDATION_FAILED" \
  --output ./reduced-project \
  -- python reproduce.py

# Regular expression in either output stream.
pyrepro reduce ./project \
  --oracle output \
  --output-stream both \
  --output-match regex \
  --output-pattern 'ERROR\\[PAYLOAD-\\d+\\]' \
  --output ./reduced-project \
  -- python reproduce.py
```

For `--output-stream both`, a marker in either stream is a match. If the
selected stream was truncated and the marker was not found, PyRepro returns
`inconclusive` rather than accepting the candidate. A timeout is likewise
inconclusive.

## 4. Run a bounded Fast reduction

Fast Mode is appropriate when you need a verified result within an explicit
search budget. It requires both a pytest node and a global Oracle limit.

```bash
pyrepro reduce ./project \
  --mode fast \
  --pytest-node tests/test_example.py::test_failure \
  --max-oracle-executions 630 \
  --timeout-seconds 15 \
  --progress on \
  --probe-records ./fast-probes.jsonl \
  --json-report ./fast-report.json \
  --html-report ./fast-report.html \
  --output ./reduced-fast \
  -- python -m pytest tests/test_example.py::test_failure
```

The global limit includes baseline and final verification commands. Three
executions are reserved for the independent final verification. Fast Mode's
per-stage limits are shared across pipeline sweeps. Set a stage's
`--max-*-probes` option to `0` to disable it; positive values bound it.

## 5. Run an exhaustive Standard reduction

With a pytest node, Standard Mode uses the same pipeline but leaves search
unbounded by default. It stops after an entire pipeline sweep accepts no edit.

```bash
pyrepro reduce ./project \
  --mode standard \
  --pytest-node tests/test_example.py::test_failure \
  --timeout-seconds 15 \
  --progress on \
  --probe-records ./standard-probes.jsonl \
  --json-report ./standard-report.json \
  --html-report ./standard-report.html \
  --output ./reduced-standard \
  -- python -m pytest tests/test_example.py::test_failure
```

You may add `--max-oracle-executions` and/or `--max-time-seconds` when an
explicit upper bound is needed. A bounded Standard run that stops for a budget
is not a fixed-point result.

For a fair Fast/Standard comparison, provide the same zero/nonzero stage
settings to both commands and use:

```text
--standard-stage-policy fast-config
```

This leaves the enabled Standard stages unbounded while matching Fast Mode's
stage set.

## 6. Understand progress and outputs

On interactive terminals, Fast Mode displays started Oracle commands against
its budget. Standard Mode displays actual started-command count without a
predicted total. Use `--progress on` when output is redirected but live status
is still useful, or `--progress off` for machine-readable logs.

Successful target-aware Fast and Standard runs:

1. create a sibling staging copy of the accepted workspace;
2. execute the configured oracle there three times; and
3. publish atomically only if all three runs match.

The original source tree is checked for integrity before publication. A
candidate result is not an official reproducer until final verification and
publication succeed.

## 7. Read reports

| Artifact | Purpose |
| --- | --- |
| `--probe-records` | JSONL: one record per candidate probe, including the Oracle decision and rollback fact. |
| `--json-report` | Canonical structured summary of a completed run. |
| `--html-report` | Human-readable rendering of the same final report data. |

The report distinguishes baseline, search, reduction, and final-verification
Oracle executions. For unified pipeline runs it also records stage metrics,
sweeps, termination reason, source integrity, and publication state. See the
[report schema](report-schema.md) for exact field meanings.

## 8. Platform support

Target-aware Fast and Standard publication is supported on Linux, WSL, and
Windows. It uses a no-clobber atomic publication operation and refuses an
existing output directory. macOS currently rejects target-aware Fast and
Standard runs before executing any reproduction command. Legacy Standard use
without `--pytest-node` retains its earlier behavior.

## 9. Troubleshooting

| Problem | What to check |
| --- | --- |
| Baseline is unstable | Run the exact command manually; remove nondeterminism before reduction. |
| The result is unpublished | Read `status` and `final_verification` in the JSON report; no result is published without three matches. |
| The output path is rejected | Choose a new directory outside the source project. |
| A command times out | Increase `--timeout-seconds` only if the command is expected to take longer; timeouts never accept an edit. |
| Standard takes too long | Interrupt it, or set explicit Oracle/time limits and record that the result is bounded rather than fixed-point. |
| Output oracle does not match | Confirm the selected stream, literal versus regex mode, and escaping. |
| Pytest target is missing later in search | Ensure the reproduction command does not depend on a deleted target test, or use an external trusted adapter. |

## 10. Read-only import inspection

Inspect import-pruning candidates without executing the target command:

```bash
pyrepro analyze-imports ./project \
  --pytest-node tests/test_example.py::test_failure
```

To exercise only the bounded, execution-verified import-pruning stage, use
`prune-imports`. This does not run the complete file or source-level pipeline:

```bash
pyrepro prune-imports ./project \
  --pytest-node tests/test_example.py::test_failure \
  --max-import-probes 16 \
  -- python -m pytest tests/test_example.py::test_failure
```

For implementation boundaries and supported source shapes, see the
[architecture](architecture.md) and the accepted [requirements](requirements/).
