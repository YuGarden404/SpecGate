# SpecGate WebUI 运行工作台设计

日期：2026-07-12

## 1. 背景

SpecGate WebUI 已经具备登录、项目创建、MockLLM 运行、产物下载、Audit 调试、HITL 审批和用户策略设置。当前问题是：后端已经产生了丰富的 harness 证据，但普通用户进入页面后，第一眼只能看到基础 run 状态，必须切到 Audit 并阅读较多技术细节，才能理解 SpecGate 实际做了什么。

本阶段目标是把 Status 页升级为“运行工作台”：在不改变后端执行语义、不接真实 LLM、不改 MockLLM 输出的前提下，把已有 run/debug/trace/metrics/evidence/artifacts/approvals 信息用更直观的方式汇总展示。

## 2. 目标

- Status 页展示本次运行的关键状态：项目、run id、状态、信任等级、错误、创建/开始/完成时间。
- Status 页展示实际运行策略：治理策略、上下文策略、运行模式。
- Status 页展示核心指标：LLM 调用、工具调用、Gate 次数、被阻止动作、审批请求、RAG 查询、上下文最大字符数。
- Status 页展示执行流程：构建上下文、LLM 响应、权限判定、工具执行、Gate 校验、运行总结。
- Status 页展示产物状态：是否存在 `index.html` 与 `result.zip`，并提供下载入口。
- Status 页展示审批提示：当 run 需要审批或存在审批项时，引导用户切到 Approvals。
- 所有展示信息从现有 `/api/runs/{id}/debug` 返回值推导，不新增数据库字段。

## 3. 非目标

- 不接入真实 LLM。
- 不提高 MockLLM 生成 HTML 的智能程度。
- 不改变 runner、policy、gate、approval 的执行语义。
- 不新增图表库、前端框架或构建系统。
- 不把 Audit 页删除；Audit 仍保留完整技术细节和原始 JSON。
- 不做复杂的历史运行列表。本阶段只展示当前项目 latest run。

## 4. 前端设计

Status 页从纯文本详情升级为四块内容：

1. 运行概览
   - 项目、Run、状态、信任等级、错误、时间。
   - 状态与信任等级仍使用现有 pill 与文本，不引入复杂图标。

2. 策略与指标
   - 复用 `auditRunStrategy(debug)` 从 trace 中读取治理策略和上下文策略。
   - 复用 `latestRunSummary(debug)` 读取 metrics。
   - 以紧凑指标卡显示关键计数。

3. 执行流程
   - 复用 trace events，使用现有 `translateTraceEvent` 和 `describeTraceEvent`。
   - 只展示最多 6 条关键事件，避免 Status 页变成完整调试日志。
   - 如果 trace 被截断或事件更多，提示用户去 Audit 页查看完整内容。

4. 产物与审批
   - 从 debug artifacts 中显示 `index` 和 `zip` 是否存在、大小和下载链接。
   - 从 debug approvals 中显示审批数量。
   - 如果 run 状态为 `needs_approval` 或审批数量大于 0，显示“前往审批”按钮，切换到 Approvals tab。

## 5. 数据流

Status 页渲染逻辑如下：

```text
renderStatusDetail
  -> 如果没有 currentRun：显示空状态
  -> 如果有 currentRun：先显示加载状态
  -> loadRunDebug(currentRun.id)
  -> renderRunWorkspace(debug)
       -> renderRunWorkspaceOverview(debug)
       -> renderRunWorkspaceMetrics(debug)
       -> renderRunWorkspaceFlow(debug)
       -> renderRunWorkspaceArtifacts(debug)
       -> renderRunWorkspaceApprovals(debug)
```

如果 debug API 请求失败，Status 页仍回退到当前已有的基础 run rows，并展示错误消息。这样即使调试数据不可用，用户仍能看到基本状态。

## 6. 组件边界

本阶段只修改静态前端：

- `src/specgate/web_static/app.js`
  - 新增 `renderRunWorkspace`
  - 新增 `renderRunWorkspaceMetrics`
  - 新增 `renderRunWorkspaceFlow`
  - 新增 `renderRunWorkspaceArtifacts`
  - 新增 `renderRunWorkspaceApprovals`
  - 新增 `formatBytes`
  - 修改 `renderStatusDetail` 以加载 debug 并渲染工作台。
- `src/specgate/web_static/styles.css`
  - 新增工作台布局样式。
- `src/specgate/web_static/index.html`
  - bump 静态资源版本。
- `tests/test_web_static.py`
  - 用静态测试覆盖新增函数、中文文案和样式 hook。

不修改后端接口，除非测试暴露出当前 debug payload 缺少必须字段；目前设计假设现有 payload 已足够。

## 7. 错误处理

- 没有项目：Status 页提示创建或选择项目。
- 没有 run：Status 页展示项目状态和“还没有运行”的空状态。
- debug 加载中：展示加载文案。
- debug 加载失败：展示基础 run 信息和错误文案，不影响 Preview/Audit/Approvals。
- artifacts 为空：展示“暂无产物”，不显示下载链接。
- approvals 为空：展示“无待处理审批”。

## 8. 测试策略

采用静态前端测试，不引入浏览器自动化：

- `tests/test_web_static.py` 检查 `app.js` 包含运行工作台相关函数。
- 检查 Status 页文案包含“运行工作台”“执行流程”“产物”“前往审批”等中文。
- 检查 `styles.css` 包含 `.run-workspace`、`.run-flow`、`.artifact-list` 等样式 hook。
- 检查 `index.html` 静态资源版本号更新。

回归验证：

- 运行 `python -m unittest tests.test_web_static -v`。
- 运行 WebUI focused tests。
- 运行全量 `python -m unittest discover -s tests -v`。

## 9. 验收标准

打开 WebUI 后，用户不需要先进入 Audit，也能在 Status 页看到本次运行的状态、策略、指标、执行流程、产物和审批提示。老师查看演示时，能够直接从主状态页理解 SpecGate 的 harness 价值：它不仅生成 HTML，还记录策略、权限、Gate、审批、RAG/压缩/隔离等运行证据。
