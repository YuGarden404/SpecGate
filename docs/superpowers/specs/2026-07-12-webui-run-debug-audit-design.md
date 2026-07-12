# SpecGate WebUI 运行调试与审计透传设计

日期：2026-07-12

## 1. 背景

SpecGate WebUI 已经跑通注册登录、项目创建、任务运行、结果预览和下载闭环。当前短板不是 MockLLM 生成页面的质量，而是 WebUI 尚未完整展示后端 harness 在一次运行中产生的治理信息。

本阶段目标是把后端已有的运行状态、指标、权限判定、Gate 结果、审批队列、产物信息和 trace evidence 结构化透传给前端。前端先以 Audit/Debug 面板展示这些信息，后续再决定哪些内容适合面向普通用户，哪些内容保留给教师演示或开发调试。

## 2. 目标

- 新增一个受登录保护的 run debug API，返回当前用户某次 run 的完整审计信息。
- 前端新增 Audit/Debug 视图，展示后端透传的摘要和原始 JSON。
- 保留当前 MockLLM 行为，不做基于主题的 if-else 页面生成。
- 复用现有 runner、metrics、gate、approvals、trace、artifact 数据，不重新实现 harness 逻辑。
- 对 trace 做最大条数和最大字符数限制，避免小项目之外的长 trace 卡死前端。

## 3. 非目标

- 不接真实 LLM。
- 不优化 MockLLM 的页面生成质量。
- 不实现复杂图表、时间线或可视化筛选。
- 不向前端暴露服务器绝对路径作为普通用户能力；调试数据中如需展示路径，只展示相对路径或经过脱敏的结构。
- 不改变 CLI/eval runner 的既有语义。

## 4. 后端 API

新增接口：

```text
GET /api/runs/{run_id}/debug
```

权限规则：

- 必须登录。
- 只能访问当前用户自己的 run。
- 找不到 run 或访问他人 run 时沿用现有 404/400 处理，不泄露资源存在性。

返回结构：

```json
{
  "debug": {
    "run": {},
    "project": {},
    "artifacts": [],
    "approvals": [],
    "trace": {
      "events": [],
      "truncated": false,
      "max_events": 200,
      "max_event_chars": 4000
    },
    "evidence": {
      "retrieval": null,
      "compression": null,
      "isolation": null,
      "security": null
    },
    "summary": {
      "status": "completed",
      "trust_level": "trusted",
      "has_artifacts": true,
      "approval_count": 0,
      "trace_event_count": 0
    }
  }
}
```

## 5. 数据来源

- `runs` 表：run 状态、prompt、trust、时间、错误信息、产物路径。
- `projects` 表：项目名称、创建模式、最新状态。
- `artifacts` 表：产物类型、存在性、大小、下载 URL。
- `approvals` 表：审批状态、动作、目标路径、原因、参数预览。
- `workspace/runs/latest/trace.jsonl`：runner trace events。
- `workspace/runs/latest/retrieval.json`：检索证据。
- `workspace/runs/latest/compression.json`：上下文压缩证据。
- `workspace/runs/latest/isolation.json`：角色隔离证据。
- `workspace/runs/latest/security.json`：注入安全评估证据。

## 6. Trace 限制

默认限制：

- 最多返回 200 条 trace event。
- 每条 event 序列化后最多 4000 个字符。
- 被截断的 event 标记 `truncated: true`。
- 总事件超过上限时，返回最近 200 条，并在 trace 层标记 `truncated: true`。

这样对当前“小 HTML 项目”足够，同时避免后续接真实 LLM 后前端一次加载过大 JSON。

## 7. 前端展示

新增或复用右侧详情面板的 `Audit` tab。

第一版展示：

- Summary：状态、trust、产物数量、审批数量、trace 数量。
- Artifacts：产物类型、是否存在、大小、下载链接。
- Approvals：审批状态摘要。
- Evidence：retrieval/compression/isolation/security 是否存在。
- Raw JSON：完整 debug payload，放在 `<pre>` 中，方便教师或开发者直接检查。

前端不在本阶段做复杂解释，只确保后端信息完整到达浏览器。

## 8. 错误处理

- debug API 读取 evidence 文件失败时，不让整个接口失败；对应 evidence 项返回错误对象。
- trace 文件不存在时返回空 events。
- artifacts 路径为空或文件不存在时仍返回记录，并标明 `exists: false`。
- 所有错误文本继续经过现有脱敏逻辑，避免 secret 泄露。

## 9. 测试策略

后端测试：

- 用户只能读取自己的 run debug。
- 完成一次 mock run 后，debug API 返回 run、project、artifacts、trace、summary。
- trace 超过上限时被截断。
- evidence 文件存在时被解析返回，不存在时为 null。
- artifact 文件大小和下载 URL 正确。

前端静态测试：

- 页面包含 Audit/Debug tab。
- `app.js` 包含 debug 加载和渲染逻辑。
- 无登录时不请求 debug。

回归测试：

- 现有 WebUI run、preview、approval 测试继续通过。
- 全量 `python -m unittest discover -s tests -v` 通过。

## 10. 验收标准

完成后，用户在 WebUI 发起一次 run 后，打开 Audit/Debug 面板，可以看到本次运行的后端调试信息，包括状态、产物、审批、trace、evidence 和原始 JSON。即使当前 MockLLM 仍生成固定 HTML，WebUI 也能展示 SpecGate harness 对这次运行的约束、记录和审计证据。
