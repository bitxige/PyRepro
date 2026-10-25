# PyRepro 项目总览

## 项目目标

PyRepro 是一个面向 Python 项目运行故障的自动复现缩减工具。用户提供一个
能够稳定复现问题的命令，PyRepro 在一次性工作副本中尝试删除无关内容，并且
只有在原始故障仍被实际执行验证时才接受删除。

```text
项目 + 复现命令
       |
       v
  建立稳定故障基线
       |
       v
  删除候选内容并重新执行
       |
       v
 更小的、已验证的复现项目
```

核心原则是：

> 静态分析用于指导缩减；执行结果用于验证缩减。

## 为什么转向这个问题

项目前期探索了“静态证据 + 受限 LLM 审查”的路线。该路线证明了受限工具调用
可以运行，但没有证明它比直接使用通用编码 Agent 具有稳定的审查质量优势，且
增加了上下文锚定与运行延迟。

命令驱动的故障缩减提供了独立的产品价值：系统不依赖语言模型的主观判断，而是
通过“删减后是否仍复现同一故障”的可执行判据进行搜索。完整决策记录见
[`0007-pivot-to-failure-reduction.md`](decisions/0007-pivot-to-failure-reduction.md)。

## 当前实现与阶段演进

P1 将 P0 的最小闭环扩展到开发者明确选择的可信本地项目：

- 使用 argv 形式运行复现命令，且不使用 `shell=True`；
- 连续三次建立相同的 Python 异常签名；
- 可选 `--expect` 文本锚点，避免针对错误的 baseline 开始缩减；
- 在临时工作副本中逐个尝试删除 Python 文件；
- 跳过环境、缓存、数据、模型和生成目录中的删除候选；
- 仅在异常类型、规范化消息和关键 traceback frame 均一致时保留删除；
- 最终再次执行输出副本验证故障；以及
- 检查原 fixture 在整个过程中未被修改。

P2 在保留 greedy baseline 的同时新增 ddmin-inspired 分组缩减：每个分组 probe
都从干净的候选副本开始，随后执行单文件 cleanup 与显式 1-minimal 验证。结果记录
候选 Python 文件和 LOC、oracle executions、probe 接受/拒绝次数、删除文件数与
wall-clock 时间。P2 不宣称全局最小复现案例。

P3 在文件级缩减后的 workspace 中继续删除完整顶层 symbol：`function`、
`async function` 与 `class`。AST 只定位原始 source span（包括 decorator），
执行 oracle 决定删除是否接受。它分别记录 file/symbol phase 的执行次数和耗时，
并且不处理 methods、statements 或 symbol-level ddmin。

P5.1 增加只读的通用静态导入分析：它识别 flat / `src` 布局、常规 package、
测试模块、内部 import 和 package re-export，并输出可能在后续阶段被验证的候选与
保守跳过原因。该阶段不执行用户命令、不创建工作副本、不修改 source，也不将静态
结果视为删除许可。

P5.2a/b 在显式 pytest node ID 下将候选范围收窄到目标测试函数：它保留目标函数、
可静态发现的同模块 helper / fixture、decorator 与模块加载上下文所使用的 import，
而不让同一模块中其他测试函数的引用永久锁住候选。静态 `__all__` re-export 候选
携带需要同步更新的行号；明显 import-time side effect 的候选携带风险标记，仍必须
由后续 Oracle 验证。该阶段同样不执行命令或修改源码。

P5.2c 将上述候选转换为受限、可回滚的动态验证操作。它仅在临时工作副本中建立三次
稳定 baseline，并优先批量修改简单的顶层 import；批量失败后完整还原，并在
`--max-import-probes` 上限内二分。带风险标记的候选与普通候选分组处理，仍只能在 strict
failure oracle 确认同一故障后接受。静态 `__all__` re-export 会与对应 import 一起作为
原子编辑。P5.2c 不启动任何文件/symbol 缩减，也不针对特定仓库目录或模块写规则。

P7 已扩展该编辑器，使其可在严格 Oracle 验证下处理受限的顶层括号多行 import 和
静态多行 `__all__` 原子编辑，并在每个 probe 重新解析当前工作区源码。动态导入、复杂
赋值、通配导入、含注释的编辑区间及无法安全解析的语法仍保守跳过。

P5.3 将经验证的 import pruning、可选的通用目录粗粒度删除和既有 greedy cleanup
组合到同一 `ReductionWorkspace` 中；它复用一次 baseline 和 probe telemetry。真实
Tactics2D 对照表明，在固定受控故障案例中，该预处理优先流水线同时改善缩减质量和
执行成本；它不构成对所有 Python 仓库的性能承诺。

P6 Fast Mode 将该流水线置于一个共享的 Oracle 执行/时间预算下。未接受 probe 的
修改会回滚，已接受的 workspace 始终保留。当前 Fast Mode CLI 会把候选复制到 staging
目录，在其中完成独立 3/3 验证后，才以 Linux 原子 no-clobber 方式发布官方 reproducer。
预算停止只有在 final 3/3 已完成且发布成功时才能返回 verified 状态。

Fast Mode 可选在文件级 cleanup 后执行已有的完整顶层 symbol 缩减。该阶段默认关闭；
启用时以共享执行预算、有界 probe 数和既有严格 Oracle 运行，最终仍由 staging 3/3
验证和发布流程决定是否交付。`span-desc` 只改变候选尝试顺序，不作为删除许可。

Fast Mode 还可在顶层 symbol 阶段后选择性缩减顶层类的直接方法。该方法阶段默认关闭，
由独立的 `--max-method-probes` 限制，但与所有其他阶段共享同一 Oracle/时间预算。它
仅删除直接 `def` 或 `async def` 方法，并跳过唯一方法以避免生成空类；每次接受、拒绝和
回滚仍完全由严格 Oracle 与工作副本决定。

Fast Mode 还可在方法阶段后选择性缩减完整的普通 `if` 语句。该阶段默认关闭，由
`--max-if-statement-probes` 限制，并与所有其他阶段共享同一 Oracle/时间预算。它仅处理
顶层函数和顶层类直接方法中的源 `if` 语句；`elif` 源节点、嵌套定义、模块/类体、含注释或
分号的编辑范围保守跳过。删除会使直接父 suite 为空时才插入 `pass`。AST 结构只用于重定位
候选；每次接受、拒绝和回滚仍完全由严格 Oracle 与工作副本决定。

P1 会重复执行用户提供的命令，因此只适用于用户信任的本地代码与命令。它不承诺
通用仓库隔离、最小化全局最优解或任意命令的安全执行。

## 路线图

| 阶段 | 目标 |
| --- | --- |
| P0 | 命令驱动的 greedy 文件级缩减闭环（已完成） |
| P1 | 可信本地项目命令支持、`--expect` 与候选忽略规则（已完成） |
| P2 | 分组与 ddmin-inspired 文件缩减、oracle execution 指标与专用 benchmark（已完成） |
| P3 | 基于 AST 的 execution-verified symbol 缩减（已完成） |
| P4 | Probe telemetry（已完成）；dependency-aware ordering 保持为实验性工作，不进入当前主线 |
| P5.1 | 通用只读导入分析与候选报告（已完成） |
| P5.2a/b | 目标 pytest 入口感知的只读候选分析（已完成） |
| P5.2c | 有界批量 import candidate 的 execution-verified 验证（已完成） |
| P5.3a | Import Pruning 与 Greedy 的同 workspace 组合验证（已完成） |
| P5.3b | 通用粗粒度预缩减与流水线扩展（已完成） |
| P6 | 有预算的 Fast Mode、verified publishing 与 CLI 交付（已完成） |
| P7 | 原子多行 Import-surface Pruning（已完成） |
| P3 Fast 集成 | 可选顶层 Symbol 阶段与有界候选排序（已完成） |
| 方法级 Fast 集成 | 可选顶层类直接方法阶段、共享预算与发布验收（已完成，默认关闭） |
| 完整 if Fast 集成 | 可选完整 if 语句阶段、共享预算与发布验收（已完成，默认关闭） |

## 明确不做

当前主线不包含：

- LLM 审查 Agent、MCP 或 RAG；
- 自动生成补丁或自动修复；
- 在 P1 中安全执行任意第三方仓库；
- 自动安装依赖；
- Web UI、多 Agent 或向量数据库；以及
- 因 greedy 策略而宣称“全局最小”复现案例。
