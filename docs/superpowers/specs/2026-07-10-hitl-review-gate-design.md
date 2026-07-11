# HITL 审批门设计

## 背景

SpecGate 现在已经具备一个小型 Coding Agent Harness 的核心结构：agent 主循环、严格 JSON action、策略层、文件工具、Gate 反馈、trace 输出、eval cases、真实 LLM 兼容接口，以及治理指标层。

上一阶段的治理指标工作解决了“事后可审计”的问题。它能记录 agent 试图做什么、工具调用是否成功或被阻断，以及最终结果是 `trusted`、`warning` 还是 `failed`。下一阶段应该把治理从“事后可见”推进到“执行前生效”。

本阶段加入 Human-in-the-loop（HITL）审批门。Harness 会对 action 做风险分级：安全动作可以自动执行，硬性违规动作直接拒绝，需要人工判断的动作会暂停并写入待审批队列，而不是直接执行。

这能让 SpecGate 继续聚焦 Harness Engineering，而不是变成模型排行榜。LLM 只负责提出 action，是否允许这个 action 修改工作区，由 harness 决定。

## 产品目标

为 SpecGate 构建一个确定性的审批门，让每次运行都能回答：

1. 哪些动作足够安全，可以自动执行？
2. 哪些动作被硬性策略阻断？
3. 哪些动作需要人工审批，因此没有自动执行？
4. 人类 reviewer 在批准或拒绝动作前，需要查看哪些证据？

第一版刻意不在 agent 主循环里做交互式审批。它只负责记录 pending approval，并阻止高风险动作执行。审批后恢复执行留到后续阶段。

## 研究问题

本阶段回答一个 harness 层面的研究问题：

> 一个小型 coding-agent harness 能否用确定性代码机制，强制区分可逆动作和不可逆动作，而不依赖模型质量？

预期答案通过 MockLLM 测试证明。mock 模型可以请求安全写入、违规写入、需要审批的动作。Harness 应该稳定地产生审批决策，不依赖真实模型自己的判断能力。

## 范围

### 本阶段包含

- 确定性的 action 风险分类器。
- `review` governance profile：把需要审批的 action 转成 pending approval。
- 结构化 pending approval 数据模型。
- 在运行产物目录下持久化审批队列。
- 为审批请求写入 trace event。
- 在报告中展示 pending approvals 和 review-required actions。
- 增加 CLI 命令，用于查看某个 workspace 的待审批项。
- 使用 MockLLM 测试 safe、blocked、review 三类动作。
- 在 eval/result 字段中暴露 pending approval 数量。

### 本阶段不包含

- 不做 agent 主循环里的交互式终端询问。
- 不做审批后自动恢复执行。
- 不增加 shell 执行工具。
- 不做审批 Web UI。
- 不引入外部数据库。
- 测试不依赖网络。
- 不削弱现有 path allowlist、snapshot 检查和 secret redaction。

## 核心概念

### 风险等级

每个解析后的 action 会被分类为三种风险等级之一：

- `safe`：如果同时通过现有 policy 检查，可以自动执行。
- `review`：在 `review` profile 下不能自动执行，需要写入 pending approval。
- `blocked`：无论 profile 是什么，都直接拒绝。

风险等级和现有 policy allowlist 是两层机制。一个路径可以被 policy 允许，但仍然因为动作不可逆或目标文件敏感而需要人工审批。

### 治理 Profile

现有 profile 继续保留：

- `strict`：硬性策略执行。需要审批的动作在该 profile 下按阻断处理。
- `demo`：执行语义和 `strict` 相同，但报告表述更适合课堂演示。
- `review`：需要审批的动作会生成 pending approval，并且不会执行。

关键变化在 `review`：harness 能区分“需要人类判断”和“硬性拒绝”。

### 待审批项

Pending approval 是一条持久化记录，表示模型请求了一个 harness 不允许自动执行的动作。字段包括：

- `id`：在本次 run 和 step 内稳定生成的标识。
- `step`：agent 主循环步数。
- `action`：动作名。
- `path`：如果 action 有目标路径，则记录目标路径。
- `risk_level`：通常为 `review`。
- `reason`：给人看的审批原因。
- `profile`：触发该决策的 governance profile。
- `arguments_preview`：经过 redaction 的 action 参数预览。
- `status`：第一版固定为 `pending`。
- `created_at`：ISO 时间戳；测试可以不断言具体时间。

第一版只创建和查看 pending approvals，不做批准、拒绝或 resume。

### 审批规则

第一版采用确定性规则：

- `write_file` 写普通允许范围内的任务产物，分类为 `safe`。
- `replace_file` 如果目标已存在，且命中配置的 review path，分类为 `review`。
- `delete_file` 如果以后进入工具注册表，则分类为 `review`；如果当前还不支持，则仍按 unknown action 阻断。
- 任何指向 `.env`、workspace 外部路径、policy 不允许路径的 action，分类为 `blocked`。
- 任何 unknown action，分类为 `blocked`。

第一版需要支持在 `specgate.toml` 中配置 review paths 和 review actions。

示例：

```toml
[governance]
profile = "review"
review_actions = ["replace_file"]
review_paths = ["README.md", "src/**"]
blocked_paths = [".env", "../*"]
```

如果没有 governance 配置，默认行为必须保持保守。

## 架构设计

### 新模块：`specgate.approvals`

该模块负责审批门的数据结构和纯分类逻辑：

- `RiskLevel`
- `ApprovalStatus`
- `ActionRisk`
- `PendingApproval`
- `ApprovalQueue`
- `classify_action_risk(action, policy, governance_config) -> ActionRisk`

文件 IO 要保持小而明确。纯分类逻辑必须能在不接触文件系统的情况下单元测试。

### 配置集成

现有 config loader 需要解析可选的 governance 字段：

- `profile`
- `review_actions`
- `review_paths`
- `blocked_paths`

缺失字段使用空列表和现有默认 profile。无效 profile 必须 fail closed，和当前 CLI 行为保持一致。

### Runner 集成

`AgentRunner` 继续负责 agent 主循环。Runner 在 action parse 之后、实际修改文件之前插入 review decision point：

```text
parse action
  -> existing policy preconditions
  -> classify risk
  -> if blocked: record blocked decision and feedback
  -> if review under review profile: persist pending approval, record feedback, skip dispatch
  -> if safe: dispatch tool normally
```

当 action 进入 review 队列时，模型应该收到类似 blocked-tool 的反馈。这样下一步它可以选择更安全的 action。

### 审批队列存储

Pending approvals 存储在：

```text
runs/latest/pending_approvals.json
```

JSON 结构应该稳定、可读：

```json
{
  "approvals": [
    {
      "id": "approval-step-2",
      "step": 2,
      "action": "replace_file",
      "path": "README.md",
      "risk_level": "review",
      "reason": "replace_file on protected path requires human review",
      "profile": "review",
      "status": "pending",
      "arguments_preview": {"path": "README.md"}
    }
  ]
}
```

审批队列属于 run artifact，不属于长期记忆。它应该像 latest trace 一样，每次 run 重置。

### Trace 和 Metrics

Trace 增加 `approval_requested` event，内容为 pending approval payload。已有的 `permission_decision` 和 `run_summary` event 继续保留。

Metrics 增加：

- `approval_requests`
- `pending_approvals`

Trust summary 规则：

- 如果最终 Gate 通过，但存在 pending approvals，状态为 `warning`。
- 如果因为必需动作进入 pending approval 导致运行无法完成，状态为 `failed`。

### CLI

增加一个小命令组：

```powershell
python -m specgate.cli approvals list <workspace>
```

该命令读取 `runs/latest/pending_approvals.json` 并打印简洁表格：

```text
ID              STATUS    ACTION        PATH       REASON
approval-step-2 pending   replace_file  README.md  replace_file on protected path requires human review
```

如果队列不存在，输出清晰的 “no pending approvals” 信息，并以成功状态退出。

本阶段刻意不加入 approve 和 deny 命令，因为它们会引入 resume 语义。等 pending queue 稳定后再单独设计。

### Report

静态报告增加 `Pending Approvals` 区块，展示：

- 数量
- id
- status
- action
- path
- reason

所有动态字段必须 HTML escape，沿用上一阶段治理报告转义修复的原则。

### Eval Runner

Eval 结果增加：

- `approval_requests`
- `pending_approvals`
- `trust_status`

控制台摘要可以保持简洁。详细审批数据写入 `results.json`；如果使用 `--save-workspaces`，case workspace 中也应保留相关产物。

## 数据流

```text
LLM output
  -> parse JSON action
  -> policy and registry checks
  -> risk classifier
  -> governance profile decision
  -> safe: dispatch tool
  -> review: write pending approval and skip mutation
  -> blocked: deny and skip mutation
  -> feedback into next context
  -> Gate/report/trace/eval summaries
```

## 错误处理

- malformed approval queue JSON 应该产生可读 CLI 错误，不打印 traceback。
- unknown governance profile 应该在 config/CLI parsing 阶段 fail closed。
- 不提前增加未设计完成的 approve/deny 命令。
- review-required action 绝不能部分修改目标文件。
- action 参数中的 secret 必须经过现有 redaction 后才能进入 trace/report。
- 如果审批队列持久化失败，高风险动作仍然不能执行，并且 run 应标记为 failed 或 warning，原因要清楚。

## 测试策略

所有核心测试使用 MockLLM 或直接构造输入，不依赖真实 LLM 或网络。

单元测试：

- `tests/test_approvals.py`
  - 普通允许写入分类为 `safe`。
  - protected replace 分类为 `review`。
  - `.env` 或 path escape 分类为 `blocked`。
  - 可以序列化和加载 `PendingApproval`。

Runner 测试：

- `review` profile 记录 pending approval，且不修改 protected file。
- `strict` profile 下，同一 action 被阻断，而不是创建 approval。
- safe write 仍然正常执行，并能通过 Gate。
- review feedback 会进入下一轮 context。

CLI 测试：

- `approvals list` 在队列缺失时输出 no pending approvals。
- `approvals list` 在队列存在时输出 pending approval 行。
- malformed queue 产生干净错误。

Report 测试：

- report 包含 `Pending Approvals`。
- report 会转义 approval 动态字段。

Eval 测试：

- eval result 包含 approval counts。
- review case 在 `--save-workspaces` 下保留 `runs/latest/pending_approvals.json`。

## 验收标准

- MockLLM run 能确定性地产生 pending approval，且不会修改 protected target。
- blocked action 保持 blocked，不会被错误标成 review。
- safe action 仍走现有 dispatch 路径。
- review-required action 会写入 `runs/latest/pending_approvals.json`。
- `python -m specgate.cli approvals list <workspace>` 可以展示 pending approvals。
- Trace、report、metrics、eval 输出都包含审批证据。
- 完整单元测试套件在无网络环境下通过。

## 后续工作

本阶段结束后，可以单独设计：

- `approvals approve`
- `approvals deny`
- 审批后恢复执行
- 签名审批记录
- WebUI 审批视图
- session replay 或 checkpoint restore

这些功能刻意不放进本 spec，避免当前分支范围失控。

## Spec 自审

- 占位符检查：没有未完成占位标记。
- 一致性检查：本设计把 pending approval 定义为“不执行的证据记录”，不是 approval/resume。
- 范围检查：本阶段限定在队列创建、查看、trace/report/eval 证据，以及确定性测试。
- 歧义检查：`review` 和 `blocked` 明确区分，二者都不会修改 workspace。
