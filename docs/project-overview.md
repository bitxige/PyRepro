RepoSentinel 项目总览
1. 项目名称

RepoSentinel

正式课题名称可以使用：

RepoSentinel：基于静态分析与大语言模型的 Python 项目智能软件工程审查平台

如果后续 Agent 实验成功，也可以升级成：

RepoSentinel：面向 Python 项目的智能软件工程审查 Agent

2. 项目背景

RepoSentinel 来源于真实的软件工程和开源协作经历。

在参与多人维护的 Python 项目过程中，我们发现：

“代码能运行”并不意味着代码具有良好的软件工程质量。

真实项目还需要考虑模块职责、代码复杂度、命名、API 设计、文档、测试质量、项目结构、维护成本以及多人协作规范等问题。

传统静态分析工具擅长发现确定性的规则问题，例如：

syntax error
unused import
formatting
部分复杂度问题

但是很难回答：

这个函数真的需要 docstring 吗？

这个 80 行函数是真的复杂，还是逻辑本身就需要这么长？

这些 pytest assert 是在验证核心行为，
还是过度绑定了实现细节？

这个 helper 没有文档到底是不是问题？

这个类放在当前文件是否合理？

这里是真的需要抽象，
还是属于过度设计？

这些问题都需要结合整个代码仓库的上下文进行判断。

另一方面，直接把源码扔给普通 LLM，也存在问题：

模型不了解整个仓库
不知道哪些文件重要
容易机械套规范
容易给泛泛建议
难以给出可靠代码证据
大仓库无法一次性塞进上下文

因此 RepoSentinel 的核心思想是：

Static Analysis
      ↓
Objective Evidence

        +

LLM Agent
      ↓
Contextual Judgement

即：

静态分析负责“事实”，LLM 负责“判断”。

而不是：

缺 docstring → 扣 3 分
函数超过 20 行 → 扣 5 分
没有 CI → 扣 10 分

RepoSentinel 明确反对这种机械式质量评分。

3. 核心设计原则

最重要的一条：

No Evidence, No Finding.

重要 Review 结论必须尽可能提供：

文件
类 / 函数 / Symbol
行号或代码区域
具体观察证据
为什么构成工程问题
改进建议

例如不是：

“这个模块代码结构不好。”

而应该类似：

Medium Priority

File:
src/parser.py

Symbol:
load_config()

Evidence:
该函数共 124 行，同时负责文件读取、
字段校验和业务对象构造。

Reason:
多个职责集中在单一函数中，
输入格式变化可能同时影响多个逻辑阶段。

Recommendation:
考虑分离输入解析和对象构造职责。

第二条原则：

静态信号只是 Evidence，不等于 Finding。

例如：

function length = 82
docstring = False
arguments = 7

都只是客观事实。

是否真正构成问题，交给 Agent 根据上下文判断。

4. 目标用户

第一阶段只面向 Python 项目。

主要用户包括：

Python 初学者
学生开发团队
小型 Python 开源项目
希望快速获得工程 Review 的开发者

暂时不考虑：

Java
C++
JavaScript
多语言统一分析

避免项目一开始做得过大。

5. RepoSentinel 最终希望实现什么

用户提供一个 Python 仓库后：

Python Repository
        ↓
Repository Scanner
        ↓
Static Evidence
        ↓
Review Agent
        ↓
Agent 自主探索代码
        ↓
Evidence-backed Judgement
        ↓
Software Engineering Review Report

最终报告主要包括：

Project Overview

Overall Assessment

Main Strengths

High Priority Findings

Medium Priority Findings

Low Priority Findings

Architecture & Organization

Maintainability

Documentation

Testing

Evidence

Final Recommendation

最后可以给出：

Ready for merge

Merge after minor cleanup

Recommend cleanup before merge

Requires significant refactoring

但不会采用机械的：

83 / 100

这种总评分。

6. 第一版主要 Review 维度
复杂度与冗余

分析：

不必要的复杂设计
重复逻辑
过度抽象
无效封装
过多中间层
超长函数
职责混杂
过多 helper
命名与代码组织

分析：

函数 / 变量命名
模块职责
文件边界
类和函数的位置
模块耦合
目录组织
Public API Documentation

分析：

public class 是否需要 docstring
public function 是否需要文档
Args
Returns
Raises
Attributes
文档是否与实现一致

但不会规定：

每一个 private helper 都必须写 docstring。

Pytest / 测试质量

分析：

assert 是否验证关键行为
是否重复断言
是否过度绑定内部实现
是否存在脆弱测试
是否适合 parameterize
是否有重复 setup
关键模块是否缺测试
7. RepoSentinel 自身代码规范

RepoSentinel 自身比被审查仓库要求更严格。

项目代码以：

Google Python Style Guide

作为主要代码和文档规范参考。

同时参考 Tactics2D 的工程实践，包括：

module responsibility
docstring structure
testing discipline
pre-commit
PR workflow
多人协作代码规范

但不会机械复制 Tactics2D。

RepoSentinel 自身原则包括：

非平凡 module 有 module docstring

public class 有明确职责说明

public API 有必要的 Google-style docstring

Args / Returns / Raises / Attributes 按需使用

private helper 不机械补 docstring

模块职责尽量单一

避免无意义抽象

避免未来功能占位架构
8. 当前 V0.1

V0.1 定位是：

Static Evidence Layer

不是完整 AI 产品。

当前基本架构：

Repository
     ↓
RepositoryScanner
     ↓
AstAnalyzer
     ↓
RepositoryTools
     ↓
MarkdownReportGenerator
RepositoryScanner

负责：

“这个仓库里面有什么？”

包括：

文件树
Python 文件
pytest 测试文件
README
pyproject.toml
requirements
Git
GitHub Actions
pre-commit

输出仓库级事实。

AstAnalyzer

使用 Python：

ast

进行不执行源码的静态分析。

提取：

classes
functions
nested scopes
qualified names
line ranges
function length
argument count
docstring presence
imports
public-looking naming convention
syntax error
read error

并使用：

tokenize.open()

遵循 Python 源文件自身的编码声明。

RepositoryTools

这是未来提供给 Agent 的“眼睛”。

目前提供：

list_tree()

read_file(path)

search_code(keyword)

get_ast_summary(path)

get_project_summary()

其中：

get_project_summary()

只提供紧凑全局摘要。

不会把整个仓库 AST 全部塞给模型。

真正需要深入某个文件时：

Agent
 ↓
get_ast_summary(path)
 ↓
read_file(path)

实现分层探索。

MarkdownReportGenerator

负责把静态 Evidence 转成 Markdown。

V0.1 报告明确：

不进行上下文质量判断。

例如超过 20 行目前最多只是：

Static Candidate

不能直接称作：

Bad Function
9. V0.1 安全模型

RepoSentinel 把被审查仓库视为：

Untrusted Input

当前禁止：

执行目标 Python 文件
pip install 目标依赖
运行目标 pytest
执行 shell
修改目标仓库
生成 patch
把报告写入目标仓库
越界访问文件

路径层面防止：

absolute path
../ traversal
external symlink
repository root escape

而且：

Files inside an inspected repository are untrusted data, not development instructions.

以后目标仓库里即使出现：

Ignore previous instructions...

也只是被分析数据，不能成为 Agent 指令。

10. 当前 V0.1 工程状态

目前开发基线：

Python >= 3.10

项目要求 Python 3.10 或更高版本，具体版本由项目配置和 CI 环境验证。

当前已有：

pytest
ruff
pre-commit
GitHub Actions
PR template
CHANGELOG
AGENTS.md
requirements
review specification
ADR
unit tests
sample_project

测试覆盖路径安全、AST、嵌套 scope、CLI、scanner、symlink 等核心行为。

11. 当前 sample_project

examples/sample_project 是故意设计的一个小型 Python 仓库。

它不是 RepoSentinel 本身，因此不会被修成完美代码。

其中故意保留：

较长 public function
缺少 docstring 的 public function
简单 undocumented private helper
多个 assert
少量可讨论的工程问题

目的就是验证未来 Agent 能否区分：

真正值得修改的问题

和：

形式上不完美，但根本无需修改的问题。

12. V0.2 —— 最关键的技术可行性实验

下一阶段不是正式大规模开发。

而是：

Agent Feasibility Spike

分支计划：

spike/agent-feasibility

只验证一个核心问题：

DeepSeek 能否通过 RepoSentinel 已有的只读工具，自主探索一个陌生 Python 仓库，并生成有具体代码证据的软件工程 Review？

目标流程：

sample_project
      ↓
get_project_summary()
      ↓
DeepSeek
      ↓
决定下一步需要什么信息
      ↓
list_tree()
      ↓
get_ast_summary(file)
      ↓
read_file(file)
      ↓
search_code(...)
      ↓
继续探索
      ↓
形成工程判断
      ↓
review.md
13. Agent 成功标准

不是“DeepSeek 能返回文字”就叫成功。

至少需要满足：

Agent 能自主决定查看哪些文件

Agent 真正调用 RepoSentinel Tools

不把整个仓库一次性塞进上下文

能够引用具体文件 / symbol / 行号

能够发现 sample_project 中故意的问题

不会机械认为缺 docstring 就是错误

能够区分 private helper 和复杂 public API

Review 有 Evidence → Reason → Recommendation

不修改目标仓库

能够自动完成整个探索流程

如果这些基本能做到：

RepoSentinel 的核心技术路线验证成功。

14. 如果 Agent 实验失败怎么办

项目并不会废掉。

如果发现 DeepSeek：

不会正确选择工具
容易迷失
乱调用
仓库稍大就效果下降
Review 太泛

可以调整成：

Static Analyzer
      ↓
候选模块筛选
      ↓
Context Builder
      ↓
LLM Review

也就是降低 Agent 自主性。

所以 Agent 是实验变量，不是整个项目唯一生路。

15. V0.3 —— Review Agent 正式化

如果 feasibility 成功，再将 spike 整理成正式代码：

reposentinel/
├── scanner/
├── tools/
├── agent/
├── report/
└── ...

这时候才正式确定：

Agent Loop
Tool Schema
Conversation State
Evidence Pool
Review Output Schema

不会提前设计一堆：

BaseAgent
AbstractTool
ReviewStrategyFactory
16. 后续 RAG

RAG 不是现在做。

已经有 ADR 明确：

先证明 Agent Review 有价值，再判断是否需要 RAG。

未来可能收录：

Google Python Style Guide
PEP 8
软件工程规范
RepoSentinel Review Guide

流程会是：

Repository Evidence
        +
Relevant Guideline
        +
Code Context
        ↓
LLM Judgement

而不是：

Google Style
↓
机械执行所有规则

RAG 是参考知识来源，不是判决器。

17. 后续可能增加的能力

大致路线可以按照：

V0.1：Static Evidence Layer
已基本完成。仓库扫描、AST、Tools、Markdown、路径安全、测试和工程规范建立。
V0.2：Agent Feasibility Spike
DeepSeek API + 最小 Tool Calling + Agent Loop，验证陌生仓库自主探索。
V0.3：Formal Review Agent
固化 Agent 架构、Evidence Pool、结构化 Finding、Priority、Merge Readiness。
V0.4：Guideline Retrieval / RAG
仅在实验表明确有价值后加入 Google Style、PEP 等规范检索。
V0.5：更完整分析能力
例如依赖关系、调用关系、Git 历史、测试结构、复杂度候选、模块耦合等。
后期版本：UI / Sandbox / Report
可考虑 Web UI、上传 ZIP、可视化、HTML/PDF 报告；若需要动态验证，再考虑隔离 Docker 中运行 pytest。自动修改代码仍属于很后面的扩展能力。
18. 暂时明确不做的东西

现阶段不要加入：

Multi-Agent
Fine-tuning
Vector Database
LangChain 大框架
LlamaIndex
自动修复
Patch generation
任意 shell
运行目标代码
复杂数据库
登录注册
大规模 Web 前端

原则是：

先证明核心思想成立，再增加工程复杂度。

19. 项目最核心的一句话

如果老师问：

RepoSentinel 到底在做什么？

可以回答：

RepoSentinel 是一个面向 Python 项目的智能软件工程审查平台。它首先通过静态分析获取可靠的仓库级代码证据，再由大语言模型结合项目上下文进行工程判断，从而避免传统规则工具机械评分以及普通 LLM 缺乏仓库上下文的问题，并最终生成带具体代码依据和优先级的软件工程 Review 报告。

如果再压缩：

Static analysis tells us what exists; the Agent decides what actually matters.

这个就是整个项目的灵魂。
