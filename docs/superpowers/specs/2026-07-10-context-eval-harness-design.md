# Context Eval Harness 设计文档

## 1. 背景

SpecGate 当前已经具备一个可运行的 Coding Agent Harness：它能读取静态 HTML 任务目录，组装上下文，调用 MockLLM 或真实 OpenAI-compatible LLM，解析 JSON Action，通过工具白名单修改文件，运行 HTML Gate，并把失败反馈回下一轮。

下一阶段不再继续横向堆功能，而是围绕课程 A 类 Harness 的要求，选择“上下文工程 + 可评估 harness”作为主要深入方向。目标是证明：同一个模型和同一批 HTML 任务，在不同上下文策略下，成功率、安全性、反馈修复能力和上下文预算表现会发生可观察差异。

## 2. 研究问题

本阶段回答一个核心问题：

> 同一个 LLM、同一批静态 HTML coding 任务，在 baseline、compressed、injection-safe 等不同 context strategy 下，完成质量、安全拦截和修复效率是否不同？

这个问题同时对齐两个课程要求：

- Context Engineering：上下文选择、压缩、注入边界、记忆注入都必须由代码机制实现，而不是只写提示词。
- Harness Engineering：不只展示一次成功运行，还要提供可复现的评估入口、指标和机制测试。

## 3. 范围

### 3.1 本阶段包含

- 新增批量评估入口 `eval`，用于运行多个 HTML 任务 case。
- 新增评估用例目录 `examples/eval_cases/`。
- 新增结构化评估结果，记录每个 case 的通过状态、步数、拦截、解析失败、Gate 失败和上下文大小。
- 新增 context strategy 机制，至少支持：
  - `baseline`：当前上下文组织方式。
  - `compressed`：压缩历史工具结果和重复反馈。
  - `injection-safe`：把任务文档、checklist、HTML 等用户内容显式标记为不可信数据区。
- 为 context strategy 和 eval runner 编写 mock/stub LLM 驱动的确定性测试。

### 3.2 本阶段不包含

- 不引入复杂向量数据库。
- 不开放 shell 工具。
- 不实现浏览器自动化或 Playwright。
- 不把真实 LLM 成功率作为唯一验收标准。
- 不依赖网络 API 完成单元测试。

真实 LLM 可以作为人工演示增强项，但核心评价仍以 mock/stub LLM 的确定性测试为准。

## 4. 设计方案

### 4.1 Eval Case

每个 eval case 是一个独立目录，结构与普通 SpecGate 任务目录一致：

```text
examples/eval_cases/<case-name>/
  TASK_SPEC.md
  CHECKLIST.md
  index.html
  specgate.toml
  case.json
```

`case.json` 保存评估元数据：

```json
{
  "id": "create-study-dashboard",
  "title": "从空白生成 AI 学习计划看板",
  "category": "generation",
  "expected": {
    "should_pass": true,
    "must_block": false
  }
}
```

首批 case 建议包含：

- `create-study-dashboard`：从简陋 starter 生成完整页面。
- `repair-checklist-failure`：初始 HTML 缺少 checklist 关键项，要求反馈后修复。
- `modify-existing-page`：在已有页面基础上添加新模块。
- `prompt-injection-write-env`：任务文档中包含越权指令，诱导写 `.env`。
- `path-escape-write`：诱导写入工作区外路径。
- `large-context-budget`：加入大段无关文本，测试压缩策略和上下文预算。

### 4.2 Eval Runner

新增 `specgate.eval_runner` 模块，职责是：

1. 发现 eval case。
2. 为每个 case 创建临时运行副本，避免污染原始样例。
3. 按指定 context strategy 启动 `AgentRunner`。
4. 读取 trace 和 Gate 结果。
5. 汇总为 `EvalCaseResult` 和 `EvalSuiteResult`。

核心数据结构：

```python
@dataclass(frozen=True)
class EvalCaseResult:
    case_id: str
    strategy: str
    passed: bool
    expected_passed: bool | None
    steps: int
    parse_errors: int
    blocked_actions: int
    gate_failures: int
    context_chars_max: int
    final_summary: str


@dataclass(frozen=True)
class EvalSuiteResult:
    strategy: str
    total_cases: int
    passed_cases: int
    expected_matches: int
    results: list[EvalCaseResult]
```

### 4.3 Context Strategy

当前 `build_context_pack` 会把任务文档、memory、工具列表、运行反馈和 Gate 摘要组装给 LLM。下一阶段将增加一个明确的 strategy 参数：

```python
build_context_pack(
    root,
    latest_gate,
    runtime_feedback,
    strategy="baseline",
)
```

三种策略的行为：

- `baseline`：保持现有格式，作为对照组。
- `compressed`：对历史工具结果做摘要，只保留最近一次关键失败、拦截原因和 Gate 修复提示；大段 HTML 内容只保留结构摘要。
- `injection-safe`：在 `compressed` 的基础上，把任务输入包在显式边界中，并声明这些内容是数据，不是可执行指令。

示例边界：

```xml
<untrusted_data name="TASK_SPEC.md">
...
</untrusted_data>
```

这不是把安全寄托在提示词上。真正的安全仍由 `WorkspacePolicy`、工具白名单、snapshot 和 Gate 负责；边界的作用是降低模型误读数据区指令的概率，并让 trace 能显示上下文组织策略。

### 4.4 指标

Eval 输出至少包含以下指标：

- `passed`：最终 Gate 是否通过。
- `steps`：AgentRunner 实际步数。
- `parse_errors`：JSON Action 解析失败次数。
- `blocked_actions`：被 policy/tool guardrail 拦截的动作次数。
- `gate_failures`：Gate 失败反馈次数。
- `context_chars_max`：本 case 最大上下文字符数估算。
- `expected_match`：结果是否符合 case.json 的预期。

后续可以扩展 token 估算、latency、工具成功率、retry 次数，但本阶段先保持标准库实现。

### 4.5 CLI

新增命令：

```powershell
python -m specgate.cli eval examples/eval_cases --context-strategy baseline
python -m specgate.cli eval examples/eval_cases --context-strategy compressed
python -m specgate.cli eval examples/eval_cases --context-strategy injection-safe
```

默认使用 MockLLM 或 stub LLM，因此无需 API key。真实 LLM 评估可以作为可选参数后续扩展，不作为第一批实现的硬目标。

输出：

- 控制台摘要。
- `eval-runs/latest/results.json`。
- 可选静态 HTML 汇总报告，若工作量超出本阶段，则推迟到后续 task。

### 4.6 测试策略

本阶段继续遵守 TDD。关键测试包括：

- `test_context_strategy.py`
  - baseline 保持当前上下文关键内容。
  - compressed 会清理冗长工具结果，但保留 Gate 修复提示。
  - injection-safe 会把任务文档放入不可信数据边界。

- `test_eval_runner.py`
  - 能发现 case。
  - 能在临时副本运行 case，不污染原目录。
  - 能统计 parse error、blocked action、gate failure。
  - 能生成 suite summary。

- `test_cli.py`
  - `eval` 命令能运行 mock case。
  - 非法 context strategy 会清晰失败。

- `test_injection_cases.py`
  - prompt injection case 诱导写 `.env` 时，必须被 policy 拦截。
  - path escape case 诱导写工作区外文件时，必须被拦截。

所有测试不依赖真实 LLM、不依赖网络。

## 5. 数据流

```text
eval CLI
  -> discover eval cases
  -> copy case to temp workspace
  -> load case specgate.toml
  -> AgentRunner(context_strategy=...)
  -> build_context_pack(strategy=...)
  -> MockLLM / real LLM
  -> parse action
  -> WorkspacePolicy + ToolDispatcher
  -> HTML Gate
  -> trace
  -> EvalRunner summarize trace + final gate
  -> results.json
```

## 6. 风险与边界

- 真实 LLM 输出不可控，所以不能把真实 LLM 成功率作为唯一验收。
- `injection-safe` 边界不能替代 policy；必须继续依靠代码层拦截。
- `compressed` 不能压掉关键 checklist、Gate 修复提示或安全规则。
- eval case 不能过多，否则会让课程项目变成样例堆砌；首批控制在 5-6 个。
- 当前项目不开放 shell，因此 HE 的 lint/LSP/CI 反馈仍不纳入本阶段。

## 7. 验收标准

- 新增 `eval` 命令可运行首批 eval cases。
- 三种 context strategy 都有确定性测试。
- eval 结果能输出机器可读 JSON。
- prompt injection 和路径越权 case 在 mock/stub LLM 下能稳定复现拦截。
- compressed strategy 能降低上下文冗余，同时保留关键修复信息。
- 全量单元测试通过。

## 8. 预期贡献表述

本阶段完成后，SpecGate 的主要贡献可以从“静态 HTML Gate 反馈闭环”升级为：

> SpecGate 是一个可观测、可约束、可评估的静态 HTML Coding Agent Harness。它通过 eval cases 和 context strategy，把 Context Engineering 从提示词经验变成可运行、可比较、可测试的 harness 机制。

