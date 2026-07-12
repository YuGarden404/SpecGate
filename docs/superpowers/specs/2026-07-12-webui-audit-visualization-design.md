# SpecGate WebUI 中文审计面板设计

日期：2026-07-12

## 1. 背景

WebUI 已经可以通过 `GET /api/runs/{run_id}/debug` 获取完整后端审计信息，并在 Audit 面板中展示摘要和原始 JSON。当前问题是这些信息仍偏向开发者调试：字段多为英文，关键指标藏在 JSON 深处，trace 事件没有按执行语义分组，右侧 tab 在窄面板中容易挤压。

本阶段目标是把 Audit 面板升级为“老师能看懂的中文审计面板”。它仍保留原始 JSON 作为完整证据，但优先展示中文摘要、执行流程、关键指标和 evidence 状态。

## 2. 目标

- Audit 面板标题和主要说明改为中文。
- 将 debug summary 渲染成中文摘要卡片。
- 从 `run_summary.payload.metrics` 中提取关键指标，渲染为指标卡片。
- 将 trace events 按事件类型渲染成中文执行流程。
- 将 evidence 状态转成中文说明：未启用或已记录。
- 保留 Raw JSON 区域，便于开发者和教师检查完整数据。
- 优化右侧 tabs 布局，避免 `Audit` / `Approvals` 被挤压或遮挡。

## 3. 非目标

- 不修改后端 debug API。
- 不修改 MockLLM、runner、gate、approval 等后端 harness 逻辑。
- 不接真实 LLM。
- 不做复杂图表库、动画、筛选器或搜索。
- 不重构整个 WebUI 布局。

## 4. 前端展示结构

Audit 面板从上到下分为五块：

1. `运行概览`
   - 状态
   - 信任等级
   - 产物数量
   - 审批数量
   - Trace 事件数量
   - Evidence 状态

2. `关键指标`
   - LLM 调用
   - 工具调用
   - 被阻止动作
   - Gate 次数
   - Gate 失败
   - 审批请求
   - RAG 查询
   - 压缩输入/输出字符
   - 角色运行次数

3. `执行流程`
   - `context_built` -> 构建上下文
   - `llm_response` -> LLM 返回动作
   - `permission_decision` -> 权限判定
   - `tool_result` -> 工具执行
   - `gate_result` -> Gate 校验
   - `run_summary` -> 运行总结
   - 未知事件 -> 其他事件

4. `Evidence 状态`
   - RAG 检索证据
   - 压缩证据
   - 多代理隔离证据
   - 安全评估证据

5. `原始 JSON`
   - 继续展示完整 debug payload。
   - 默认直接可见，后续可再改成折叠。

## 5. 文案规则

使用中文面向课程展示：

- `completed` -> `已完成`
- `running` -> `运行中`
- `queued` -> `排队中`
- `failed` -> `失败`
- `needs_approval` -> `等待审批`
- `trusted` -> `可信`
- `warning` -> `警告`
- `failed` -> `失败`
- evidence 为 null -> `本次未启用`
- evidence 存在 -> `已记录`

保留少量英文专有名词，如 `Gate`、`RAG`、`MockLLM`、`Trace`。

## 6. 布局规则

- 右侧 tab 改为自动换行或横向滚动，不能挤压到文字不可读。
- 指标卡片使用紧凑网格，适合右侧窄面板。
- 执行流程使用纵向列表，每条显示事件类型、步骤号和简短摘要。
- Raw JSON 使用现有 `source-view`，避免引入新的复杂组件。

## 7. 测试策略

静态测试覆盖：

- `app.js` 包含中文审计面板标题。
- `app.js` 包含 `renderAuditMetrics`。
- `app.js` 包含 `renderAuditTimeline`。
- `app.js` 包含 `translateRunStatus` 和 `translateTrustLevel`。
- `styles.css` 包含 `.audit-metrics`、`.audit-timeline`、`.audit-event`。
- tabs 样式不再固定为 6 等分，应支持自适应换行或横向滚动。

回归测试：

- 现有 Web static tests 继续通过。
- Web app/debug/run 相关测试继续通过。
- 全量 `python -m unittest discover -s tests -v` 通过。

## 8. 验收标准

完成后，用户打开 Audit 面板时，应优先看到中文概览、关键指标、执行流程和 evidence 状态；仍然能在下方看到完整 Raw JSON。右侧 tabs 在当前窄面板中不再明显挤压或遮挡。
