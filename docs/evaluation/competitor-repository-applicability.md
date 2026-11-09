# Repository-Level Competitor Applicability

## Scope

PyRepro's primary evaluation unit is a trusted local Python repository plus a
developer-supplied failure command. This record separates that repository-level
claim from the supplementary single-file study. It records both successful
smoke checks and unsuccessful trials; an unfinished output is never treated as
a successful reduction.

## Perses directory checks

| Trial | Result | Evidence and interpretation |
| --- | --- | --- |
| Three-file Python directory smoke | GO | Perses v2.7 accepted a directory input, created an independent output (27 to 2 Python LOC), preserved the protected input digest, and the output passed the external strict oracle 3/3. This establishes only a directory-mode smoke capability. |
| Click historical-bug working input | NO-GO | The trial used a fresh 18-file, 10,737-LOC working input and a stable strict baseline. The execution host interrupted the run before completion (about 55 seconds); Perses had created `PersesTempRoot_*` directories inside that disposable input root. Its partial 9,199-LOC output was not independently verified and is excluded from every result table. |

The Click result does **not** show that Perses lacks directory support or that
its reduction algorithm is ineffective. It shows only that this attempted
real-project run did not satisfy this study's completion and input-integrity
rules in the current environment. No further real-project Perses trials were
started for attrs or python-dateutil.

## Project-level PyRepro evidence

These completed PyRepro outcomes are reported separately from external-tool
results because all are full project inputs with their own frozen source,
adapter, environment record, and strict final verification:

| Project | Fast B final LOC | Standard final LOC |
| --- | ---: | ---: |
| Rich | 8,092 | 4,659 |
| Tactics2D | 5,355 | 3,539 |
| Click #2939 | 5,527 | 4,774 |
| attrs #1416 | 4,870 | 4,569 |
| python-dateutil #661 | 1,212 | 1,212 |

Do not compare this table numerically with the Perses Click partial output or
with the single-file external-tool results. They have different inputs and,
for Perses, no verified project-level completion.

## Current capability matrix

| Capability | PyRepro | Perses in this study | ShrinkRay in this study | AutoDD in this study |
| --- | --- | --- | --- | --- |
| Strict external 3/3 output check | Verified | Verified for smoke/single file | Verified for single file | Verified for single file post-check |
| Multi-file directory smoke | Verified on project workflows | Verified on one smoke fixture | Not evaluated | Not evaluated |
| Completed real-project trial | Verified on five projects | No valid result under this protocol | Not evaluated | Not evaluated |
| Single-file Python fixture result | Verified | Verified | Verified | Verified |
| Fast/Standard budget policy | Verified | Not applicable to this study | Not applicable to this study | Not applicable to this study |

“Not evaluated” must not be read as “unsupported.”
