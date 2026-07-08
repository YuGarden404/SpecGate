# SpecGate Agent Log

## 2026-07-07 22:48:03 +08:00

- Task：在 `D:\code\NJU\SpecGate` 初始化 SpecGate 项目过程。
- Skill/process：延续 Superpowers `brainstorming` 流程。
- 使用的上下文：
  - `AI4SE 期末项目 · 通用要求（所有项目必读）.md`
  - `AI4SE_Final_Project_A_Coding_Agent_Harness.md`
  - 前面对 MVP 边界的确认。
- 人工决策：
  - 项目路径是 `D:\code\NJU\SpecGate`。
  - 项目类型是 A 类 `Coding Agent Harness`。
  - MVP 边界是 Python CLI harness、mock LLM、静态 HTML 生成/修复、Checklist/Gate 反馈闭环、静态 Web 报告。
  - 不开放 shell，不做 Playwright，不做复杂前端。
- Agent 决策：
  - 先写正式项目 SPEC 和过程记录，再开始实现。
  - WebUI 采用静态报告，满足课程部署要求，同时不扩大前端范围。
  - 主要贡献维度选择 Checklist/Gate 反馈闭环。
- 输出：
  - 初版 `SPEC.md`。
  - 初版 `SPEC_PROCESS.md`。
  - 初版 `AGENT_LOG.md`。
  - 初版 `README.md`。
  - 初版 `.gitignore`。

## 2026-07-07

- Task：根据人工反馈，将主要文档从英文改为中文。
- 原因：英文说明影响人工阅读和确认。
- 处理方式：
  - `SPEC.md`、`SPEC_PROCESS.md`、`README.md`、`AGENT_LOG.md` 改为中文说明。
  - 保留 `MockLLM`、`Action`、`GateResult`、`unit-test`、`Dockerfile`、`SPEC.md`、`PLAN.md` 等英文技术标识。
- 判断：
  - 中文说明不会实质影响后续 LLM 处理。
  - 保留关键英文标识可以降低后续代码、测试、CI 和冷启动 agent 的歧义。

## 2026-07-07

- Task：澄清两类 SPEC 的命名边界。
- 人工反馈：
  - 根目录 `SPEC.md` 是我们要做的项目规约，不应该被误认为 harness 的 HTML 任务输入。
  - harness 的输入应该是一个 HTML 设计要求，然后 harness 负责实现和修改。
- 处理方式：
  - 保留根目录 `SPEC.md` 作为课程交付物。
  - 将 harness 运行时任务输入命名为 `TASK_SPEC.md`。
  - 在 `SPEC.md` 和 `README.md` 中补充“两类 SPEC”的说明。

## 2026-07-07 23:37:10 +08:00

- Task：编写 `PLAN.md`。
- Skill/process：使用 Superpowers `writing-plans` 流程。
- 输出：
  - `PLAN.md`。
  - `docs/superpowers/plans/2026-07-07-specgate-mvp.md`。
- 计划结构：
  - Task 1 项目骨架与测试入口。
  - Task 2 Action 数据结构与严格 JSON 解析。
  - Task 3 Workspace Policy 与 Guardrail。
  - Task 4 文件工具与 Dispatcher。
  - Task 5 静态 HTML Gate 与 Checklist 检查。
  - Task 6 Trace Store 与 Context Builder。
  - Task 7 `MockLLM` 与 `AgentRunner` 主循环。
  - Task 8 静态报告生成。
  - Task 9 CLI、示例任务与端到端 mock demo。
  - Task 10 凭据边界、Docker、CI 与最终文档。
- 验证：
  - 占位词扫描无命中。
  - 计划覆盖 `TASK_SPEC.md`、`MockLLM`、guardrail、Gate、静态报告、Docker、`unit-test` 和冷启动验证。
- 阻塞：
  - 当前 `.git` 目录为空且 Git 不可用，正式执行任务前需要修复 Git 初始化。

## 2026-07-08

- Task：记录并处理冷启动验证反馈。
- 外部 agent：Gemini 3.5 思考。
- 输入限制：
  - 只提供 `SPEC.md` 和 `PLAN.md`。
  - 不提供历史对话、`AGENT_LOG.md`、`SPEC_PROCESS.md` 或 `README.md`。
- 验证结论：
  - `SPEC.md` 与 `TASK_SPEC.md` 边界清楚。
  - Task 2 和 Task 3 整体可执行。
  - Windows PowerShell 测试命令可用。
- 采纳的修改：
  - `PLAN.md` Task 3 的后三个测试改为使用 `tempfile.TemporaryDirectory()`，避免依赖 `Path.cwd()`。
  - `docs/superpowers/plans/2026-07-07-specgate-mvp.md` 同步修改。
  - `SPEC.md` 第 9.1 节补充 MVP 凭据边界：只实现可测试的 fail-closed 状态存根，完整 keyring CLI 为后续扩展。
- 判断：
  - 冷启动验证未发现阻塞正式实现的问题。

## 2026-07-08 11:11:14 +08:00

- Task：Task 1 项目骨架与测试入口。
- 分支：`feat-task-1-skeleton`。
- Superpowers：
  - 使用 `using-git-worktrees` 检查隔离工作区；由于工具环境无法创建 worktree，人工确认后改用隔离分支。
  - 使用 `test-driven-development` 执行红-绿流程。
  - 使用 `executing-plans` 按 `PLAN.md` 执行 Task 1。
- 文件变更：
  - 新增 `tests/test_imports.py`，验证 `specgate` 包能导入且版本号为 `0.1.0`。
  - 新增 `pyproject.toml`，定义 Python 包元数据和未来 CLI 入口。
  - 新增 `src/specgate/__init__.py`，提供最小包入口和版本号。
  - 更新 `README.md`，加入本地测试命令。
- TDD 证据：
  - 红灯：`python -m unittest tests.test_imports -v` 失败，原因是 `ModuleNotFoundError: No module named 'specgate'`。
  - 绿灯：`$env:PYTHONPATH='src'; python -m unittest tests.test_imports -v` 通过，1 个测试 OK。
- 人工参与：
  - 人工要求解释每个文件、代码、目的和作用。
  - 实现前已说明 Task 1 的文件职责和最小实现边界。

## 2026-07-08 11:16:07 +08:00

- Task：Task 2 Action 数据结构与严格 JSON 解析。
- 分支：`feat-task-1-skeleton`。
- Superpowers：
  - 使用 `test-driven-development` 执行红-绿流程。
  - 使用 `executing-plans` 按 `PLAN.md` 执行 Task 2。
- 文件变更：
  - 新增 `tests/test_actions.py`，定义 Action parser 的行为规格。
  - 新增 `src/specgate/actions.py`，实现 `Action`、`ActionParseError`、`parse_action()`。
- 代码作用：
  - `Action` 是 LLM 动作的受控数据结构。
  - `parse_action()` 把不可信 LLM 文本解析为 `Action`，并拒绝非严格 JSON、缺字段、错误类型和非对象 `args`。
  - `ActionParseError` 让后续 runner 可以把解析失败作为 observation 回灌给 agent。
- TDD 证据：
  - 红灯：`$env:PYTHONPATH='src'; python -m unittest tests.test_actions -v` 失败，原因是 `ModuleNotFoundError: No module named 'specgate.actions'`。
  - 绿灯：同一命令通过，4 个测试 OK。
  - 回归：`$env:PYTHONPATH='src'; python -m unittest discover -s tests -v` 通过，5 个测试 OK。
- 人工参与：
  - 实现前说明了 `tests/test_actions.py` 与 `actions.py` 的职责。
  - 明确该任务只处理 action 解析，不提前实现工具分发或 guardrail。
