# Supplementary Single-File Competitor Results

## Protocol

Run date: 2026-11-09. The exact inputs are committed under
[`benchmarks/competitive/`](../../benchmarks/competitive/). Each input was
first established as a strict 3/3 baseline with CPython 3.10.18. Each tool then
received a fresh copy of the same one-file input. Output was accepted for this
table only after the shared external strict oracle passed independently 3/3.
Every protected master input retained its SHA-256 digest.

| Case | Initial Python LOC | SHA-256 |
| --- | ---: | --- |
| `method` | 29 | `45a857cd6f6bf07e0b38e0db991a25fdcc735de4581241c8d99d542ef7ee2646` |
| `if_case` | 20 | `d5eebd2d37d23e2ebe7bba650c1c83b5bf75aff058a8cc7fdd15e19b19faa5fc` |
| `container` | 33 | `ba880c250d51a9349929a2df8a20b2d984548532850c46a7c2b77426cb09caac` |

Physical Python LOC is `len(source.splitlines())`, the same measurement used
for every final file in this table. This is a supplementary fixture study, not
a repository-level benchmark and not a claim of global minimality.

## Verified results

| Case | Tool/configuration | Final LOC | LOC reduction | Tool-reported search evidence | Reported elapsed time | Strict output verification |
| --- | --- | ---: | ---: | --- | --- | --- |
| `method` | PyRepro Fast B | 20 | 31.03% | 13 search; 19 total Oracle | 0.67 s | 3/3 |
|  | PyRepro Standard B | 20 | 31.03% | 13 search; 19 total Oracle | 0.67 s | 3/3 |
|  | Perses v2.7 | 4 | 86.21% | 240 test-script invocations | 9 s | 3/3 |
|  | ShrinkRay 26.9.13.0 | 3 | 89.66% | no directly comparable query count | 68.05 s | 3/3 |
|  | AutoDD 0.1.15 | 8 | 72.41% | 112 dispatched tasks | not emitted by tool log | 3/3 |
| `if_case` | PyRepro Fast B | 16 | 20.00% | 12 search; 18 total Oracle | 0.63 s | 3/3 |
|  | PyRepro Standard B | 16 | 20.00% | 12 search; 18 total Oracle | 0.64 s | 3/3 |
|  | Perses v2.7 | 3 | 85.00% | 108 test-script invocations | 5 s | 3/3 |
|  | ShrinkRay 26.9.13.0 | 2 | 90.00% | no directly comparable query count | 46.44 s | 3/3 |
|  | AutoDD 0.1.15 | 6 | 70.00% | 89 dispatched tasks | not emitted by tool log | 3/3 |
| `container` | PyRepro Fast B | 25 | 24.24% | 26 search; 32 total Oracle | 1.14 s | 3/3 |
|  | PyRepro Standard B | 25 | 24.24% | 26 search; 32 total Oracle | 1.15 s | 3/3 |
|  | Perses v2.7 | 3 | 90.91% | 131 test-script invocations | 6 s | 3/3 |
|  | ShrinkRay 26.9.13.0 | 2 | 93.94% | no directly comparable query count | 51.74 s | 3/3 |
|  | AutoDD 0.1.15 | 6 | 81.82% | 76 dispatched tasks | not emitted by tool log | 3/3 |

Fast B and Standard B produce the same output on these small deterministic
fixtures because Fast B reaches its fixed point without spending its global
cap. The result is not evidence that the two modes are equivalent on larger
repositories.

## Findings and limitations

The external single-file reducers reached substantially smaller programs on
these purpose-built fixtures. That is an expected and useful limitation: their
fine-grained grammar or source transformations are not the same as PyRepro's
current production repository pipeline. These results must not be presented as
a PyRepro win on final LOC.

Conversely, all four implementations can be evaluated under one external
strict failure contract for these cases. AutoDD's native error-text predicate
is weaker than that contract, so its reported outputs rely on the independent
strict 3/3 post-check. Counts in the table are deliberately labeled by the
tool's own terminology and must not be compared as equivalent Oracle counts.
