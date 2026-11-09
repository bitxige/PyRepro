# Competitor Technology Survey

## Scope

This survey supports the supplementary external-tool comparison. It does not
claim that every tool solves the same problem or that a result on a fixture
predicts repository-scale behavior. The primary PyRepro evaluation remains the
repository-level Rich, Tactics2D, Click, attrs, and python-dateutil trials.

| Tool | Study role | Input scope exercised here | Version |
| --- | --- | --- | --- |
| PyRepro | repository-level reference and single-file arm | Python project or one-file project | project commit `d7f485b` |
| Perses | grammar-aware external reducer | one file; directory smoke; attempted project directory | `v2.7` |
| ShrinkRay | external single-artifact reducer | one Python file | `26.9.13.0`, `--no-llm` |
| AutoDD | Python-specific supplementary reducer | one Python file | TileLang `0.1.15` |

The authoritative upstream interfaces are [Perses](https://github.com/uw-pluverse/perses),
[ShrinkRay](https://pypi.org/project/shrinkray/), and
[AutoDD](https://tilelang.com/tools/autodd.html). Versions, complete argv, and
raw logs are retained in the external experiment archive.

## Comparable and non-comparable dimensions

All tools in the single-file study receive byte-identical source input and a
15-second per-candidate command timeout. Every reported result subsequently
passes the same external strict Python-failure check three times. The strict
check requires the expected exception type and message, a traceback frame for
the candidate source file, and `trigger` as the failing function.

The tools do **not** expose identical internal accounting:

- PyRepro reports baseline, search, and final-verification Oracle executions.
- Perses reports test-script invocations.
- ShrinkRay's terminal summary reports elapsed time but not a directly
  comparable candidate-command total.
- AutoDD reports dispatched tasks. Those tasks are not asserted to be one
  process execution each, and its native acceptance condition is an error-text
  match rather than this study's complete strict signature.

Consequently, final LOC and external 3/3 verification are the comparable
primary measurements. Tool-reported query/task counts are diagnostic evidence,
not a shared Oracle-count ranking.

## Controlled tool settings

| Tool | Fixed settings |
| --- | --- |
| PyRepro Fast B | Fast B stage defaults, explicit global cap 630, strict matching |
| PyRepro Standard B | `--standard-stage-policy fast-config`, no default search cap, strict matching |
| Perses | Python3 grammar, one worker, `--global-fixpoint false`, test-script timeout 15 seconds |
| ShrinkRay | `--no-llm`, one worker, deterministic seed `20261109`, 15-second timeout |
| AutoDD | `subproc` backend, one job, 15-second timeout; result independently verified strictly |

The target program interpreter was CPython 3.10.18 for every study oracle.
Tool runtime environments are recorded separately because they need not match
the target interpreter.

## Interpretation boundary

This study does not claim that PyRepro is superior to grammar-aware or
single-file reducers on statement-level minimization. It records where each
tool can be executed under the same failure check. PyRepro's product claim is
more specific: reduce a trusted Python repository from a developer-supplied
argv command while preserving a stable failure and publishing only a staged,
strictly verified output.
