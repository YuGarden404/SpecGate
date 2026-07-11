# SpecGate True Multi-Agent Isolation Design

## 1. 背景与问题

SpecGate 已经完成了自研小型 Coding Agent Harness 的核心链路：MockLLM、严格 JSON Action、Context Select/RAG、上下文压缩、WorkspacePolicy、snapshot guardrail、HITL approve/deny/resume、治理指标、静态报告和 benchmark。

当前 `isolated-harness` 策略已经能记录 planner / implementer / reviewer 的角色定义、可见区段、隐藏状态和允许动作，但它仍然是“隔离证据展示”，不是“隔离执行”。也就是说，runner 仍然只调用一个 agent loop，角色隔离没有真正参与调度和动作拦截。

本阶段要把隔离从说明性元数据推进为可测试的 harness 机制：让 planner、implementer、reviewer 在同一次运行中按阶段执行，每个角色收到不同 context、不同 state view、不同 action capability，并且所有文件写入继续经过现有 policy、snapshot 和 HITL 治理。

本阶段仍坚持 mock-first。真实 LLM 不作为验收条件，也不把重点放在模型效果比较上。

## 2. 目标

本阶段目标是实现第一版 true multi-agent isolation：

1. 单进程内执行三阶段角色编排：planner -> implementer -> reviewer。
2. 每个角色使用代码级 context view 和 state view，不依赖提示词自觉遵守边界。
3. 每个角色先经过 role capability check，再进入现有 action parser、WorkspacePolicy、snapshot、HITL 和 ToolDispatcher。
4. planner 和 reviewer 不能写文件；即使它们输出 `write_file` 或 `replace_file`，也会被 role 层阻断。
5. implementer 可以提出写入，但不能绕过 WorkspacePolicy、snapshot guardrail、HITL review profile 或 hard blocked paths。
6. trace、metrics、report 和 eval case 能展示角色执行证据，而不只是展示角色定义。
7. benchmark 可以把 `multi-agent-isolated` 作为 harness strategy 与 baseline、rag-select、compressed-rag、isolated-harness 对比。

## 3. 非目标

第一版明确不做：

1. 不做真实并发。
2. 不做真实多进程沙箱。
3. 不创建真实 git worktree 或复制 workspace 作为运行时必备条件。
4. 不做 agent 自动生成任务树或动态创建新角色。
5. 不把真实 LLM 作为验收标准。
6. 不绕过现有 HITL approve/deny/resume 机制。
7. 不在本阶段重写整个 `AgentRunner`。

这些能力可以作为后续 B/C 阶段继续深化。

## 4. 方案选择

考虑过三个方案：

### 4.1 方案 A1：直接在 `AgentRunner` 内加入三阶段模式

当 `context_strategy="multi-agent-isolated"` 时，runner 内部依次执行 planner、implementer、reviewer。实现最直接，但会让 `runner.py` 继续膨胀。

### 4.2 方案 A2：新增轻量 multi-agent coordinator

新增独立 coordinator，负责角色编排、role context、role state、role capability 和角色证据。现有 runner 在策略为 `multi-agent-isolated` 时委托 coordinator 执行。文件动作仍然复用现有治理链路。

这是推荐方案。它让“多代理隔离”成为清晰模块，而不是把所有逻辑塞进主循环。同时它不要求大规模重构，适合作为第一版真实隔离。

### 4.3 方案 A3：只做 role prompt wrapper

每轮仍是单 agent loop，只在 prompt 中提示当前角色。这种方案改动最小，但本质仍是提示词约束，无法证明 harness 层代码隔离。

最终选择：A2 的轻量版本。

## 5. 总体架构

新增一个单进程三角色执行链：

```text
Coordinator
  -> Planner role
     - 只能 read_file / list_files / finish
     - 看到 Task / Checklist / Retrieved Context / Latest Gate Feedback
     - 输出 plan
  -> Implementer role
     - 可以 read_file / list_files / write_file / replace_file / finish
     - 看到 Task / Checklist / Retrieved Context / Plan / Latest Gate Feedback
     - 输出文件动作或 finish
     - 文件动作继续经过 policy / snapshot / HITL / ToolDispatcher
  -> Reviewer role
     - 只能 read_file / list_files / finish
     - 看到 Task / Checklist / Final Artifact Summary / Trace Summary / Latest Gate Feedback
     - 输出 review notes、finish 或 repair request
  -> Coordinator
     - 记录 role evidence
     - 决定是否结束或允许有限 repair cycle
```

第一版仍使用现有 `LLMClient.complete(context)` 接口，因此 MockLLM 可以确定性地按顺序返回 planner、implementer、reviewer 的 JSON action。

## 6. 角色语义

### 6.1 Planner

Planner 负责读任务和上下文，产出计划。它不能写文件。

Planner 允许动作：

- `read_file`
- `list_files`
- `finish`

Planner 的 `finish.args.summary` 被 coordinator 解释为 `shared_state.plan`。

Planner 如果输出 `write_file` 或 `replace_file`，该 action 在 role capability 层被阻断，记录 `role_action_blocked`，不会进入 ToolDispatcher。

### 6.2 Implementer

Implementer 负责根据 task、checklist、retrieved context 和 plan 产出实际文件动作。

Implementer 允许动作：

- `read_file`
- `list_files`
- `write_file`
- `replace_file`
- `finish`

Implementer 的写入仍必须经过：

1. role capability check
2. action parser
3. `classify_action_risk`
4. `WorkspacePolicy`
5. snapshot guardrail
6. HITL review profile
7. `ToolDispatcher`
8. HTML Gate

Role capability 只做角色边界，不做安全豁免。

### 6.3 Reviewer

Reviewer 负责检查最终 artifact、gate feedback 和 trace summary。它不能写文件。

Reviewer 允许动作：

- `read_file`
- `list_files`
- `finish`

Reviewer 的 `finish.args.summary` 被解释为 review notes。如果 summary 中出现明确 repair 意图，coordinator 可以允许 implementer 再执行有限一轮 repair。第一版建议采用显式、确定性的判断，例如 summary 包含 `request_repair` 或 action args 中出现 `{"request_repair": true}` 时触发 repair。

Reviewer 如果输出写文件动作，同样被 role capability 阻断。

## 7. Context 与 State 隔离

每个角色收到不同 context sections：

| Role | 可见 sections | 隐藏内容 |
| --- | --- | --- |
| planner | Task, Checklist, Retrieved Context, Latest Gate Feedback | draft patch, review notes, final trace details |
| implementer | Task, Checklist, Retrieved Context, Plan, Latest Gate Feedback | reviewer-only notes |
| reviewer | Task, Checklist, Final Artifact Summary, Trace Summary, Latest Gate Feedback | implementer draft internals, unnecessary retrieved raw data |

每个角色还只能看到允许的 state keys：

| Role | state keys |
| --- | --- |
| planner | task, constraints, plan |
| implementer | task, constraints, plan, draft_patch |
| reviewer | task, constraints, review_notes |

现有 `filter_state_for_role` 保留，但需要从静态 evidence 工具扩展为执行链的一部分。

## 8. 数据模型

### 8.1 RoleContext

继续使用现有 `RoleContext`，必要时增加字段：

- `role`
- `visible_sections`
- `hidden_sections`
- `allowed_actions`
- `state_keys`

### 8.2 RoleExecution

新增角色执行证据模型：

- `role: str`
- `phase: str`
- `context_chars: int`
- `visible_sections: list[str]`
- `allowed_actions: list[str]`
- `attempted_action: str | None`
- `action_allowed_by_role: bool`
- `blocked_reason: str | None`
- `summary: str | None`

### 8.3 IsolationRunEvidence

写入 `runs/latest/isolation.json`：

- `strategy: "multi-agent-isolated"`
- `role_contexts: int`
- `isolated_state_keys: int`
- `role_runs: int`
- `role_blocked_actions: int`
- `review_repairs: int`
- `roles: list[RoleContext]`
- `executions: list[RoleExecution]`

旧的 `isolated-harness` 可以继续写入只有 role definitions 的 evidence；新的 `multi-agent-isolated` 必须包含 executions。

## 9. Trace 事件

新增或扩展 trace 事件：

- `role_started`
- `role_context_built`
- `role_action`
- `role_action_blocked`
- `role_finished`
- `role_repair_requested`
- `multi_agent_summary`

所有 trace payload 必须继续经过 redaction。动态文本不能泄露 secret-like value。

## 10. Metrics

`RunMetrics` 增加：

- `role_runs`
- `role_blocked_actions`
- `review_repairs`
- `planner_runs`
- `implementer_runs`
- `reviewer_runs`

现有指标继续保留：

- `tool_calls`
- `successful_tool_calls`
- `blocked_actions`
- `parse_errors`
- `gate_runs`
- `gate_failures`
- `approval_requests`
- `pending_approvals`
- `retrieved_chunks`
- `compression_*`

`role_blocked_actions` 表示角色能力层阻断。`blocked_actions` 表示治理或工具层阻断。两者可以同时用于分析，但含义不同。

## 11. Runner 集成

新增 context strategy：

- `multi-agent-isolated`

当 `AgentRunner.run()` 遇到该策略时，进入 multi-agent coordinator。推荐实现方式：

1. 保持 `AgentRunner` 作为治理和运行入口。
2. 把可复用的小函数抽成内部 helper 或轻量模块，例如 action risk、approval request、tool dispatch、gate execution、metrics update。
3. coordinator 调用这些 helper，而不是复制一整份 `_run_loop`。
4. 第一版只抽必要部分，避免为了架构整洁做大规模重构。

`resume_from_approval()` 第一版可以继续复用现有流程。多代理运行中如果 implementer 触发 pending approval，本次运行暂停；人工 approve/deny 后，resume 应继续保持现有安全语义。是否完整恢复到 planner/reviewer 的中间阶段不作为第一版验收条件，但必须在 trace/report 中明确审批状态。

## 12. Repair Cycle

第一版支持有限 repair：

- 默认 `max_role_cycles = 2`。
- 正常流程是 planner 一次、implementer 一次、reviewer 一次。
- reviewer 请求 repair 时，coordinator 允许 implementer 再执行一轮，然后 reviewer 再检查。
- 超过 `max_role_cycles` 后 fail closed，记录 `max_steps_reached` 或 `role_cycle_limit_reached`，trust 降级。

Repair 不应该让 reviewer 获得写文件权限。

## 13. 安全边界

多代理隔离不会降低现有安全要求：

1. role capability 不能扩大 `WorkspacePolicy`。
2. retrieved context 仍然是不可信数据。
3. planner/reviewer 输出的写文件 action 不进入工具层。
4. implementer 也不能写 `.env`、路径逃逸或未授权路径。
5. HITL approve 只代表允许尝试执行，不代表绕过 policy、hard blocked path 或 snapshot。
6. report 中所有 role evidence 字段必须 HTML escape。
7. trace/report 中所有动态字段必须 redaction。

## 14. CLI 与配置

CLI 不需要新增命令。复用现有参数：

```powershell
python -m specgate.cli eval examples/eval_cases --context-strategy multi-agent-isolated
python -m specgate.cli benchmark examples/eval_cases --strategies baseline rag-select compressed-rag isolated-harness multi-agent-isolated
```

`specgate.toml` 中的 `[context] strategy = "multi-agent-isolated"` 也应被接受。

未知 strategy 必须 fail closed。

## 15. Eval Case

新增 `examples/eval_cases/true-multi-agent-isolation/`。

建议 case 内容：

- `TASK_SPEC.md`：要求生成一个包含明确 checklist 字段的静态 HTML。
- `CHECKLIST.md`：包含至少一个 `必须包含` 条目。
- `case.json`：
  - `suite = "isolation"`
  - tags 包含 `multi-agent`、`role-boundary`
  - mock responses 固定为 planner plan、implementer write、reviewer finish
  - expected 验证 should_pass、expected_trust、role_runs、role_blocked_actions 等。

另外建议增加一个越权 case：

- planner 尝试写 `index.html`
- expected：文件不被写入，role 层阻断，trust warning 或 failed，trace 包含 `role_action_blocked`

若时间有限，第一版至少保留一个成功 case 和单元测试中的越权覆盖。

## 16. 报告展示

报告中的 Role Isolation Evidence 升级为 Role Execution Evidence。

展示内容：

- role
- phase
- context chars
- allowed actions
- attempted action
- whether allowed by role
- blocked reason
- summary

如果只有旧版 `isolated-harness` evidence，则报告继续兼容旧格式，显示 role definitions。

## 17. 测试策略

### 17.1 `tests/test_isolation.py`

覆盖：

- role context 定义完整。
- role state filtering 不泄露未授权 state keys。
- role capability 判断 planner/reviewer 不允许写文件。
- isolation evidence 可以序列化。

### 17.2 `tests/test_runner.py`

覆盖：

- `multi-agent-isolated` 按 planner -> implementer -> reviewer 顺序调用 MockLLM。
- planner 的 finish summary 进入 plan。
- implementer context 包含 plan。
- planner 尝试写文件被 role 层阻断。
- reviewer 尝试写文件被 role 层阻断。
- implementer 写文件仍受 WorkspacePolicy 限制。
- implementer 在 review profile 下触发 pending approval，不直接写文件。
- reviewer request repair 时 implementer 可再执行一轮。

### 17.3 `tests/test_report.py`

覆盖：

- report 显示 role execution evidence。
- malformed isolation evidence 不导致报告崩溃。
- 动态字段 HTML escape。
- secret-like 字段 redaction。

### 17.4 `tests/test_eval_runner.py` / `tests/test_benchmark.py`

覆盖：

- eval result 汇总 role-level metrics。
- benchmark 接受 `multi-agent-isolated` 策略。
- isolation suite 可以只运行 isolation cases。

## 18. 验收标准

完成实现后必须满足：

1. `python -m unittest discover -s tests -v` 全部通过。
2. `python -m specgate.cli eval examples/eval_cases --suite isolation --context-strategy multi-agent-isolated` 可以稳定运行。
3. `python -m specgate.cli benchmark examples/eval_cases --strategies baseline rag-select compressed-rag isolated-harness multi-agent-isolated` 可以稳定运行。
4. `runs/latest/isolation.json` 包含 role executions，不只是 role definitions。
5. planner/reviewer 写文件会被 role 层阻断。
6. implementer 写文件仍受 WorkspacePolicy、snapshot 和 HITL 控制。
7. report 展示 role execution evidence。
8. 不依赖真实 LLM，不依赖网络。

## 19. 与课程要求的对应关系

本阶段强化 Harness Engineering：

- Harness 不再只是单 agent loop，而是具备角色分工、上下文隔离和能力隔离的执行机制。
- 隔离由代码实现，而不是靠 prompt 说“请不要越权”。
- 治理链路集中保留，说明多代理不会天然安全，必须由 harness 统一执行权限边界。
- MockLLM 固定输出使实验可复现，避免把结果归因于某个真实模型表现。

同时也延续 Context Engineering：

- 不同角色获得不同上下文视图。
- reviewer 不需要完整 retrieved raw data，只需要 artifact、gate 和 trace summary。
- implementer 获得 planner plan，减少无结构上下文堆叠。

## 20. 风险与对策

风险：实现时复制 `_run_loop`，导致治理逻辑分叉。  
对策：只抽必要 helper，让 multi-agent coordinator 复用同一套 policy、snapshot、HITL 和 ToolDispatcher。

风险：role capability 与 WorkspacePolicy 语义混淆。  
对策：明确 role capability 是第一层角色边界，WorkspacePolicy 是第二层工作区安全边界，指标分别记录。

风险：review repair 造成循环。  
对策：设置 `max_role_cycles`，超过后 fail closed。

风险：报告渲染 role evidence 引入 XSS 或 secret 泄露。  
对策：所有字段 escape + redact，并加 malformed evidence 测试。

风险：第一版范围过大。  
对策：只做单进程三阶段，不做真实并发、多进程、worktree 沙箱和真实 LLM 验收。
