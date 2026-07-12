# SpecGate WebUI 运行策略绑定设计

日期：2026-07-12

## 1. 背景

WebUI 已经支持用户在 Settings 中保存治理策略和上下文策略，也已经能在 Audit 面板展示 RAG、压缩、隔离、安全评估等 evidence 状态。但当前后端运行路径仍在 `web_runs.py` 中硬编码为 `review + injection-safe`。这会导致用户在前端切换 `rag-select`、`compressed-rag` 或 `isolated-harness` 后，实际 run 仍走默认策略，Audit 面板无法展示不同 harness 策略的真实差异。

本阶段目标是把 WebUI Settings 与后端 `AgentRunner` 真正绑定，使每次 WebUI run 使用当前用户保存的 `governance_profile` 和 `context_strategy`。

## 2. 目标

- `execute_run_once` 根据 run 的 `user_id` 读取该用户 Settings。
- `_run_mock_agent` 使用 settings 中的治理策略和上下文策略创建 `GovernanceConfig`、`ContextConfig` 和 `AgentRunner`。
- `resume_run_once` 恢复运行时也使用同一用户当前 settings。
- Debug API 返回本次 trace 中实际使用的 strategy/profile，前端 Audit 可展示。
- 前端 Audit 运行概览显示：
  - 治理策略
  - 上下文策略
  - 运行模式：MockLLM

## 3. 非目标

- 不接真实 LLM。
- 不改变 MockLLM 的固定 HTML 输出。
- 不改变 CLI/eval runner 的策略语义。
- 不新增数据库迁移字段来持久化每次 run 的 settings 快照；本阶段从 trace 和 run_summary 中读取实际运行证据。
- 不保证每种策略都会在当前固定 MockLLM 场景下产生所有 evidence；只要求后端实际传入用户选择的策略。

## 4. 后端设计

新增内部 helper：

```python
def _load_user_settings(db_path: Path, user_id: int) -> dict:
    return get_settings(db_path, user_id)
```

修改执行路径：

- `execute_run_once` 在 `_run_mock_agent(paths)` 前读取 settings，并改为 `_run_mock_agent(paths, settings)`。
- `resume_run_once` 同理，改为 `_run_resume_agent(paths, settings)`。
- `_run_mock_agent` 和 `_run_resume_agent` 从 settings 中读取：
  - `governance_profile`
  - `context_strategy`
- 默认仍由 `get_settings` 保证为：
  - `review`
  - `injection-safe`

## 5. 策略映射

第一版直接使用已存在的 `VALID_CONTEXT_STRATEGIES` 和 `VALID_GOVERNANCE_PROFILES`，不做新的前端枚举扩展。

注意：

- WebUI 下拉框当前有 `isolated-harness`，但深度多代理策略实际是 `multi-agent-isolated`。本阶段先绑定已保存的值，不新增 UI 选项语义。如果 `isolated-harness` 在现有 runner 中只是渲染隔离段而不是运行多代理，这是预期行为。
- 后续可单独做“WebUI 多代理演示策略”阶段。

## 6. Debug / Audit 展示

后端 debug API 不新增字段。前端从现有 trace 中提取：

- 最新 `context_built.payload.strategy` 作为上下文策略。
- 最新 `run_summary.payload.profile` 作为治理策略。
- 固定显示运行模式为 `MockLLM`。

如果 trace 尚未产生，显示 `待运行` 或 `未知`。

## 7. 测试策略

后端测试：

- 更新用户 settings 为 `strict + rag-select` 后执行 WebUI run，trace 的 `context_built.payload.strategy` 应为 `rag-select`，run_summary profile 应为 `strict`。
- 默认 settings 仍执行为 `review + injection-safe`。
- resume run 使用当前用户 settings。

前端静态测试：

- `app.js` 包含 `auditRunStrategy` helper。
- Audit 概览包含 `治理策略`、`上下文策略`、`运行模式`。

回归测试：

- WebUI focused tests 通过。
- 全量 unittest 通过。

## 8. 验收标准

用户在 Settings 中选择不同 governance/context 策略后，新发起的 run 在 Audit 面板里显示真实使用的策略。trace 中的 `context_built` 和 `run_summary` 能证明后端 runner 收到了前端设置，而不是继续使用硬编码默认值。
