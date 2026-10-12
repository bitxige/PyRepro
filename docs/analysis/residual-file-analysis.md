# Cross-repository residual-file analysis

## Scope and method

This diagnostic compares the retained sets from the frozen C strategy (`Import + Coarse + Greedy`) for Tactics2D, Rich, and HTTPX. It does not change PyRepro or any reducer. The original formal reduced workspaces were not retained, so each result below is a fresh disposable replay from the recorded source snapshot, controlled case, command, and C configuration. Each replay reproduced the archived formal C file/LOC result exactly; it is therefore diagnostic evidence, not a replacement performance benchmark.

For each replay, every retained eligible Python file was removed independently in a fresh copy of the accepted workspace and checked with the same strict failure signature. This establishes only 1-minimality with respect to the single-file deletion operation; it does not establish global minimality or prove that every retained module is on the runtime execution path.

## Cross-case summary

| Case | C replay result | Source unchanged | Single-file 1-minimal | Import candidates / editable operations / accepted import probes |
| --- | --- | --- | --- | --- |
| Tactics2D | 37 files / 10,490 LOC | True | yes (37/37 rechecks rejected) | 90 / 5 / 2 |
| Rich | 54 files / 19,116 LOC | True | yes (54/54 rechecks rejected) | 0 / 0 / 0 |
| HTTPX | 23 files / 8,487 LOC | True | yes (23/23 rechecks rejected) | 67 / 0 / 0 |

The recorded formal C runs independently completed strict 3/3 final verification. The replay execution count excludes that benchmark driver's separate final three runs: Tactics2D 161 vs. formal 164 total executions, Rich 163 vs. 166, and HTTPX 74 vs. 77.

## What the 1-minimal checks establish

All three retained sets are locally minimal under the existing one-file deletion move. Thus the residual sets are not explained by a file that Greedy simply skipped. The dominant immediate rejection class is an import/load failure, which is evidence of an import-structure constraint—not evidence by itself that the whole file's runtime implementation is required by the target failure.

## Import-pruning comparison

| Case | Static outcome | Dynamic outcome | Interpretation |
| --- | --- | --- | --- |
| Tactics2D | 90 target-aware candidates: 77 package re-exports and 13 target-test imports. Only 5 operations were locally editable; 84 candidates were skipped by the intentionally narrow source editor. | 2 import-pruning probes were accepted in formal C. | Existing pruning released meaningful file deletion, but most residual re-export candidates remain outside editor support. |
| Rich | 0 candidates, 0 editable operations. Analyzer recorded 5 `target_entry_used` and 8 `not_static_reexport` skips. | No import probe was run; the four import-stage executions are baseline/final checks. | No evidence currently supports import-surface pruning as Rich's residual bottleneck. |
| HTTPX | 67 target re-export candidates, all in `httpx/__init__.py`, all risk-marked; 0 editable operations because the associated static `__all__` is multiline. | No import probe was run; the four import-stage executions are baseline/final checks. | Candidate recall exists, but the editor cannot express the required atomic import-plus-`__all__` update. |

Tactics2D and HTTPX share one syntax limitation: their relevant package re-exports are coupled to multiline static `__all__` declarations; Tactics2D also contains multiline imports. Rich is structurally different: the current target-aware analysis does not propose a safe candidate at all.

## Controlled HTTPX feasibility evidence

A separate, disposable HTTPX-only probe replaced `httpx/__init__.py` with a minimal `Response` re-export and matching `__all__`. The strict target failure still matched. Running the existing Greedy cleanup afterwards reduced the accepted C workspace from 23 files / 8,487 LOC to 13 files / 4,301 LOC, deleting `_api.py`, `_auth.py`, `_client.py`, `_config.py`, `__version__.py`, and five transport modules. This is a feasibility result only: it is not an automated PyRepro result or a new benchmark value.

## Most supported next repository-level experiment

The strongest cross-case hypothesis is a conservative **atomic multiline static re-export operation**: edit a simple package import/re-export and its literal multiline `__all__` together, validate the batch solely through the strict Oracle, then rerun the existing file cleanup. It has direct feasibility evidence in HTTPX and candidate-shape evidence in Tactics2D. It is not supported as a Rich solution, so the next step should be a bounded two-case feasibility experiment (Tactics2D + HTTPX), followed by a held-out case before making it a general reducer feature.

This report does not recommend statement-level reduction, a repository-specific rule, or accepting any static conclusion without Oracle validation.

## Complete retained-file inventories

### Tactics2D

| 文件 | LOC | 单独删除结果 | 观察到的替代故障 | 证据分类 |
| --- | ---: | --- | --- | --- |
| `tactics2d/geometry/__init__.py` | 59 | different_failure | ImportError: cannot import name 'heading_unit' from 'tactics2d.geometry' (unknown location) | 包初始化／重导出约束 |
| `tactics2d/geometry/circle.py` | 139 | different_failure | ModuleNotFoundError: No module named 'tactics2d.geometry.circle' | 观察到的导入约束（非运行必要性证明） |
| `tactics2d/geometry/direction.py` | 81 | different_failure | ModuleNotFoundError: No module named 'tactics2d.geometry.direction' | 观察到的导入约束（非运行必要性证明） |
| `tactics2d/geometry/frenet.py` | 59 | different_failure | ModuleNotFoundError: No module named 'tactics2d.geometry.frenet' | 观察到的导入约束（非运行必要性证明） |
| `tactics2d/geometry/polyline.py` | 470 | different_failure | ModuleNotFoundError: No module named 'tactics2d.geometry.polyline' | 观察到的导入约束（非运行必要性证明） |
| `tactics2d/geometry/utils.py` | 115 | different_failure | ModuleNotFoundError: No module named 'tactics2d.geometry.utils' | 观察到的导入约束（非运行必要性证明） |
| `tactics2d/interpolator/__init__.py` | 15 | different_failure | ImportError: cannot import name 'Bezier' from 'tactics2d.interpolator' (unknown location) | 包初始化／重导出约束 |
| `tactics2d/interpolator/b_spline.py` | 57 | different_failure | ModuleNotFoundError: No module named 'tactics2d.interpolator.b_spline' | 观察到的导入约束（非运行必要性证明） |
| `tactics2d/interpolator/bezier.py` | 44 | different_failure | ModuleNotFoundError: No module named 'tactics2d.interpolator.bezier' | 观察到的导入约束（非运行必要性证明） |
| `tactics2d/interpolator/cubic_spline.py` | 84 | different_failure | ModuleNotFoundError: No module named 'tactics2d.interpolator.cubic_spline' | 观察到的导入约束（非运行必要性证明） |
| `tactics2d/interpolator/dubins.py` | 331 | different_failure | ModuleNotFoundError: No module named 'tactics2d.interpolator.dubins' | 观察到的导入约束（非运行必要性证明） |
| `tactics2d/interpolator/param_poly3.py` | 178 | different_failure | ModuleNotFoundError: No module named 'tactics2d.interpolator.param_poly3' | 观察到的导入约束（非运行必要性证明） |
| `tactics2d/interpolator/reeds_shepp.py` | 583 | different_failure | ModuleNotFoundError: No module named 'tactics2d.interpolator.reeds_shepp' | 观察到的导入约束（非运行必要性证明） |
| `tactics2d/interpolator/spiral.py` | 89 | different_failure | ModuleNotFoundError: No module named 'tactics2d.interpolator.spiral' | 观察到的导入约束（非运行必要性证明） |
| `tactics2d/map/element/__init__.py` | 26 | different_failure | ImportError: cannot import name 'Map' from 'tactics2d.map.element' (unknown location) | 包初始化／重导出约束 |
| `tactics2d/map/element/area.py` | 125 | different_failure | ModuleNotFoundError: No module named 'tactics2d.map.element.area' | 观察到的导入约束（非运行必要性证明） |
| `tactics2d/map/element/junction.py` | 117 | different_failure | ModuleNotFoundError: No module named 'tactics2d.map.element.junction' | 观察到的导入约束（非运行必要性证明） |
| `tactics2d/map/element/lane.py` | 343 | different_failure | ModuleNotFoundError: No module named 'tactics2d.map.element.lane' | 观察到的导入约束（非运行必要性证明） |
| `tactics2d/map/element/map.py` | 558 | different_failure | ModuleNotFoundError: No module named 'tactics2d.map.element.map' | 观察到的导入约束（非运行必要性证明） |
| `tactics2d/map/element/node.py` | 52 | different_failure | ModuleNotFoundError: No module named 'tactics2d.map.element.node' | 观察到的导入约束（非运行必要性证明） |
| `tactics2d/map/element/regulatory.py` | 145 | different_failure | ModuleNotFoundError: No module named 'tactics2d.map.element.regulatory' | 观察到的导入约束（非运行必要性证明） |
| `tactics2d/map/element/roadline.py` | 145 | different_failure | ModuleNotFoundError: No module named 'tactics2d.map.element.roadline' | 观察到的导入约束（非运行必要性证明） |
| `tactics2d/map/generator/road_segment/__init__.py` | 26 | different_failure | ImportError: cannot import name 'EntranceRamp' from 'tactics2d.map.generator.road_segment' (unknown location) | 包初始化／重导出约束 |
| `tactics2d/map/generator/road_segment/element_builder.py` | 537 | different_failure | ModuleNotFoundError: No module named 'tactics2d.map.generator.road_segment.element_builder' | 观察到的导入约束（非运行必要性证明） |
| `tactics2d/map/generator/road_segment/fork_merge.py` | 920 | different_failure | ModuleNotFoundError: No module named 'tactics2d.map.generator.road_segment.fork_merge' | 观察到的导入约束（非运行必要性证明） |
| `tactics2d/map/generator/road_segment/intersection.py` | 638 | different_failure | ModuleNotFoundError: No module named 'tactics2d.map.generator.road_segment.intersection' | 观察到的导入约束（非运行必要性证明） |
| `tactics2d/map/generator/road_segment/lane_adapter.py` | 338 | different_failure | ModuleNotFoundError: No module named 'tactics2d.map.generator.road_segment.lane_adapter' | 观察到的导入约束（非运行必要性证明） |
| `tactics2d/map/generator/road_segment/one_way.py` | 137 | different_failure | ModuleNotFoundError: No module named 'tactics2d.map.generator.road_segment.one_way' | 观察到的导入约束（非运行必要性证明） |
| `tactics2d/map/generator/road_segment/ramp.py` | 1057 | different_failure | ModuleNotFoundError: No module named 'tactics2d.map.generator.road_segment.ramp' | 观察到的导入约束（非运行必要性证明） |
| `tactics2d/map/generator/road_segment/reference_line.py` | 216 | different_failure | ModuleNotFoundError: No module named 'tactics2d.map.generator.road_segment.reference_line' | 观察到的导入约束（非运行必要性证明） |
| `tactics2d/map/generator/road_segment/road_segment.py` | 51 | different_failure | ModuleNotFoundError: No module named 'tactics2d.map.generator.road_segment.road_segment' | 观察到的导入约束（非运行必要性证明） |
| `tactics2d/map/generator/road_segment/roundabout.py` | 809 | different_failure | ModuleNotFoundError: No module named 'tactics2d.map.generator.road_segment.roundabout' | 观察到的导入约束（非运行必要性证明） |
| `tactics2d/map/generator/road_segment/two_way.py` | 229 | different_failure | ModuleNotFoundError: No module named 'tactics2d.map.generator.road_segment.two_way' | 目标 failure-frame 模块 |
| `tactics2d/map/generator/rules/lane_marking_config.py` | 355 | different_failure | ModuleNotFoundError: No module named 'tactics2d.map.generator.rules.lane_marking_config' | 观察到的导入约束（非运行必要性证明） |
| `tactics2d/map/generator/rules/lane_marking_rules.py` | 260 | different_failure | ModuleNotFoundError: No module named 'tactics2d.map.generator.rules.lane_marking_rules' | 观察到的导入约束（非运行必要性证明） |
| `tactics2d/map/generator/rules/module_types.py` | 156 | different_failure | ModuleNotFoundError: No module named 'tactics2d.map.generator.rules.module_types' | 观察到的导入约束（非运行必要性证明） |
| `tests/test_map_generator.py` | 946 | different_failure | FileNotFoundError: [Errno 2] No such file or directory: '/tmp/pyrepro-tactics-residual-p3ct4mfh/project/tests/test_map_generator.py' | 测试入口约束 |

单独删除复核：37/37 均为 `different_failure` （FileNotFoundError: 1; ImportError: 4; ModuleNotFoundError: 32）。所有保留文件此前也都经过了 Greedy probe。

### Rich

| 文件 | LOC | 单独删除结果 | 观察到的替代故障 | 证据分类 |
| --- | ---: | --- | --- | --- |
| `rich/__init__.py` | 177 | different_failure | ImportError: cannot import name 'get_console' from 'rich' (unknown location) | 包初始化／重导出约束 |
| `rich/_cell_widths.py` | 451 | different_failure | ModuleNotFoundError: No module named 'rich._cell_widths' | 观察到的导入约束（非运行必要性证明） |
| `rich/_emoji_codes.py` | 3610 | different_failure | ModuleNotFoundError: No module named 'rich._emoji_codes' | 观察到的导入约束（非运行必要性证明） |
| `rich/_emoji_replace.py` | 32 | different_failure | ModuleNotFoundError: No module named 'rich._emoji_replace' | 观察到的导入约束（非运行必要性证明） |
| `rich/_export_format.py` | 76 | different_failure | ModuleNotFoundError: No module named 'rich._export_format' | 观察到的导入约束（非运行必要性证明） |
| `rich/_extension.py` | 10 | different_failure | ModuleNotFoundError: No module named 'rich._extension' | 观察到的导入约束（非运行必要性证明） |
| `rich/_fileno.py` | 24 | different_failure | ModuleNotFoundError: No module named 'rich._fileno' | 观察到的导入约束（非运行必要性证明） |
| `rich/_log_render.py` | 94 | different_failure | ModuleNotFoundError: No module named 'rich._log_render' | 观察到的导入约束（非运行必要性证明） |
| `rich/_loop.py` | 43 | different_failure | ModuleNotFoundError: No module named 'rich._loop' | 观察到的导入约束（非运行必要性证明） |
| `rich/_null_file.py` | 69 | different_failure | ModuleNotFoundError: No module named 'rich._null_file' | 观察到的导入约束（非运行必要性证明） |
| `rich/_palettes.py` | 309 | different_failure | ModuleNotFoundError: No module named 'rich._palettes' | 观察到的导入约束（非运行必要性证明） |
| `rich/_pick.py` | 17 | different_failure | ModuleNotFoundError: No module named 'rich._pick' | 观察到的导入约束（非运行必要性证明） |
| `rich/_ratio.py` | 160 | different_failure | ModuleNotFoundError: No module named 'rich._ratio' | 观察到的导入约束（非运行必要性证明） |
| `rich/_stack.py` | 16 | different_failure | ModuleNotFoundError: No module named 'rich._stack' | 观察到的导入约束（非运行必要性证明） |
| `rich/_wrap.py` | 56 | different_failure | ModuleNotFoundError: No module named 'rich._wrap' | 观察到的导入约束（非运行必要性证明） |
| `rich/abc.py` | 33 | different_failure | ModuleNotFoundError: No module named 'rich.abc' | 观察到的导入约束（非运行必要性证明） |
| `rich/align.py` | 311 | different_failure | ModuleNotFoundError: No module named 'rich.align' | 观察到的导入约束（非运行必要性证明） |
| `rich/box.py` | 517 | different_failure | ModuleNotFoundError: No module named 'rich.box' | 观察到的导入约束（非运行必要性证明） |
| `rich/cells.py` | 154 | different_failure | ModuleNotFoundError: No module named 'rich.cells' | 观察到的导入约束（非运行必要性证明） |
| `rich/color.py` | 622 | different_failure | ModuleNotFoundError: No module named 'rich.color' | 观察到的导入约束（非运行必要性证明） |
| `rich/color_triplet.py` | 38 | different_failure | ModuleNotFoundError: No module named 'rich.color_triplet' | 观察到的导入约束（非运行必要性证明） |
| `rich/console.py` | 2632 | different_failure | ModuleNotFoundError: No module named 'rich.console' | 观察到的导入约束（非运行必要性证明） |
| `rich/constrain.py` | 37 | different_failure | ModuleNotFoundError: No module named 'rich.constrain' | 观察到的导入约束（非运行必要性证明） |
| `rich/containers.py` | 167 | different_failure | ModuleNotFoundError: No module named 'rich.containers' | 观察到的导入约束（非运行必要性证明） |
| `rich/control.py` | 225 | different_failure | ModuleNotFoundError: No module named 'rich.control' | 观察到的导入约束（非运行必要性证明） |
| `rich/default_styles.py` | 190 | different_failure | ModuleNotFoundError: No module named 'rich.default_styles' | 观察到的导入约束（非运行必要性证明） |
| `rich/emoji.py` | 96 | different_failure | ModuleNotFoundError: No module named 'rich.emoji' | 观察到的导入约束（非运行必要性证明） |
| `rich/errors.py` | 34 | different_failure | ImportError: cannot import name 'errors' from 'rich' (/tmp/pyrepro-rich-residual-d8qmr4uj/project/rich/__init__.py) | 观察到的导入约束（非运行必要性证明） |
| `rich/highlighter.py` | 232 | different_failure | ModuleNotFoundError: No module named 'rich.highlighter' | 观察到的导入约束（非运行必要性证明） |
| `rich/jupyter.py` | 101 | different_failure | ModuleNotFoundError: No module named 'rich.jupyter' | 观察到的导入约束（非运行必要性证明） |
| `rich/markdown.py` | 802 | different_failure | ModuleNotFoundError: No module named 'rich.markdown' | 观察到的导入约束（非运行必要性证明） |
| `rich/markup.py` | 248 | different_failure | ModuleNotFoundError: No module named 'rich.markup' | 观察到的导入约束（非运行必要性证明） |
| `rich/measure.py` | 151 | different_failure | ModuleNotFoundError: No module named 'rich.measure' | 观察到的导入约束（非运行必要性证明） |
| `rich/padding.py` | 141 | different_failure | ModuleNotFoundError: No module named 'rich.padding' | 观察到的导入约束（非运行必要性证明） |
| `rich/pager.py` | 34 | different_failure | ModuleNotFoundError: No module named 'rich.pager' | 观察到的导入约束（非运行必要性证明） |
| `rich/palette.py` | 100 | different_failure | ModuleNotFoundError: No module named 'rich.palette' | 观察到的导入约束（非运行必要性证明） |
| `rich/panel.py` | 308 | different_failure | ModuleNotFoundError: No module named 'rich.panel' | 观察到的导入约束（非运行必要性证明） |
| `rich/pretty.py` | 995 | different_failure | ModuleNotFoundError: No module named 'rich.pretty' | 观察到的导入约束（非运行必要性证明） |
| `rich/protocol.py` | 42 | different_failure | ModuleNotFoundError: No module named 'rich.protocol' | 观察到的导入约束（非运行必要性证明） |
| `rich/region.py` | 10 | different_failure | ModuleNotFoundError: No module named 'rich.region' | 观察到的导入约束（非运行必要性证明） |
| `rich/repr.py` | 149 | different_failure | ModuleNotFoundError: No module named 'rich.repr' | 观察到的导入约束（非运行必要性证明） |
| `rich/rule.py` | 130 | different_failure | ModuleNotFoundError: No module named 'rich.rule' | 观察到的导入约束（非运行必要性证明） |
| `rich/scope.py` | 86 | different_failure | ModuleNotFoundError: No module named 'rich.scope' | 观察到的导入约束（非运行必要性证明） |
| `rich/screen.py` | 54 | different_failure | ModuleNotFoundError: No module named 'rich.screen' | 观察到的导入约束（非运行必要性证明） |
| `rich/segment.py` | 739 | different_failure | ModuleNotFoundError: No module named 'rich.segment' | 观察到的导入约束（非运行必要性证明） |
| `rich/style.py` | 796 | different_failure | ModuleNotFoundError: No module named 'rich.style' | 观察到的导入约束（非运行必要性证明） |
| `rich/styled.py` | 42 | different_failure | ModuleNotFoundError: No module named 'rich.styled' | 观察到的导入约束（非运行必要性证明） |
| `rich/syntax.py` | 948 | different_failure | ModuleNotFoundError: No module named 'rich.syntax' | 观察到的导入约束（非运行必要性证明） |
| `rich/table.py` | 1002 | different_failure | ModuleNotFoundError: No module named 'rich.table' | 观察到的导入约束（非运行必要性证明） |
| `rich/terminal_theme.py` | 153 | different_failure | ModuleNotFoundError: No module named 'rich.terminal_theme' | 观察到的导入约束（非运行必要性证明） |
| `rich/text.py` | 1352 | different_failure | ModuleNotFoundError: No module named 'rich.text' | 观察到的导入约束（非运行必要性证明） |
| `rich/theme.py` | 115 | different_failure | ModuleNotFoundError: No module named 'rich.theme' | 观察到的导入约束（非运行必要性证明） |
| `rich/themes.py` | 5 | different_failure | ImportError: cannot import name 'themes' from 'rich' (/tmp/pyrepro-rich-residual-fy6gauwi/project/rich/__init__.py) | 观察到的导入约束（非运行必要性证明） |
| `tests/test_markdown.py` | 181 | different_failure | FileNotFoundError: [Errno 2] No such file or directory: '/tmp/pyrepro-rich-residual-mhtzdsvg/project/tests/test_markdown.py' | 测试入口约束 |

单独删除复核：54/54 均为 `different_failure` （FileNotFoundError: 1; ImportError: 3; ModuleNotFoundError: 50）。所有保留文件此前也都经过了 Greedy probe。

### HTTPX

| 文件 | LOC | 单独删除结果 | 观察到的替代故障 | 证据分类 |
| --- | ---: | --- | --- | --- |
| `httpx/__init__.py` | 138 | different_failure | AttributeError: module 'httpx' has no attribute 'Response' | 包初始化／重导出约束 |
| `httpx/__version__.py` | 3 | different_failure | ModuleNotFoundError: No module named 'httpx.__version__' | 观察到的导入约束（非运行必要性证明） |
| `httpx/_api.py` | 465 | different_failure | ModuleNotFoundError: No module named 'httpx._api' | 观察到的导入约束（非运行必要性证明） |
| `httpx/_auth.py` | 352 | different_failure | ModuleNotFoundError: No module named 'httpx._auth' | 观察到的导入约束（非运行必要性证明） |
| `httpx/_client.py` | 2037 | different_failure | ModuleNotFoundError: No module named 'httpx._client' | 观察到的导入约束（非运行必要性证明） |
| `httpx/_compat.py` | 41 | different_failure | ModuleNotFoundError: No module named 'httpx._compat' | 观察到的导入约束（非运行必要性证明） |
| `httpx/_config.py` | 368 | different_failure | ModuleNotFoundError: No module named 'httpx._config' | 观察到的导入约束（非运行必要性证明） |
| `httpx/_content.py` | 238 | different_failure | ModuleNotFoundError: No module named 'httpx._content' | 观察到的导入约束（非运行必要性证明） |
| `httpx/_decoders.py` | 325 | different_failure | ModuleNotFoundError: No module named 'httpx._decoders' | 观察到的导入约束（非运行必要性证明） |
| `httpx/_exceptions.py` | 349 | different_failure | ModuleNotFoundError: No module named 'httpx._exceptions' | 观察到的导入约束（非运行必要性证明） |
| `httpx/_models.py` | 1215 | different_failure | ModuleNotFoundError: No module named 'httpx._models' | 观察到的导入约束（非运行必要性证明） |
| `httpx/_multipart.py` | 269 | different_failure | ModuleNotFoundError: No module named 'httpx._multipart' | 观察到的导入约束（非运行必要性证明） |
| `httpx/_status_codes.py` | 158 | different_failure | ModuleNotFoundError: No module named 'httpx._status_codes' | 观察到的导入约束（非运行必要性证明） |
| `httpx/_transports/asgi.py` | 179 | different_failure | ModuleNotFoundError: No module named 'httpx._transports.asgi' | 观察到的导入约束（非运行必要性证明） |
| `httpx/_transports/base.py` | 82 | different_failure | ModuleNotFoundError: No module named 'httpx._transports.base' | 观察到的导入约束（非运行必要性证明） |
| `httpx/_transports/default.py` | 383 | different_failure | ModuleNotFoundError: No module named 'httpx._transports.default' | 观察到的导入约束（非运行必要性证明） |
| `httpx/_transports/mock.py` | 38 | different_failure | ModuleNotFoundError: No module named 'httpx._transports.mock' | 观察到的导入约束（非运行必要性证明） |
| `httpx/_transports/wsgi.py` | 144 | different_failure | ModuleNotFoundError: No module named 'httpx._transports.wsgi' | 观察到的导入约束（非运行必要性证明） |
| `httpx/_types.py` | 134 | different_failure | ModuleNotFoundError: No module named 'httpx._types' | 观察到的导入约束（非运行必要性证明） |
| `httpx/_urlparse.py` | 467 | different_failure | ModuleNotFoundError: No module named 'httpx._urlparse' | 观察到的导入约束（非运行必要性证明） |
| `httpx/_urls.py` | 648 | different_failure | ModuleNotFoundError: No module named 'httpx._urls' | 观察到的导入约束（非运行必要性证明） |
| `httpx/_utils.py` | 442 | different_failure | ModuleNotFoundError: No module named 'httpx._utils' | 观察到的导入约束（非运行必要性证明） |
| `tests/test_pyrepro_httpx_2998.py` | 12 | different_failure | FileNotFoundError: [Errno 2] No such file or directory: '/tmp/pyrepro-residual-probe-30jopgml/project/tests/test_pyrepro_httpx_2998.py' | 测试入口约束 |

单独删除复核：23/23 均为 `different_failure` （AttributeError: 1; FileNotFoundError: 1; ModuleNotFoundError: 21）。所有保留文件此前也都经过了 Greedy probe。

## Evidence assets

The machine-readable replays and candidate report are retained outside the PyRepro repository under `~/my_project/pyrepro-bench-results/residual-file-analysis/`:

- `tactics2d-c-residual-replay.json`
- `rich-c-residual-replay.json`
- `httpx-c-residual-replay.json`
- `import-pruning-candidate-diagnosis.json`
- `httpx-init-reexport-feasibility.json`
