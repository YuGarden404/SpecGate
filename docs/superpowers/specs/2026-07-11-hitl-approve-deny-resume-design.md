# HITL Approve / Deny / Resume 设计规格

## 1. 背景

SpecGate 已经具备一个小型 Coding Agent Harness 的核心基础：MockLLM、严格 JSON action、WorkspacePolicy、工具白名单、快照保护、HTML Gate、治理指标、HITL pending approval、RAG/Select、上下文压缩、隔离证据和 Prompt Injection Benchmark。

当前 HITL 能力还停留在“发现高风险动作并写入 pending approval”。也就是说，agent 可以被拦住，用户可以查看待审批项，但用户还不能通过 CLI 明确批准或拒绝，也不能让 runner 在审批后恢复执行。这会导致 HITL 治理只是一种报告能力，而不是完整的人机协作闭环。

本阶段目标是补齐最小但完整的 HITL approve / deny / resume 闭环。它是下一阶段“真正多代理隔离”的前置基础，因为多代理会产生更多跨角色、高风险、需要人类确认的动作。如果没有稳定的审批闭环，多代理只会放大状态混乱。

## 2. 研究问题

本阶段回答的问题是：

> 一个小型 Coding Agent Harness 能否把高风险 action 从“自动执行或直接阻断”提升为“可审计、可批准、可拒绝、可恢复执行”的治理流程，同时仍然保持 policy、快照保护、secret 脱敏和 benchmark 可重复性？

本阶段关注 harness 治理能力，不关注真实 LLM 表现。所有核心验证仍然应通过 MockLLM / StubLLM 完成。

## 3. 产品目标

本 PR 需要实现一个单次审批闭环：

1. `run --governance-profile review` 遇到需要人工复核的 action。
2. runner 不执行该 action，而是写入 `runs/latest/pending_approvals.json`。
3. 用户通过 `approvals list` 查看审批项。
4. 用户通过 `approvals approve <workspace> <approval-id>` 或 `approvals deny <workspace> <approval-id>` 改变审批状态。
5. 用户通过 `resume <workspace>` 恢复运行。
6. `resume` 一次只处理一个已审批项。
7. approved 项在执行前仍然重新校验 policy、硬阻断路径和文件快照。
8. denied 项不会执行，并把拒绝原因写入 runtime feedback。
9. 后续 runner 继续正常循环，产出 trace、report、metrics 和 trust summary。

## 4. 非目标

本阶段不做以下事情：

- 不做真实 LLM 评测。
- 不做模型能力比较。
- 不做交互式 TUI / GUI 审批界面。
- 不做批量 approve / deny / resume。
- 不把 `approve` 命令设计成直接执行 action。
- 不序列化和恢复完整 LLM 上下文对象。
- 不引入数据库、后台服务或长驻 daemon。
- 不实现真正多进程、多 worktree 或多代理沙箱。
- 不允许人类审批绕过 WorkspacePolicy、硬阻断路径或快照保护。

## 5. 核心语义

### 5.1 审批不是越权

`approve` 只表示“用户同意尝试执行这个 action”。它不是 root 权限，也不是绕过安全检查。

`resume` 在真正执行 approved action 前必须重新检查：

- action schema 是否仍然有效；
- action 是否仍在工具白名单中；
- action path 是否仍在 `allowed_write_paths` 内；
- action path 是否命中 `.env` 等硬阻断路径；
- 目标文件是否通过快照保护检查；
- action preview / trace / report 是否继续保持 secret 脱敏。

如果任一检查失败，approved action 仍然必须被阻断，并在 trace / metrics 中记录原因。

### 5.2 Deny 是显式治理反馈

`deny` 表示用户明确拒绝该 action。被拒绝的 action 不执行，但拒绝原因要进入 runtime feedback，让后续 MockLLM 能够修复计划或直接 finish。

示例反馈：

```json
{
  "type": "approval_denied",
  "approval_id": "approval-step-1",
  "action": "replace_file",
  "path": "README.md",
  "reason": "human denied: too broad"
}
```

### 5.3 Resume 一次只处理一个审批结果

本阶段采用单次 resume 语义：

- `resume <workspace>` 查找队列中最早的 `approved` 或 `denied` 项；
- 只处理这一项；
- 处理后继续 runner 正常循环；
- 如果运行中再次产生 review action，则再次暂停，等待下一轮人工审批。

这个限制让状态转换简单、可测试，并且方便后续扩展批量 resume。

## 6. 审批状态模型

`PendingApproval.status` 扩展为以下状态：

- `pending`：等待人类决定。
- `approved`：人类已批准，但 action 尚未由 `resume` 处理。
- `denied`：人类已拒绝，但拒绝结果尚未由 `resume` 处理。
- `applied`：approved action 已由 `resume` 成功执行。
- `rejected`：denied action 已由 `resume` 记录并消费。
- `failed`：approved action 在 resume 阶段重新校验或执行失败。

状态转换：

```text
pending -> approved -> applied
pending -> approved -> failed
pending -> denied -> rejected
```

不允许的转换：

- `applied` 不能再次 approve / deny。
- `rejected` 不能再次 approve / deny。
- `failed` 不能再次 approve / deny。
- `pending` 不能直接 applied / rejected / failed。

## 7. 队列数据结构

继续使用 `runs/latest/pending_approvals.json`，但每个 approval 需要保存足够信息用于 resume。

新增或强化字段：

```json
{
  "id": "approval-step-1",
  "step": 1,
  "action": "replace_file",
  "path": "README.md",
  "risk_level": "review",
  "reason": "replace_file on protected path requires human review",
  "profile": "review",
  "arguments_preview": {
    "path": "README.md",
    "content": "..."
  },
  "action_payload": {
    "schema_version": "1",
    "action": "replace_file",
    "args": {
      "path": "README.md",
      "content": "full original content"
    }
  },
  "status": "pending",
  "created_at": "2026-07-11T10:00:00Z",
  "decided_at": null,
  "decision_reason": null,
  "resolved_at": null
}
```

安全要求：

- `arguments_preview` 必须脱敏和截断，用于展示。
- `action_payload` 用于恢复执行，不能在 CLI list 或 HTML report 中直接展示完整内容。
- 写入队列文件时仍应使用 UTF-8 JSON。
- 读取 malformed queue 必须失败关闭，不能 traceback，不能泄漏 secret。

## 8. CLI 设计

### 8.1 列表

保留现有命令：

```powershell
python -m specgate.cli approvals list <workspace>
```

输出应包含：

- id
- status
- action
- path
- reason
- decision_reason（如果有）

不输出完整 `action_payload`。

### 8.2 批准

新增：

```powershell
python -m specgate.cli approvals approve <workspace> <approval-id>
```

语义：

- 只允许从 `pending` 转为 `approved`。
- 写入 `decided_at`。
- 如果 approval 不存在，返回非 0。
- 如果状态不是 `pending`，返回非 0。
- 不执行 action。

### 8.3 拒绝

新增：

```powershell
python -m specgate.cli approvals deny <workspace> <approval-id> --reason "too broad"
```

语义：

- 只允许从 `pending` 转为 `denied`。
- 写入 `decided_at` 和 `decision_reason`。
- `--reason` 可选；默认值为 `human denied`。
- 不执行 action。

### 8.4 恢复

新增：

```powershell
python -m specgate.cli resume <workspace> --max-steps 5
```

语义：

- 读取 `pending_approvals.json`。
- 查找最早的 `approved` 或 `denied` 项。
- 如果没有可处理项，返回非 0，并打印清晰错误。
- 如果处理 approved 项，先重新校验，再执行原 action。
- 如果处理 denied 项，只写入拒绝反馈。
- 处理后更新 approval 状态为 `applied`、`rejected` 或 `failed`。
- 然后继续 runner 循环，直到 finish、再次 pending approval 或 max steps。

## 9. Runner 设计

现有 `AgentRunner.run()` 会从空状态开始，并在启动时删除旧审批队列。为了支持 resume，需要引入一个轻量入口，而不是重写整个 runner。

推荐新增：

```python
AgentRunner.resume_from_approval(approval_id: str | None = None) -> RunResult
```

核心流程：

1. 不清空现有审批队列。
2. 读取队列。
3. 选择一个 `approved` 或 `denied` approval。
4. 对 denied：
   - 写入 `approval_denied` trace；
   - 增加对应 metrics；
   - 把拒绝事件加入 runtime feedback；
   - 状态改为 `rejected`。
5. 对 approved：
   - 从 `action_payload` 重建 Action；
   - 重新执行治理和 policy 校验；
   - 调用 ToolDispatcher；
   - 写入 `approval_applied` 或 `approval_failed` trace；
   - 更新 metrics；
   - 状态改为 `applied` 或 `failed`。
6. 继续进入普通 LLM loop。

为了减少重复，runner 内部可以抽出共享方法：

- 构建 context；
- 记录 permission decision；
- 记录 tool feedback；
- run gate；
- finish result。

但本阶段不做大规模 runner 重构，只抽取 resume 必需的最小共享逻辑。

## 10. Metrics 与 Trust

`RunMetrics` 需要扩展审批闭环指标：

- `approval_requests`
- `pending_approvals`
- `approved_approvals`
- `denied_approvals`
- `applied_approvals`
- `failed_approvals`

trust 语义：

- 仍有 `pending` / `approved` / `denied` 未处理项时，trust 至少为 `warning`。
- approved action 成功 applied，且最终 gate 通过、无其他异常时，可以回到 `trusted`。
- denied action 被 rejected 后，如果最终 gate 通过，可以是 `warning` 或 `trusted`，取决于是否保留 `human_denial_present` 作为治理原因。推荐本阶段保留为 `warning`，因为这表示运行曾被人类干预。
- approved action 在 resume 阶段 failed，trust 必须是 `failed`。

## 11. Report 与 Trace

Trace 需要新增事件类型：

- `approval_approved`
- `approval_denied`
- `approval_applied`
- `approval_rejected`
- `approval_failed`
- `resume_started`
- `resume_finished`

Report 的 Pending Approvals 区域需要升级为 Approval History：

- 展示所有 approval 的 id、status、action、path、reason、decision_reason。
- 不展示完整 `action_payload`。
- 对 malformed queue 继续清晰报错并脱敏。

## 12. Eval / Benchmark

新增至少一个 mock eval case，用于证明 HITL 闭环可自动化验证：

场景：

1. MockLLM 第一次请求修改受保护文件。
2. review profile 产生 pending approval。
3. 测试代码调用 approve。
4. 调用 resume。
5. MockLLM 根据 tool result / gate feedback finish。
6. 断言文件确实被修改、approval 状态为 applied、metrics 正确、trace 完整。

另一个 deny 场景：

1. MockLLM 第一次请求高风险 action。
2. 测试调用 deny。
3. 调用 resume。
4. 断言原文件未变、状态为 rejected、runtime feedback 包含 denial、runner 可以继续 finish 或保持 warning。

安全回归：

- approve `.env` 写入仍然失败。
- approve 路径逃逸仍然失败。
- approval list / report / trace 不泄漏 secret-like 内容。

## 13. 验收标准

本阶段完成后，以下命令应通过：

```powershell
$env:PYTHONPATH="src"
python -m unittest discover -s tests -v
```

推荐新增 smoke flow：

```powershell
$env:PYTHONPATH="src"
python -m specgate.cli run-mock-demo examples/knowledge_nav --governance-profile review
python -m specgate.cli approvals list examples/knowledge_nav
python -m specgate.cli approvals approve examples/knowledge_nav approval-step-1
python -m specgate.cli resume examples/knowledge_nav --max-steps 5
```

如果 demo workspace 默认不会产生 review action，则应新增专门 HITL demo / eval case，不强行改变现有 demo 的语义。

## 14. 后续扩展

本 PR 完成后，可以继续做：

1. 批量 approve / deny / resume。
2. 更细粒度的人类审批策略，例如按 diff 大小、路径风险、工具类型自动升级。
3. 多代理隔离中的 planner / implementer / reviewer 审批边界。
4. 把审批历史纳入 benchmark 汇总，比较不同 harness 策略下的人类介入成本。
5. 浏览器或 Web UI 形式的审批面板。

本阶段只交付 CLI 驱动、mock-first、可回归测试的最小闭环。
