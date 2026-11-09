# Competitive-Study Fixtures

This directory contains small, single-file fixtures used only for the
supplementary external-reducer study. Every tool receives the exact same input
file for a case and must preserve the same strict Python failure.

These fixtures are deliberately distinct from the sealed synthetic benchmarks:
they include a self-executing `test_trigger` function so that both PyRepro's
pytest-node targeting and external reducer test scripts can use one source
file. They do not measure repository-level reduction ability.

| Case | Input | Primary PyRepro stage | Expected failure |
| --- | --- | --- | --- |
| `method` | `single_file/method.py` | Method | `ValueError: method fixture failure` |
| `if_case` | `single_file/if_case.py` | If statement | `ValueError: if fixture failure` |
| `container` | `single_file/container.py` | Container and list entries | `ValueError: container fixture failure` |

Run a baseline three times with the target project interpreter before starting
any reducer. The strict oracle requires all of the following: exit status 1,
the expected `ValueError` text, a traceback frame for the reduced source file,
and a frame named `trigger`.

`strict_oracle.sh` accepts a candidate file path. `perses_oracle.sh` is copied
beside a Perses input file because Perses invokes its test script from the
candidate directory. Set `TARGET_PYTHON` to the interpreter that must execute
the reduced program; it defaults to `python3`.

Generated outputs, per-probe logs, and tool installations belong in the
external experiment archive, not in this repository. See
[`docs/evaluation/competitor-single-file-results.md`](../../docs/evaluation/competitor-single-file-results.md)
for the recorded study and commands.
