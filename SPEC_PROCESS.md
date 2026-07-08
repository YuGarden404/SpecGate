# SpecGate 规约过程记录

## 1. 过程概览

本文档记录 SpecGate 设计如何通过 Superpowers 风格流程产生：先 brainstorming，再写 `SPEC.md`，再写 `PLAN.md`，再做冷启动验证，最后才进入实现。

截至 2026-07-07：MVP 边界已经确认，课程要求已经重新阅读，初版 `SPEC.md` 已写入。实现代码尚未开始。

## 2. 关键 brainstorming 迭代

### 第 1 轮：理解课程资料

先阅读了 `D:\code\NJU\AI4Coding\docs` 中的 AI4SE 课程资料。核心结论是：期末项目不是考“AI 能不能写代码”，而是考学生能不能设计工程机制来控制 AI 写代码。

决策：

- 选择 A 类 `Coding Agent Harness`，因为它是课程首选方向，也最贴合 Prompt / Context / Harness Engineering 主线。

### 第 2 轮：区分 A 类和 B 类

对 A 类和 B 类做了澄清：

- A 类重点是 harness core：loop、tools、guardrails、memory/context、feedback、config、deterministic tests。
- B 类重点是应用产品；如果 B 类里有 agent 部分，该 agent 部分仍需遵守 A 类边界。

决策：

- SpecGate 是 A 类项目。
- 不能用 LangChain AgentExecutor、AutoGen、CrewAI、LangGraph 或宿主 coding agent runner 作为交付物核心。

### 第 3 轮：确定 MVP 边界

比较多个可能范围后，最终 MVP 定为：

```text
Python CLI harness + mock LLM + 静态 HTML 生成/修复
+ Checklist/Gate 反馈闭环 + 静态 Web 报告
```

明确排除：

- 不开放 shell。
- 不做 Playwright。
- 不做复杂前端。
- 不做实时 dashboard。

决策：

- 主要贡献聚焦在确定性 Checklist/Gate 反馈闭环，而不是 UI 复杂度或广泛工具访问。

### 第 4 轮：重新核对期末要求

2026-07-07 重新阅读了通用要求和 A 类要求。设计因此补充了：

- 凭据威胁模型。
- Docker 分发。
- 通过 Pages 提供静态 WebUI URL。
- `.gitlab-ci.yml` 中必须有 `unit-test` job。
- mock LLM 确定性测试。
- 机制演示：guardrail 拦截、反馈驱动修复、主贡献机制行为。
- 实现前进行冷启动验证。

## 3. 采纳的 AI 建议

- 用静态 HTML 任务缩小范围，使反馈可以确定性检查。
- WebUI 做成静态报告，而不是 live dashboard。
- `MockLLM` 作为主要验证路径。
- MVP 不开放 shell，使安全边界更清晰。
- 把 Checklist/Gate 作为主贡献维度。

## 4. 拒绝或后置的 AI 建议

- 浏览器自动化后置，因为 Playwright 会扩大范围。
- 通用 coding agent 被拒绝，因为它会削弱重点机制并增加安全风险。
- 复杂前端 dashboard 被拒绝，因为课程只要求可访问 WebUI，静态报告足够。
- shell 执行被排除出 MVP，因为它是最高风险工具类别，且不是静态 HTML Gate 演示所必需。

## 5. 冷启动验证计划

在正式实现前，需要让另一个不同类型的 agent 只读取 `SPEC.md` 和 `PLAN.md`，尝试完成 1-2 个小任务。它遇到不清楚的地方必须暂停提问，而不是猜测实现。

后续需要在这里记录：

- 第二个 agent 在哪里暂停。
- 它暴露了哪些 SPEC / PLAN 缺陷。
- 它做出了哪些与原意不一致的解读。
- 根据反馈对 `SPEC.md` / `PLAN.md` 做了哪些修订。

冷启动验证已于 2026-07-08 由 Gemini 3.5 思考完成。验证对象只包含 `SPEC.md` 和 `PLAN.md`。

验证结论：

- `SPEC.md` 与运行时输入 `TASK_SPEC.md` 的边界清晰。
- Task 2 Action parser 可以按红-绿步骤直接执行。
- Task 3 Workspace Policy / Guardrail 可以按计划执行。
- Windows PowerShell 的测试命令可执行。

暴露的问题：

- `PLAN.md` Task 3 中后三个测试使用 `Path.cwd()`，虽然能运行，但测试隔离性不如 `tempfile.TemporaryDirectory()`。
- `SPEC.md` 第 9.1 节描述了完整 `credentials set/status/clear` 交互，而 `PLAN.md` Task 10 的 MVP 实现只做 `credential_status` fail-closed 存根，范围精细度需要对齐。

处理决策：

- 采纳 Task 3 测试隔离建议，统一使用临时目录。
- 采纳凭据范围说明建议，在 `SPEC.md` 明确 MVP 只要求凭据状态存根和 fail-closed 行为，完整 keyring CLI 属于后续扩展。

## 6. 当前自检

- 还没有在 SPEC 之前写实现代码。
- 当前 `SPEC.md` 已包含 A 类额外要求：“领域与机制设计”。
- 当前 `SPEC.md` 已把课程要求映射成具体机制。
- `PLAN.md` 已写入，已经把实现拆成 TDD 小任务，并明确每个任务的验证步骤。

## 7. 语言调整记录

2026-07-07 根据人工反馈，将主要说明文档从英文改为中文。保留文件名、命令名、JSON 字段、模块名和测试 job 名称等英文标识，避免影响后续 LLM 和自动化处理。

## 8. SPEC 命名澄清

2026-07-07 根据人工反馈，澄清两类 SPEC：

- 根目录 `SPEC.md` 是课程交付物，描述 SpecGate harness 本身。
- harness 运行时的 HTML 任务输入不再叫 `SPEC.md`，改名为 `TASK_SPEC.md`，并和 `CHECKLIST.md` 一起放在示例任务目录中。

这样可以避免把“项目设计文档”和“被 harness 处理的 HTML 任务设计”混在一起。

## 9. PLAN 写入记录

2026-07-07 写入实现计划：

- 根目录课程交付物：`PLAN.md`。
- Superpowers 计划证据：`docs/superpowers/plans/2026-07-07-specgate-mvp.md`。

计划按以下模块拆分：

- 项目骨架与测试入口。
- Action parser。
- Workspace policy 与 guardrail。
- 文件工具与 dispatcher。
- 静态 HTML Gate。
- Trace store 与 context builder。
- `MockLLM` 与 `AgentRunner` 主循环。
- 静态报告生成。
- CLI、示例 `TASK_SPEC.md`、端到端 mock demo。
- 凭据边界、Docker、CI 与最终文档。

计划自检结果：

- 覆盖 `SPEC.md` 中的 A 类 harness 核心机制。
- 明确 `TASK_SPEC.md` 是 harness 运行输入。
- 明确 `.gitlab-ci.yml` 必须包含 `unit-test` job。
- 保留冷启动验证作为实现前下一步。
