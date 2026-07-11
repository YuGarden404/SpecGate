# SpecGate Coding Agent Harness 规约

## 1. 问题陈述

SpecGate 是 AI4SE 期末项目的 A 类选题：`Coding Agent Harness`。本项目要从零实现一个小型 coding agent harness，而不是配置现成 agent 框架。

它要解决的问题是：当 LLM 只能给出“下一步想做什么”时，如何用工程机制把它包装成一个可控、可测试、可追踪、可修复的系统。

目标用户是课程评审者、学习 agent 工程的学生，以及想理解 coding agent 内核机制的开发者。项目价值不在于“让模型一次生成漂亮网页”，而在于展示 harness 层的工程能力：动作协议、工具分发、治理护栏、上下文组织、客观反馈、失败修复、日志、测试、凭据安全与分发。

MVP 领域限定为静态单页 HTML 生成与修复。SpecGate 读取目标任务目录中的 `TASK_SPEC.md` 和 `CHECKLIST.md`，让可注入的 LLM 输出严格 JSON 动作，只执行白名单文件操作，运行确定性的 HTML Gate，把失败结果反馈给下一轮，并生成静态 Web 报告。

## 1.1 两类 SPEC 的区别

本仓库中有两类“规约”，它们不是同一个东西：

- 根目录 `SPEC.md`：课程要求的项目设计文档，说明“我们要做一个什么 harness”。它是给人、评审者、后续开发 agent 看的，不是 SpecGate 运行时要修改的 HTML 任务输入。
- 目标任务目录中的 `TASK_SPEC.md`：SpecGate 运行时读取的任务输入，说明“这次要生成什么 HTML 页面”。它通常和 `CHECKLIST.md` 一起放在示例任务目录中，例如 `examples/knowledge_nav/TASK_SPEC.md`。

因此，本项目的交付物是 harness；harness 的输入是某个 HTML 任务设计。MVP demo 会提供一个静态 HTML 任务：AI for Coding 知识体导航器。

## 2. 范围

### 2.1 MVP 包含

- Python CLI harness。
- 自己实现 agent 主循环。
- 可注入的 LLM 抽象层，优先支持确定性的 `MockLLM`。
- 严格 JSON Action Protocol。
- 面向静态 HTML 任务的白名单工具分发。
- 对未知动作、shell 执行、路径越界、非法写入、非法 JSON 的 guardrail。
- 静态 HTML 的 Checklist/Gate 确定性检查。
- Gate 失败后的反馈闭环，让下一轮 agent 能根据失败信息改变动作。
- 简单 memory/context 机制：trace、stage summary、当前产物摘要、最近 Gate 结果。
- 一次运行后的静态 Web 报告。
- 基于 mock/stub LLM 的单元测试。
- Docker 分发。
- CI 中包含名为 `unit-test` 的 job。

### 2.2 MVP 不包含

- 不开放自由 shell 执行工具。
- 不做 Playwright 或浏览器自动化。
- 不做复杂前端应用。
- 不做多文件 SPA 构建流水线。
- 不使用 LangChain `AgentExecutor`、AutoGen、CrewAI、LangGraph、LlamaIndex agent runner 或宿主 coding agent loop 作为交付物核心。
- 不承诺所有真实 LLM 都能完成任务。Harness 只负责验证、重试、拦截、反馈和记录证据。

## 3. 用户故事

1. 作为课程评审者，我可以只用 `MockLLM` 运行完整闭环，从而在无网络、无真实 API key 的情况下评估机制。
2. 作为开发者，我可以用 `TASK_SPEC.md` 和 `CHECKLIST.md` 描述静态 HTML 任务，从而让 agent 基于明确规约工作。
3. 作为 harness 使用者，我可以看到不安全或不支持的动作被执行前拦截，从而确认 agent 没有越界。
4. 作为 harness 使用者，我可以看到 Gate 失败结果如何反馈到下一轮，并导致 agent 改变动作。
5. 作为开发者，我可以用一条命令运行测试，从而回归验证核心机制。
6. 作为评审者，我可以打开静态 Web 报告查看运行过程、动作、拦截、Gate 结果和最终产物。
7. 作为未来真实 LLM 用户，我可以安全配置 API key，避免密钥进入源码、日志或 Git 历史。

## 4. 领域与机制设计

### 4.1 领域

SpecGate 的 coding 领域选择为静态 HTML 生成与修复。工作区包含：

- 任务输入：`TASK_SPEC.md`、`CHECKLIST.md`、可选 starter 文件。
- 生成产物：`index.html`。
- 运行输出：trace、Gate 结果、stage summary、静态报告。

这个领域故意收窄。它足够展示 coding agent 的核心闭环：生成代码、检查代码、发现缺陷、反馈失败、修复产物；同时又避免 shell、浏览器自动化和复杂前端带来的范围膨胀。

### 4.2 工具

MVP 的 Tool Registry 只包含确定性白名单工具：

- `read_file`：读取允许范围内的文本文件。
- `write_file`：写入允许范围内的文本文件，主要是 `index.html` 和报告文件。
- `replace_file`：原子替换允许范围内的文本文件。
- `list_files`：列出允许范围内的工作区文件。
- `finish`：请求结束循环并提交最终摘要。

Gate 是 runner 内部的确定性检查步骤，不作为 LLM 可直接调用的工具开放。

MVP 明确没有 `run_command` 或 shell 工具。如果后续版本加入命令执行，必须作为单独白名单工具，并配套审批、限制和测试。

### 4.3 客观反馈信号

主要反馈信号是确定性静态 HTML Gate。它解析 `index.html` 并返回结构化结果：

- `passed`：整体是否通过。
- `checks`：每个检查项的通过/失败。
- `issues`：问题代码、严重程度、说明、证据、修复提示。
- `summary`：给下一轮 prompt 使用的简短机器可读摘要。

MVP 基础检查包括：

- `index.html` 存在。
- HTML 包含 doctype、`html`、`head`、`title`、`body`、viewport metadata。
- 页面至少包含 10 个知识节点。
- 每个节点有标题和定义。
- 节点包含关联实验或 checklist 概念。
- 页面包含搜索/过滤 UI。
- 页面脚本体现关系高亮行为。
- 布局具备移动端可读约束。
- 页面运行不依赖外部网络脚本或样式。
- 生成产物中不包含疑似密钥。

Checklist 可以补充项目特定要求，例如必须出现的文本、ID、区块或关系名称。

### 4.4 危险动作与 Guardrail

以下动作必须在代码层拦截，而不是只靠 prompt 约束：

- 未注册动作。
- 任何 shell 执行尝试。
- 访问工作区外路径。
- 写入 allowlist 外文件。
- MVP 中的二进制写入。
- 非法 JSON、缺少字段、未知 schema version、参数类型错误。
- 生成内容中出现疑似 API key 或凭据。

Guardrail 返回结构化 refusal event。该事件会写入 trace，并作为 observation 回灌给下一轮。

### 4.5 Memory / Context

MVP 不做复杂向量记忆，而是使用显式、可测试的小型 memory/context 机制：

- `trace.jsonl`：追加式运行事件。
- `memory.json`：跨会话运行摘要，保留最近几次运行的通过状态、步数和 Gate 摘要。
- 当前产物摘要：`index.html` 的结构摘要。
- 最近 Gate 结果：失败项和修复提示。
- 任务文档：当前任务的 `TASK_SPEC.md` 和 `CHECKLIST.md`。

每次 LLM 调用前，由 Context Builder 组装这些信息。每次运行结束后，由 Memory Store 更新 `memory.json`。context pack 必须有边界、可预测、可在测试中断言。

### 4.6 主要贡献维度

SpecGate 的主要贡献维度是 Checklist/Gate 反馈闭环：

1. 把任务 `TASK_SPEC.md` 和 `CHECKLIST.md` 转成确定性 Gate 期望。
2. Agent 通过 JSON 提出文件动作。
3. Harness 只执行安全动作。
4. Gate 给出失败分类和修复提示。
5. 下一轮 context 包含这些失败信息。
6. `MockLLM` 测试证明下一轮动作确实因为反馈而变化。

这符合 A 类要求：机制必须是代码，而不是一句“请模型自己检查”的提示词。

后续深化方向是 Context Eval Harness：通过一组可复现的 eval cases 比较 `baseline`、`compressed`、`injection-safe` 三类上下文策略。该机制把上下文工程从提示词经验转成可运行、可统计、可单测的 harness 代码机制。

## 5. 功能规约

### 5.1 CLI

输入：

- 命令名和参数。
- workspace path。
- 配置文件路径，默认 `specgate.toml`。
- 可选 run ID。

行为：

- 校验工作区和配置。
- 在 `runs/<run-id>/` 下创建运行目录。
- 启动 agent loop。
- 写入 trace、Gate 结果和报告。

输出：

- 控制台摘要。
- 机器可读 trace 文件。
- 静态 Web 报告。

错误处理：

- 缺少配置：清晰失败。
- 非法工作区：在任何 LLM 调用前失败。
- 缺少任务文件：以输入 Gate 错误形式失败。

### 5.2 LLM 抽象层

输入：

- context pack。
- 允许的 action schema。
- 前一轮 observation。

行为：

- `MockLLM` 返回脚本化响应，用于确定性测试和演示。
- 可选真实 LLM adapter 走同一接口。
- 所有模型输出都视为不可信输入。

输出：

- 原始模型文本。
- 如果合法，则输出解析后的 action candidate。

错误处理：

- 非法 JSON 变成 observation，并可在 `max_steps` 内重试。
- Provider 错误被记录，但不能泄露凭据。

### 5.3 Action Parser

输入：

- LLM 原始文本。

行为：

- 只接受一个严格 JSON object。
- 校验 `schema_version`、`action`、`args`。
- strict mode 下拒绝 markdown 代码块包裹的 JSON。

输出：

- typed action object，或 parse error。

错误处理：

- parse error 写入 trace，并作为下一轮 observation。

### 5.4 Tool Dispatcher

输入：

- typed action。
- workspace policy。

行为：

- 调用 guardrail。
- 分发给注册工具。
- 记录工具结果。

输出：

- 给下一轮 loop 使用的 tool observation。

错误处理：

- 被拦截动作返回 refusal observation。
- 工具失败返回结构化 failure observation。

### 5.5 Gate Engine

输入：

- artifact path。
- 配置的 checklist。

行为：

- 运行内置 HTML 检查。
- 运行 checklist 派生检查。
- 按严重程度分类问题。

输出：

- `gate_result.json`。
- 紧凑反馈摘要。

错误处理：

- 产物不存在是 Gate 失败，不是程序崩溃。

### 5.6 Report Generator

输入：

- trace events。
- Gate results。
- 最终产物摘要。

行为：

- 生成无需服务端的静态 HTML/CSS 报告。
- 如果最终产物存在，报告链接到最终 `index.html`。

输出：

- `reports/latest/index.html`。
- 可选 run-specific report。

错误处理：

- 报告生成失败必须显示在 CLI 和 trace 中。

## 6. 非功能性需求

### 6.1 性能

Mock 模式下，demo 项目应在数秒内完成。Gate 必须本地、确定、无需网络。

### 6.2 安全与凭据威胁模型

主要威胁：

- API key 被提交到 Git。
- API key 被打印到日志或报告。
- LLM 输出试图路径越界或执行 shell。
- 生成 HTML 中包含疑似密钥。
- `.env` 在共享机器上被误认为安全存储。

对策：

- MVP 默认使用 `MockLLM`，不需要凭据。
- 如启用真实 LLM，必须通过 credential manager module 读取凭据。
- 首选 OS keyring，包括 Windows Credential Manager。
- `.env` 只作为本地开发 fallback，必须进入 `.gitignore`，并说明明文风险。
- `credentials status` 不回显密钥明文。
- trace 会对疑似凭据做 redaction。
- guardrail 强制动作和路径边界。

### 6.3 可用性

CLI 命令应清晰，demo fixtures 可重复运行，失败信息应说明原因和下一步。静态报告应让评审者不用阅读原始日志也能理解一次运行。

### 6.4 可观测性

每个 loop step 至少记录：

- step number。
- context summary hash 或简短说明。
- raw LLM response path。
- parsed action 或 parse error。
- guardrail decision。
- tool observation。
- Gate result。

### 6.5 可靠性

以下情况必须停止：

- Gate 通过且 agent 调用 `finish`。
- 达到 `max_steps`。
- 出现不可恢复的配置或工作区错误。

## 7. 系统架构

```text
CLI
 |
 v
Config Loader ---- Workspace Policy
 |
 v
Agent Runner
 |       |          |             |
 |       |          |             v
 |       |          |        Trace Store
 |       |          |
 |       |          v
 |       |     Context Builder <---- Memory Store
 |       |
 |       v
 |   LLM Client
 |       |
 |       v
 |   Action Parser
 |       |
 |       v
 |   Guardrail
 |       |
 |       v
 |   Tool Dispatcher ---- File Tools
 |       |
 |       v
 |   Gate Engine
 |       |
 |       v
 |   Feedback Observation
 |
 v
Report Generator
```

核心尽量使用 Python 标准库。可选依赖只用于 OS keyring、打包等外围能力。Mock 模式核心不能依赖网络。

## 8. 数据模型

### 8.1 Action

- `schema_version`：字符串。
- `action`：字符串。
- `args`：对象。
- `reason`：可选字符串。

### 8.2 ToolResult

- `ok`：布尔值。
- `action`：字符串。
- `message`：字符串。
- `data`：对象。
- `blocked`：布尔值。

### 8.3 GateResult

- `passed`：布尔值。
- `checks`：检查项列表。
- `issues`：问题列表。
- `summary`：字符串。

### 8.4 TraceEvent

- `timestamp`：ISO-8601 字符串。
- `run_id`：字符串。
- `step`：整数。
- `event_type`：字符串。
- `payload`：已做 redaction 的对象。

### 8.5 Config

配置文件使用 `specgate.toml`，方便 Python 标准库 `tomllib` 解析：

- `workspace_root`。
- `allowed_read_paths`。
- `allowed_write_paths`。
- `max_steps`。
- `llm_provider`。
- `gate_name`。
- `report_dir`。
- `credential_source`。

## 9. 凭据与分发设计

### 9.1 凭据

Mock 模式默认不需要 key。真实 LLM 模式为可选能力，必须通过：

- `specgate credentials set <provider>`：安全保存 key。
- `specgate credentials status`：只显示是否存在 key，不打印明文。
- `specgate credentials clear <provider>`：清除 key。

如果 OS keyring 不可用，真实 LLM 模式应 fail closed，并提示用户配置方法。当前 MVP 提供 `credentials status/set/clear` 的最低 CLI，实现 `.env` 本地开发 fallback；`.env` 必须进入 `.gitignore`，命令不得回显密钥明文。

MVP 的实现边界是：`MockLLM` 模式无需凭据；真实 provider 默认只有在检测到凭据时才标记为 safe；`.env` fallback 用于演示安全录入、查看状态和清除流程，不代表生产级密钥库。

### 9.2 分发

分发形态选择 Docker：

- `Dockerfile` 构建可运行 CLI 镜像。
- README 写清 `docker build` 和 `docker run`。
- Mock demo 无需凭据即可运行。
- 真实 LLM 模式说明目标机器上如何安全配置凭据。

### 9.3 WebUI URL

WebUI 是静态报告站点。最终提交时通过 GitHub Pages 或 GitLab Pages 发布一次运行报告，并在 README 提供 URL。这样满足“可访问 WebUI 接口”要求，同时不把项目变成复杂 Web 应用。

## 10. 技术选型

- 语言：Python。理由是 CLI、测试、文件处理、CI 和 Docker 都简单直接。
- 测试：`unittest` 或 `pytest`，最终在 `PLAN.md` 中选定，并保持一条命令可运行。
- 配置：TOML，通过 Python `tomllib`。
- HTML Gate：Python 标准库解析和确定性字符串/结构检查。
- LLM：先实现 `MockLLM`，真实 adapter 后置。
- 报告：Python 生成静态 HTML。
- 分发：Docker。
- 部署：GitHub Pages 或 GitLab Pages 展示静态报告。

## 11. 验收标准

MVP 完成时必须满足：

- 最终提交前存在 `SPEC.md`、`PLAN.md`、`SPEC_PROCESS.md`、`README.md`、`AGENT_LOG.md`、`REFLECTION.md`。
- 交付的 harness core 包含自实现 main loop、LLM abstraction、action parser、guardrail、tool dispatcher、gate engine、memory/context builder、config loader、report generator。
- mock 模式单元测试在无网络、无真实 LLM 下验证核心机制。
- 机制演示能确定性复现：
  - 危险动作被 guardrail 拦截。
  - Gate 失败反馈给 agent 后，下一步动作发生变化。
  - Checklist/Gate 主贡献机制的确定性行为。
- 测试可以一条命令运行。
- `.gitlab-ci.yml` 包含名为 `unit-test` 的 job。
- CI 支持 Docker 分发路径。
- README 说明安装、运行、Docker 分发、凭据安全、已知限制、静态 Web 报告 URL。
- 源码、配置、日志、报告和 Git 历史中不能出现真实凭据。

## 12. 风险与决策

- 风险：项目变成通用 coding agent。决策：MVP 只做静态单页 HTML。
- 风险：WebUI 变成复杂前端。决策：WebUI 只做静态运行报告。
- 风险：安全只停留在 prompt。决策：guardrail 必须是可单测的确定性代码。
- 风险：反馈闭环描述模糊。决策：Gate result 必须结构化，并进入下一轮 context pack。
- 风险：真实 LLM 不稳定掩盖机制。决策：`MockLLM` 是主要 demo 和测试路径。
- 风险：课程过程证据不足。决策：从项目开始维护 `SPEC_PROCESS.md` 和 `AGENT_LOG.md`。
# 2026-07-10 Context Harness Deepening 补充规格

本节记录 SpecGate 在 MVP、真实 LLM 兼容、Context Eval、治理指标和 HITL Review Gate 之后的下一阶段主贡献。该阶段不改变 SpecGate 作为自研 Coding Agent Harness 的定位，而是在已有 harness 内核上继续深入 Context Engineering 与 Harness Engineering。

## 深化目标

新的主线命名为 `Context Harness Deepening`。它按四个阶段推进：

1. Select / RAG Harness：实现本地轻量检索、切片、打分和上下文注入。
2. Explainable Select：记录每个检索片段的来源、分数、命中词、行号和选择原因。
3. Compress Lifecycle：实现上下文压缩、tool-result clearing、关键约束置尾和超预算裁剪。
4. Isolate + Benchmark：实现 planner / implementer / reviewer 的 stub role 隔离，并用固定 mock cases 比较 harness strategy。

## 验收边界

本阶段所有核心机制都必须能在 mock/stub LLM 下确定性验证。真实 LLM 只作为可选人工实验，不作为核心通过标准。原因是课程要求关注自研 harness 机制：移除真实 LLM 后，检索、压缩、隔离、治理和 benchmark 仍应能通过单元测试证明其行为。

## 新增机制

- Select：从 workspace 中允许读取的文本文件构建轻量 lexical index，按任务、checklist 和最新 Gate feedback 检索相关片段。
- Explainability：为 retrieved chunk 记录 `path`、`start_line`、`end_line`、`score`、`matched_terms`、`reason` 和 `token_estimate`。
- Compress：清理大体积 tool result，摘要长 trace，保留 task constraints、policy boundary 和 latest gate feedback。
- Isolate：不同 role 只能看到对应 context view 和 state keys；role 不得绕过 WorkspacePolicy、snapshot guardrail 或 HITL。
- Benchmark：在固定 eval cases 上比较 `baseline`、`rag-select`、`compressed-rag`、`isolated-harness` 等策略的通过率、上下文规模、检索命中、压缩比例和治理指标。

完整设计见 `docs/superpowers/specs/2026-07-10-context-harness-deepening-design.md`。

## Task 7 Mock Eval Cases 与文档补充

本阶段新增三个固定 mock eval case，用来展示 Context Harness Deepening 不是只存在于单元测试中，而是可以通过 CLI 复现并留下 evidence：

- `retrieval-context-select`：展示 `rag-select` 对任务相关说明文档的检索，并在 evidence 中记录来源、行号、命中词和选择原因。
- `context-compression-lifecycle`：展示 `compressed-rag` 在大工具结果出现后的压缩证据，并保留关键约束。
- `isolation-role-boundary`：展示 `isolated-harness` 的 planner / implementer / reviewer 角色隔离证据，同时不改变既有权限执行路径。

这些 case 均使用 MockLLM / StubLLM，真实 LLM 仍然只作为后续可选人工实验，不作为核心验收条件。
