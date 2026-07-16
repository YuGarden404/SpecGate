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

## 2026-07-08 11:32:04 +08:00

- Task：Task 3 Workspace Policy 与 Guardrail。
- 分支：`feat-task-1-skeleton`。
- Superpowers：
  - 使用 `test-driven-development` 执行红-绿流程。
  - 使用 `executing-plans` 按 `PLAN.md` 执行 Task 3。
- 文件变更：
  - 新增 `tests/test_policy.py`，定义工作区策略和 guardrail 的行为规格。
  - 新增 `src/specgate/policy.py`，实现 `WorkspacePolicy`、`GuardrailDecision`、`check_action()`。
- 代码作用：
  - `WorkspacePolicy` 保存允许的 action、读路径和写路径。
  - `GuardrailDecision` 表示一个 action 是否允许执行，以及拒绝原因。
  - `check_action()` 在工具执行前拦截未知动作、路径越界、非白名单写入和非白名单读取。
  - `_normalize_relative()` 把 Windows 路径分隔符标准化，并拒绝绝对路径或包含 `..` 的路径。
- TDD 证据：
  - 红灯：`$env:PYTHONPATH='src'; python -m unittest tests.test_policy -v` 失败，原因是 `ModuleNotFoundError: No module named 'specgate.policy'`。
  - 绿灯：同一命令通过，4 个测试 OK。
  - 回归：`$env:PYTHONPATH='src'; python -m unittest discover -s tests -v` 通过，9 个测试 OK。
- 人工参与：
  - 实现前说明了 `tests/test_policy.py` 与 `policy.py` 的职责。
  - 明确该任务只做“执行前判断”，不真正读写文件；文件工具留到 Task 4。

## 2026-07-08

- Task：Task 4 文件工具与 Dispatcher。
- 分支：`feat-task-1-skeleton`。
- Superpowers：
  - 使用 `test-driven-development` 执行红-绿流程。
  - 使用 `executing-plans` 按 `PLAN.md` 执行 Task 4。
  - 使用 `verification-before-completion` 在提交前重新验证测试结果。
- 文件变更：
  - 新增 `tests/test_tools.py`，定义 `ToolDispatcher` 的文件读写和 guardrail blocked 行为规格。
  - 新增 `src/specgate/tools.py`，实现 `ToolResult` 与 `ToolDispatcher`。
- 代码作用：
  - `ToolResult` 统一表示工具执行结果，包括是否成功、消息、数据和是否被 guardrail 阻断。
  - `ToolDispatcher.dispatch()` 先调用 `check_action()`，只有 policy 放行后才执行具体文件工具。
  - `write_file` / `replace_file` 写入白名单内文件，`read_file` 读取白名单内文件，`list_files` 返回工作区文件列表，`finish` 表示 agent 请求结束。
  - `run_command` 没有实现，也不会执行；在当前 policy 下会被 `unknown action` 拦截，符合“不开放 shell”的 MVP 边界。
- TDD 证据：
  - 红灯：`$env:PYTHONPATH='src'; python -m unittest tests.test_tools -v` 失败，原因是 `ModuleNotFoundError: No module named 'specgate.tools'`。
  - 绿灯：同一命令通过，2 个测试 OK。
  - 回归：`$env:PYTHONPATH='src'; python -m unittest discover -s tests -v` 通过，11 个测试 OK。
- 人工参与：
  - 实现前说明了 `tests/test_tools.py` 与 `tools.py` 的职责。
  - 明确该任务只连接 action、policy 和文件读写，不引入 shell、Playwright 或复杂前端。

## 2026-07-08

- Task：Task 5 静态 HTML Gate 与 Checklist 检查。
- 分支：`feat-task-1-skeleton`。
- Superpowers：
  - 使用 `test-driven-development` 执行红-绿流程。
  - 使用 `executing-plans` 按 `PLAN.md` 执行 Task 5。
  - 遇到摘要断言失败后使用 `systematic-debugging` 定位根因。
  - 使用 `verification-before-completion` 在提交前重新验证测试结果。
- 文件变更：
  - 新增 `tests/test_gate.py`，定义静态 HTML Gate 的通过和失败行为规格。
  - 新增 `src/specgate/gate.py`，实现 `GateIssue`、`GateCheck`、`GateResult` 和 `run_html_gate()`。
- 代码作用：
  - `GateCheck` 表示每一条确定性检查是否通过。
  - `GateIssue` 表示失败原因、证据和修复建议，后续会作为反馈传给 agent。
  - `GateResult` 汇总 Gate 是否通过、检查列表、问题列表和自然语言摘要。
  - `run_html_gate()` 使用 Python 标准库 `HTMLParser` 静态检查 `index.html`，覆盖 doctype、HTML 基础标签、viewport、搜索/过滤、关系能力、离线资源、疑似密钥、至少 10 个知识节点，以及 `CHECKLIST.md` 中 `- 必须包含 X` 格式的内容要求。
  - Gate 不运行浏览器、不联网、不做 Playwright，符合 MVP 边界。
- TDD 证据：
  - 红灯：`$env:PYTHONPATH='src'; python -m unittest tests.test_gate -v` 失败，原因是 `ModuleNotFoundError: No module named 'specgate.gate'`。
  - 首次实现后测试失败：`test_missing_nodes_fails_with_repair_hint` 断言摘要缺少“至少 10 个”。
  - 根因：失败摘要只取前 4 个 issue，`too_few_nodes` 被前面的结构性问题挤出摘要。
  - 修复：生成失败摘要时优先展示 `too_few_nodes` 的修复建议。
  - 绿灯：`$env:PYTHONPATH='src'; python -m unittest tests.test_gate -v` 通过，2 个测试 OK。
  - 回归：`$env:PYTHONPATH='src'; python -m unittest discover -s tests -v` 通过，13 个测试 OK。
- 人工参与：
  - 实现前说明了 `tests/test_gate.py` 与 `gate.py` 的职责。
  - 明确该任务只做静态 Gate，不扩大到浏览器自动化、联网检查或复杂前端分析。

## 2026-07-08

- Task：Task 6 Trace Store 与 Context Builder。
- 分支：`feat-task-1-skeleton`。
- Superpowers：
  - 使用 `test-driven-development` 执行红-绿流程。
  - 使用 `executing-plans` 按 `PLAN.md` 执行 Task 6。
  - 使用 `verification-before-completion` 在提交前重新验证测试结果。
- 文件变更：
  - 新增 `tests/test_context.py`，定义 trace 脱敏和 context pack 组装行为规格。
  - 新增 `src/specgate/trace.py`，实现 `TraceStore` 和 `redact()`。
  - 新增 `src/specgate/context.py`，实现 `build_context_pack()`。
- 代码作用：
  - `TraceStore.append()` 将运行事件追加到 `trace.jsonl`，每行一个 JSON 事件，包含 UTC 时间、事件类型和 payload。
  - `redact()` 在 trace 落盘前递归脱敏疑似密钥，例如 `sk-...` 和 `api_key=...`。
  - `build_context_pack()` 将 `TASK_SPEC.md`、`CHECKLIST.md`、`index.html` 摘要和最近 Gate 结果拼接为下一轮 LLM 输入。
  - 本任务只做记录与上下文构造，不接入 MockLLM，也不启动 runner 主循环。
- TDD 证据：
  - 红灯：`$env:PYTHONPATH='src'; python -m unittest tests.test_context -v` 失败，原因是 `ModuleNotFoundError: No module named 'specgate.context'`。
  - 绿灯：同一命令通过，2 个测试 OK。
  - 回归：`$env:PYTHONPATH='src'; python -m unittest discover -s tests -v` 通过，15 个测试 OK。
- 人工参与：
  - 实现前说明了 `tests/test_context.py`、`trace.py` 和 `context.py` 的职责。
  - 明确 Task 6 是反馈闭环的数据准备层，agent 主循环留到 Task 7。

## 2026-07-08

- Task：Task 7 MockLLM 与 Agent Runner 主循环。
- 分支：`feat-task-1-skeleton`。
- Superpowers：
  - 使用 `test-driven-development` 执行红-绿流程。
  - 使用 `executing-plans` 按 `PLAN.md` 执行 Task 7。
  - 使用 `verification-before-completion` 在提交前重新验证测试结果。
- 文件变更：
  - 新增 `tests/test_runner.py`，定义反馈闭环和 guardrail trace 行为规格。
  - 新增 `src/specgate/llm.py`，实现 `LLMClient` 协议和 `MockLLM`。
  - 新增 `src/specgate/runner.py`，实现 `RunResult` 和 `AgentRunner`。
- 代码作用：
  - `MockLLM` 按顺序返回预设 JSON action，并记录调用次数，让闭环 demo 可复现。
  - `AgentRunner.run()` 每轮构造 context、调用 LLM、解析 action、执行工具、对 HTML 写入结果运行 Gate，并写入 trace。
  - 当 action 是 `finish` 时，runner 使用最近一次 Gate 结果作为最终结果；如果还没有 Gate 结果，则立即运行一次 Gate。
  - guardrail blocked 的工具结果会写入 `runs/latest/trace.jsonl`，用于证明不允许的动作没有被执行且可追溯。
- TDD 证据：
  - 红灯：`$env:PYTHONPATH='src'; python -m unittest tests.test_runner -v` 失败，原因是 `ModuleNotFoundError: No module named 'specgate.llm'`。
  - 绿灯：同一命令通过，2 个测试 OK。
  - 回归：`$env:PYTHONPATH='src'; python -m unittest discover -s tests -v` 通过，17 个测试 OK。
- 人工参与：
  - 实现前说明了 `tests/test_runner.py`、`llm.py` 和 `runner.py` 的职责。
  - 明确 Task 7 只接入 `MockLLM` 主循环，不接真实 LLM、不做 CLI demo、不生成最终报告。

## 2026-07-08

- Task：Task 8 静态报告生成。
- 分支：`feat-task-1-skeleton`。
- Superpowers：
  - 使用 `test-driven-development` 执行红-绿流程。
  - 使用 `executing-plans` 按 `PLAN.md` 执行 Task 8。
  - 使用 `verification-before-completion` 在提交前重新验证测试结果。
- 文件变更：
  - 新增 `tests/test_report.py`，定义静态报告生成行为规格。
  - 新增 `src/specgate/report.py`，实现 `generate_report()`。
- 代码作用：
  - `generate_report(root, gate, steps)` 在 `reports/latest/index.html` 生成静态 HTML 报告。
  - 报告展示运行步数、Gate 摘要、每条 check 的 PASS/FAIL 和 issue 列表。
  - 报告中的 Gate 文本使用 `html.escape` 转义，避免未处理文本直接进入 HTML。
  - 本任务只生成静态报告，不负责 CLI 入口、demo 编排或启动 Web 服务。
- TDD 证据：
  - 红灯：`$env:PYTHONPATH='src'; python -m unittest tests.test_report -v` 失败，原因是 `ModuleNotFoundError: No module named 'specgate.report'`。
  - 绿灯：同一命令通过，1 个测试 OK。
  - 回归：`$env:PYTHONPATH='src'; python -m unittest discover -s tests -v` 通过，18 个测试 OK。
- 人工参与：
  - 实现前说明了 `tests/test_report.py` 与 `report.py` 的职责。
  - 明确 Task 8 的报告是静态 HTML，后续 Task 9 再接入 CLI mock demo。

## 2026-07-08

- Task：Task 9 CLI、示例任务与端到端 mock demo。
- 分支：`feat-task-1-skeleton`。
- Superpowers：
  - 使用 `test-driven-development` 执行红-绿流程。
  - 使用 `executing-plans` 按 `PLAN.md` 执行 Task 9。
  - 使用 `verification-before-completion` 在提交前重新验证测试结果。
- 文件变更：
  - 新增 `tests/test_cli.py`，定义 `run_mock_demo()` 的端到端行为规格。
  - 新增 `src/specgate/config.py`，实现 `load_policy()`，从 TOML 配置构造 `WorkspacePolicy`。
  - 新增 `src/specgate/cli.py`，实现 `run_mock_demo()` 和 `specgate run-mock-demo` 命令入口。
  - 新增根目录 `specgate.toml`，作为默认 policy 配置示例。
  - 新增 `examples/knowledge_nav/TASK_SPEC.md`、`CHECKLIST.md`、`specgate.toml`，作为演示任务工作区。
  - 运行 mock demo 后生成 `examples/knowledge_nav/index.html`，作为可检查的最终 artifact。
  - 更新 `README.md`，加入 Mock Demo 运行命令和报告路径，并刷新当前状态。
- 代码作用：
  - `run_mock_demo(root)` 使用 `MockLLM` 先写入不合格 HTML，再根据 Gate 反馈替换为合格 HTML，最后生成静态报告。
  - `main()` 提供 `python -m specgate.cli run-mock-demo <workspace>` 命令行入口。
  - 示例任务展示 harness 的真实输入：`TASK_SPEC.md` + `CHECKLIST.md`，不是根目录课程规约 `SPEC.md`。
  - `runs/latest/trace.jsonl` 作为运行日志保持未提交；示例最终 `index.html` 和 `reports/latest/index.html` 作为课程展示 artifact 一并提交。
- TDD 与验证证据：
  - 红灯：`$env:PYTHONPATH='src'; python -m unittest tests.test_cli -v` 失败，原因是 `ModuleNotFoundError: No module named 'specgate.cli'`。
  - 绿灯：同一命令通过，1 个测试 OK。
  - Demo：`$env:PYTHONPATH='src'; python -m specgate.cli run-mock-demo examples/knowledge_nav` 退出码为 0。
  - Demo 产物：`examples/knowledge_nav/index.html`、`examples/knowledge_nav/reports/latest/index.html`、`examples/knowledge_nav/runs/latest/trace.jsonl` 均已生成。
  - 回归：`$env:PYTHONPATH='src'; python -m unittest discover -s tests -v` 通过，19 个测试 OK。
- 人工参与：
  - 实现前说明了 `tests/test_cli.py`、`config.py`、`cli.py`、示例任务和 README 的职责。
  - 明确 Task 9 仍使用 `MockLLM`，不接真实 LLM；凭据、Docker、CI 和最终反思留到 Task 10。

## 2026-07-08

- Task：Task 10 凭据边界、Docker、CI 与最终文档。
- 分支：`feat-task-1-skeleton`。
- Superpowers：
  - 使用 `test-driven-development` 执行凭据边界红-绿流程。
  - 使用 `executing-plans` 按 `PLAN.md` 执行 Task 10。
  - Docker 本机构建失败后使用 `systematic-debugging` 区分权限、daemon 和网络代理问题。
  - 使用 `verification-before-completion` 在提交前重新验证测试结果。
- 文件变更：
  - 新增 `tests/test_credentials.py`，定义 mock 凭据豁免和真实 provider fail-closed 行为。
  - 新增 `src/specgate/credentials.py`，实现 `CredentialStatus` 和 `credential_status()`。
  - 新增 `Dockerfile`，默认运行 `examples/knowledge_nav` mock demo。
  - 新增 `.gitlab-ci.yml`，包含课程要求的 `unit-test` job，并提供 `docker-build` job。
  - 新增 `REFLECTION.md`，只提供学生本人反思结构，不代写最终观点。
  - 更新 `README.md`，补充 Docker、CI 和已知限制。
  - 更新 `SPEC_PROCESS.md`，记录 MVP 实现完成情况和待人工完成事项。
- 代码作用：
  - `credential_status("mock")` 返回 configured/safe，说明 mock 模式无需凭据。
  - 非 mock provider 默认返回 configured=False、safe_to_run=False，避免真实 LLM 在无 keyring 支持时被误启用。
  - Dockerfile 与 CI 只覆盖 mock demo 和测试路径，不引入真实凭据。
- TDD 与验证证据：
  - 红灯：`$env:PYTHONPATH='src'; python -m unittest tests.test_credentials -v` 失败，原因是 `ModuleNotFoundError: No module named 'specgate.credentials'`。
  - 绿灯：同一命令通过，2 个测试 OK。
  - 回归：`$env:PYTHONPATH='src'; python -m unittest discover -s tests -v` 通过，21 个测试 OK。
  - Demo：`$env:PYTHONPATH='src'; python -m specgate.cli run-mock-demo examples/knowledge_nav` 退出码为 0。
  - Docker CLI：`docker --version` 返回 `Docker version 29.1.3, build f52814d`，但提示本机 `C:\Users\Lenovo\.docker\config.json` 权限 warning。
  - Docker build：`docker build -t specgate:local .` 未通过，首次根因是本机 Docker buildx 配置目录权限：`CreateFile C:\Users\Lenovo\.docker\buildx\instances: Access is denied`。
  - Docker 复测：打开 Docker 后改用临时 `DOCKER_CONFIG` 继续验证，曾因 daemon 管道权限失败：`open //./pipe/docker_engine: Access is denied`。
  - Docker 最终人工验证：用户在本机 PowerShell 设置 `HTTP_PROXY`、`HTTPS_PROXY`、`NO_PROXY` 后，`docker pull python:3.11-slim` 成功，`docker build --build-arg HTTP_PROXY=$env:HTTP_PROXY --build-arg HTTPS_PROXY=$env:HTTPS_PROXY -t specgate:local .` 成功，`docker run --rm specgate:local` 退出码为 0。
  - Codex 环境复测限制：单元测试可运行，但 Codex 进程访问 Docker daemon 仍返回 `permission denied while trying to connect to the docker API at npipe:////./pipe/docker_engine`，因此 Docker 成功证据以用户本机 PowerShell 输出为准。
- 人工参与：
  - 实现前说明了凭据、Docker、CI、README、SPEC_PROCESS 和 REFLECTION 的职责。
  - 明确 `REFLECTION.md` 只创建结构，最终内容需要学生本人完成。

## 2026-07-08

- Task：Demo showcase 展示增强。
- 分支：`main`。
- Superpowers：
  - 使用 `brainstorming` 先对齐边界：只增强静态 demo 展示，不扩展复杂前端、不引入 npm/React/Vue。
  - 使用 `test-driven-development` 先写失败测试，再修改 mock demo HTML。
  - 使用 `verification-before-completion` 在说明完成前运行测试。
- 文件变更：
  - 新增 `docs/superpowers/plans/2026-07-08-demo-showcase.md`，记录小步实现计划。
  - 更新 `tests/test_cli.py`，要求 demo 产物包含中文知识图谱标题、搜索框、右侧详情面板、至少 10 个知识节点和交互函数。
  - 更新 `src/specgate/cli.py` 的 `_fixed_demo_html()`，让 `MockLLM` 生成更像课程知识导航器的单文件静态 HTML。
  - 重新生成 `examples/knowledge_nav/index.html`。
- 代码作用：
  - demo 页面从占位 `Node 0` 列表升级为 `AI for Coding 知识图谱`。
  - 页面包含 Spec、Checklist、Action Protocol、MockLLM、Guardrail、Tool Dispatcher、HTML Gate、Feedback Loop、Context Pack、Trace / Report、Credentials、Docker / CI 等知识节点。
  - 点击节点时右侧显示知识详情，并高亮关联节点；搜索框支持本地过滤。
- TDD 与验证证据：
  - 红灯：`$env:PYTHONPATH='src'; python -m unittest tests.test_cli -v` 失败，原因是旧 demo HTML 不包含 `AI for Coding 知识图谱`。
  - 绿灯：同一命令通过，1 个测试 OK。
  - Demo：`$env:PYTHONPATH='src'; python -m specgate.cli run-mock-demo examples/knowledge_nav` 退出码为 0。
  - 回归：`$env:PYTHONPATH='src'; python -m unittest discover -s tests -v` 通过，21 个测试 OK。
- 人工参与：
  - 用户提供老师演示项目截图和课堂知识搜索页面参考。
  - 明确本次改动只提升评审展示效果，不改变 A 类 Coding Agent Harness 的核心边界。

## 2026-07-08

- Task：GitHub Actions CI 补充。
- 分支：`main`。
- Superpowers：
  - 使用 `verification-before-completion` 在提交前重新运行本地测试。
- 文件变更：
  - 新增 `.github/workflows/ci.yml`。
  - 更新 `README.md` 的 CI 说明。
- 代码作用：
  - GitHub `unit-test` job 在 push 和 pull request 时运行 `python -m unittest discover -s tests -v`。
  - GitHub `docker-build` job 构建 `specgate:ci`，用于补充 GitHub 平台上的分发验证。
- 验证证据：
  - 本地回归：`$env:PYTHONPATH='src'; python -m unittest discover -s tests -v` 通过，21 个测试 OK。
- 人工参与：
  - 明确仓库实际托管在 GitHub，因此在课程要求的 `.gitlab-ci.yml` 之外补充 GitHub Actions，方便老师查看远端 pass 记录。

## 2026-07-08

- Task：GitHub Pages 静态 WebUI 部署准备。
- 分支：`main`。
- Superpowers：
  - 使用 `verification-before-completion` 在提交前重新运行本地测试。
- 文件变更：
  - 新增 `.github/workflows/pages.yml`，使用 GitHub Actions 发布 `site/`。
  - 新增 `site/index.html`，作为公开 WebUI 首页。
  - 更新 `README.md` 的静态 WebUI URL 和 Pages 设置说明。
- 代码作用：
  - Pages workflow 会在部署前重新运行 mock demo，复制 `examples/knowledge_nav/index.html` 到 `site/demo/index.html`，复制运行报告到 `site/report/index.html`。
  - `site/index.html` 提供 WebUI 首页、知识图谱 demo、运行报告和 GitHub 仓库入口。
- 验证证据：
  - 本地回归：`$env:PYTHONPATH='src'; python -m unittest discover -s tests -v` 通过，21 个测试 OK。
  - 静态检查：`git diff --check` 退出码为 0，仅提示 Windows 行尾转换 warning。
  - GitHub Pages workflow 已在远端 Actions 通过，`build-pages` 和 `deploy-pages` 均为 Success。
  - 已部署 WebUI 首页：`https://yugarden404.github.io/SpecGate/`。
- 人工参与：
  - 用户在 GitHub Settings / Pages 中确认 source 为 GitHub Actions，并重新运行 Pages workflow 完成部署验证。

## 2026-07-08

- Task：示例任务输入与目录说明整理。
- 分支：`main`。
- Superpowers：
  - 使用 `verification-before-completion` 验证整理后的示例仍能通过 Gate 和全量测试。
- 文件变更：
  - 扩写 `examples/knowledge_nav/TASK_SPEC.md`，把最小占位需求整理为正式 demo 任务规约。
  - 扩写 `examples/knowledge_nav/CHECKLIST.md`，拆分自动 Gate 必检项、内置 Gate 检查项和人工验收项。
  - 新增 `examples/knowledge_nav/README.md`，解释输入文件、输出文件、`reports/latest`、`runs/latest` 和 `site/` 的区别。
  - 重新生成 `examples/knowledge_nav/reports/latest/index.html`。
  - 更新 `README.md` 和 `site/index.html`，说明 `examples/knowledge_nav/index.html` 与 `site/index.html` 的职责差异。
- 代码作用：
  - 本次未修改 Python harness 核心代码。
  - 示例任务更清楚地表达“用户需求 + 验收清单 -> Harness 控制 LLM 生成/修复 HTML -> Gate 验收 -> 报告/trace 记录证据”的关系。
- 验证证据：
  - Demo：`$env:PYTHONPATH='src'; python -m specgate.cli run-mock-demo examples/knowledge_nav` 退出码为 0。
  - 报告检查：`examples/knowledge_nav/reports/latest/index.html` 中新增 checklist 项均为 PASS。
  - 回归：`$env:PYTHONPATH='src'; python -m unittest discover -s tests -v` 通过，21 个测试 OK。
- 人工参与：
  - 用户指出 `TASK_SPEC.md` / `CHECKLIST.md` 太简单，并询问 `reports/latest`、`runs/latest`、`site/` 与 `examples/` 的区别。

## 2026-07-08

- Task：第二阶段上下文管理增强。
- 分支：`main`。
- 文件变更：
  - 新增 `src/specgate/context_selector.py`，实现 Context Manifest 文件选择。
  - 新增 `tests/test_context_selector.py`，覆盖优先级、跳过规则、预算和非法预算。
  - 更新 `src/specgate/context.py`，让 context pack 输出 Context Manifest 和 Selected Files。
  - 更新 `README.md`，说明上下文管理行为。
- 代码作用：
  - 将固定拼接上下文升级为按目录扫描、优先级和预算选择上下文。
  - 默认跳过运行报告、trace 和缓存目录，避免污染后续 LLM 输入。
- 验证证据：
  - `$env:PYTHONPATH="src"; python -m unittest discover -s tests -v` 通过。
  - `$env:PYTHONPATH="src"; python -m specgate.cli run-mock-demo examples/knowledge_nav` 通过。
- 人工参与：
  - 用户确认默认上下文选择规则和 12000 字符预算可以接受。

## 2026-07-08

- Task：第二阶段安全修改检测。
- 分支：`main`。
- 文件变更：
  - 新增 `src/specgate/snapshot.py`，记录 allowed write paths 的文件快照。
  - 新增 `tests/test_snapshot.py`，覆盖已存在文件、missing 文件、外部修改和写入后基线更新。
  - 更新 `src/specgate/tools.py`，写入前检查 snapshot，写入成功后更新 snapshot。
  - 更新 `src/specgate/runner.py`，run 开始时默认启用文件快照保护。
  - 更新 `README.md`，说明运行期间用户修改检测。
- 代码作用：
  - 防止 agent 在运行期间覆盖用户或外部进程对 allowlist 文件的修改。
  - 安全拦截以 blocked `ToolResult` 写入 trace，便于报告和复盘。
- 验证证据：
  - `$env:PYTHONPATH="src"; python -m unittest discover -s tests -v` 通过。
  - `$env:PYTHONPATH="src"; python -m specgate.cli run-mock-demo examples/knowledge_nav` 通过。
- 人工参与：
  - 用户确认第二阶段采用“先让 Context / Safety / Tooling 都有可测试第一层”的路线。

## 2026-07-09

- Task：第二阶段工具注册表。
- 分支：`main`。
- 文件变更：
  - 新增 `src/specgate/tool_registry.py`，定义现有工具的名称、权限、参数和结果说明。
  - 新增 `tests/test_tool_registry.py`，覆盖默认工具集合、权限和 context 渲染。
  - 更新 `src/specgate/tools.py`，让工具分发器先检查 registry。
  - 更新 `src/specgate/context.py`，让 context pack 输出 Tool Registry。
  - 更新 `src/specgate/report.py`，让静态报告展示工具列表。
  - 更新 `README.md`，说明工具管理边界。
- 代码作用：
  - 将工具能力从硬编码分支提升为可测试、可展示的结构化注册表。
  - 不新增 shell、网络、MCP 或浏览器工具。
- 验证证据：
  - `$env:PYTHONPATH="src"; python -m unittest discover -s tests -v` 通过。
  - `$env:PYTHONPATH="src"; python -m specgate.cli run-mock-demo examples/knowledge_nav` 通过。
- 人工参与：
  - 用户确认先让 Context / Safety / Tooling 三个方向都有可测试第一层，再考虑深挖。

## 2026-07-09

- Task：AgentOS / Superpowers 对齐层。
- 分支：`main`。
- 文件变更：
  - 新增 `skills/specgate-static-html-harness/SKILL.md`，记录 SpecGate 静态 HTML harness 的可复用执行流程。
  - 新增 `skills/specgate-static-html-harness/agents/openai.yaml`，补充 Skill UI 元数据。
  - 新增 `docs/AI4SE_Lab_9_12_Alignment.md`，说明 Lab 9-12 的取舍。
  - 新增 `docs/superpowers/specs/2026-07-09-agentos-alignment-design.md`，记录本阶段设计。
  - 新增 `docs/superpowers/plans/2026-07-09-agentos-alignment.md`，记录本阶段实施计划。
  - 更新 `README.md`，加入 AgentOS / Superpowers 对齐说明。
- 代码作用：
  - 本次不修改 Python harness 核心代码。
  - 将当前上下文管理、安全性和工具管理机制沉淀为可复用 Skill。
  - 明确本阶段选择 Lab 10 Skill，暂不接入 Lab 9 MCP、Lab 11 Hook、Lab 12 AgentPack 和真实 LLM。
- 验证证据：
  - `python C:\Users\Lenovo\.codex\skills\.system\skill-creator\scripts\quick_validate.py skills\specgate-static-html-harness` 通过。
  - `$env:PYTHONPATH='src'; python -m unittest discover -s tests -v` 通过，39 个测试 OK。
  - `$env:PYTHONPATH='src'; python -m specgate.cli run-mock-demo examples/knowledge_nav` 通过，退出码为 0。
- 人工参与：
  - 用户确认真实 LLM 先不接入，先完成 Lab 10 Skill 和 Lab 对齐文档。

## 2026-07-09

- Task：SpecGate Skill 中文化。
- 分支：`main`。
- 文件变更：
  - 更新 `skills/specgate-static-html-harness/SKILL.md`，将说明正文改为中文，保留必要英文标识、文件名、命令和工具名。
  - 更新 `skills/specgate-static-html-harness/agents/openai.yaml`，将 Skill UI 描述和默认提示改为中文。
- 代码作用：
  - 本次不修改 Python harness 核心代码。
  - Skill 仍然描述同一套受控静态 HTML harness 流程，方便中文阅读和课程展示。
- 验证证据：
  - `$env:PYTHONUTF8='1'; python C:\Users\Lenovo\.codex\skills\.system\skill-creator\scripts\quick_validate.py skills\specgate-static-html-harness` 通过。
  - `$env:PYTHONPATH='src'; python -m unittest discover -s tests -v` 通过，39 个测试 OK。
  - `$env:PYTHONPATH='src'; python -m specgate.cli run-mock-demo examples/knowledge_nav` 通过，退出码为 0。
- 说明：
  - Windows 下 `quick_validate.py` 默认编码可能是 GBK，直接读取中文 UTF-8 Skill 会报 `UnicodeDecodeError`；设置 `PYTHONUTF8=1` 后校验通过。

## 2026-07-09

- Task：最终交付材料打磨。
- 分支：`main`。
- 文件变更：
  - 新增 `docs/FINAL_SUBMISSION_CHECKLIST.md`，整理课程交付物、核心机制、评审路径和复现命令。
  - 新增 `docs/PROJECT_WALKTHROUGH.md`，提供项目讲解稿、数据流、模块说明和演示脚本。
  - 新增 `docs/superpowers/plans/2026-07-09-final-delivery-polish.md`，记录最终材料打磨计划。
  - 更新 `README.md`，增加评审快速入口。
  - 更新 `REFLECTION.md`，补充最终交付阶段反思。
- 代码作用：
  - 本次不修改 Python harness 核心代码。
  - 将现有实现整理成面向期末评审的入口材料。
- 验证证据：
  - `$env:PYTHONPATH='src'; python -m unittest discover -s tests -v` 通过，39 个测试 OK。
  - `$env:PYTHONPATH='src'; python -m specgate.cli run-mock-demo examples/knowledge_nav` 通过，退出码为 0。
  - `$env:PYTHONUTF8='1'; python C:\Users\Lenovo\.codex\skills\.system\skill-creator\scripts\quick_validate.py skills\specgate-static-html-harness` 通过。
- 人工参与：
  - 用户确认先做方向 A：最终交付材料打磨。

## 2026-07-09

- Task：Lab 11 Hook sample。
- 分支：`main`。
- 文件变更：
  - 新增 `hooks/pre-commit.sample`，提供可选提交前检查示例。
  - 新增 `tests/test_hook_sample.py`，验证 Hook sample 包含密钥扫描、必要文件检查、测试提示和 runtime 边界说明。
  - 新增 `docs/superpowers/specs/2026-07-09-hook-sample-design.md`，记录 Hook sample 设计。
  - 新增 `docs/superpowers/plans/2026-07-09-hook-sample.md`，记录实施计划。
  - 更新 `docs/AI4SE_Lab_9_12_Alignment.md`、`docs/FINAL_SUBMISSION_CHECKLIST.md` 和 `README.md`，把 Lab 11 状态更新为已提供可选 sample。
- 代码作用：
  - 本次不修改 SpecGate runtime。
  - Hook sample 只作为 HE / Lab 11 证据，不会自动安装到 `.git/hooks`。
  - 不向 LLM 开放 shell、网络或额外文件权限。
- 验证证据：
  - `$env:PYTHONPATH='src'; python -m unittest tests.test_hook_sample -v` 通过，1 个测试 OK。
  - `$env:PYTHONPATH='src'; python -m unittest discover -s tests -v` 通过，40 个测试 OK。
  - `$env:PYTHONPATH='src'; python -m specgate.cli run-mock-demo examples/knowledge_nav` 通过，退出码为 0。
  - `$env:PYTHONUTF8='1'; python C:\Users\Lenovo\.codex\skills\.system\skill-creator\scripts\quick_validate.py skills\specgate-static-html-harness` 通过。
- 人工参与：
  - 用户确认忽略老师的进阶应用项目文档，继续沿 SpecGate 当前方向推进。

## 2026-07-10 Context Eval Harness

- Task：Context Eval Harness 设计、计划、实现与文档收口。
- Superpowers：
  - 使用 `brainstorming` 对齐深化方向：把上下文策略评估做成确定性 harness，而不是只写提示词经验。
  - 使用 `writing-plans` 产出可执行实现计划。
  - 使用 `subagent-driven-development` 按任务拆分推进实现与复核。
- 分支：`feat-context-eval-harness`。
- 设计文档：`docs/superpowers/specs/2026-07-10-context-eval-harness-design.md`。
- 实现计划：`docs/superpowers/plans/2026-07-10-context-eval-harness.md`。
- 决策：
  - 先用 MockLLM / StubLLM 完成确定性评估。
  - 不把真实 LLM 成功率作为核心验收；真实 LLM 只作为后续实验扩展。
  - 用 eval cases 比较 `baseline`、`compressed`、`injection-safe`，并把结果写入 `eval-runs/latest/results.json`。
- 验证证据：
  - `$env:PYTHONPATH='src'; python -m unittest discover -s tests -v` 通过，83 个测试 OK。
  - `$env:PYTHONPATH='src'; python -m specgate.cli eval examples/eval_cases --context-strategy baseline` 通过，`cases=4, expected_matches=4`。
  - `$env:PYTHONPATH='src'; python -m specgate.cli eval examples/eval_cases --context-strategy compressed` 通过，`cases=4, expected_matches=4`。
  - `$env:PYTHONPATH='src'; python -m specgate.cli eval examples/eval_cases --context-strategy injection-safe` 通过，`cases=4, expected_matches=4`。
  - Docker 人工验证：用户在本机 PowerShell 执行 `docker build -t specgate:context-eval .` 成功，`docker run --rm specgate:context-eval` 无报错，`docker run --rm specgate:context-eval python -m specgate.cli eval examples/eval_cases --context-strategy injection-safe` 输出 `SpecGate eval finished: strategy=injection-safe, cases=4, passed=0, expected_matches=4`。
# 2026-07-10 23:40:00 +08:00

- Task：启动 `Context Harness Deepening` 大工程规格设计。
- Branch：`feat-context-harness-deepening`。
- Skill/process：
  - 使用 Superpowers `brainstorming` 收束方向。
  - 读取课程通用要求、A 类 Coding Agent Harness 要求和 PE/CE/HE 课件。
- 人工决策：
  - 授权在一条大分支上连续推进四个阶段。
  - 授权阶段完成后自动写规格/计划、派发 subagent、审查、测试、提交，并继续下一阶段。
  - 授权根目录 `SPEC.md`、`PLAN.md`、`SPEC_PROCESS.md`、`AGENT_LOG.md` 从本轮开始作为最终交付物持续维护。
  - 确认核心验收以 mock/stub LLM 为准，真实 LLM 只作为后续可选实验。
- Agent 决策：
  - 采用方案 A：Select / RAG Harness -> Explainable Select -> Compress Lifecycle -> Isolate + Benchmark。
  - 第一版 Select/RAG 不引入向量库或 embedding API，先使用本地 lexical retrieval。
  - 第一版 Compress 不依赖 LLM 摘要，先使用 deterministic summarizer。
  - 第一版 Isolate 不做真实并发进程，只做 role context/state isolation。
- 输出：
  - `docs/superpowers/specs/2026-07-10-context-harness-deepening-design.md`
  - `SPEC.md` 追加深化规格摘要。
  - `SPEC_PROCESS.md` 追加本轮 brainstorming 过程记录。

## 2026-07-10 23:50:00 +08:00

## 2026-07-10 Task 7 Mock Eval Cases and Documentation

- Task: 补充 Context Harness Deepening 的 mock eval cases 与说明文档。
- Branch: `feat-context-harness-deepening`
- Superpowers:
  - 继续使用 `subagent-driven-development` 主流程。
  - 保持 mock/stub LLM 为核心验收路径。
- 新增样例:
  - `examples/eval_cases/retrieval-context-select`
  - `examples/eval_cases/context-compression-lifecycle`
  - `examples/eval_cases/isolation-role-boundary`
- 文档更新:
  - `README.md`
  - `SPEC.md`
  - `PLAN.md`
  - `SPEC_PROCESS.md`
  - `AGENT_LOG.md`
- 验证计划:
  - `python -m specgate.cli eval examples/eval_cases --context-strategy rag-select`
  - `python -m specgate.cli eval examples/eval_cases --context-strategy compressed-rag`
  - `python -m specgate.cli eval examples/eval_cases --context-strategy isolated-harness`
  - `python -m specgate.cli benchmark examples/eval_cases --strategies baseline rag-select compressed-rag isolated-harness`
- Review 结果:
  - 规格审查发现 `examples/eval_cases/eval-runs/` 是运行产物，需要避免误提交。
  - 质量审查建议将文档措辞从“验证策略能力”收窄为“展示/记录 evidence”。
  - 已在 `.gitignore` 增加 `examples/eval_cases/eval-runs/`，并同步修正文档说明。
- 验证结果:
  - `rag-select`: `cases=7, expected_matches=7`
  - `compressed-rag`: `cases=7, expected_matches=7`
  - `isolated-harness`: `cases=7, expected_matches=7`
  - `benchmark`: `strategies=4, cases=7`
  - `python -m unittest discover -s tests -v`: `Ran 190 tests ... OK`

- Task：编写 `Context Harness Deepening` 实现计划。
- Skill/process：
  - 使用 Superpowers `writing-plans`。
  - 根据已确认规格拆分为 8 个 TDD 任务。
- 人工决策：
  - 已确认规格。
  - 已授权按方案 A 连续推进。
- Agent 决策：
  - 任务顺序固定为 retrieval core -> rag strategy -> evidence -> compression -> isolation -> benchmark -> eval/docs -> final verification。
  - 不并行派发实现任务，避免共享文件冲突。
  - 每个任务完成后再进入下一任务。
- 输出：
  - `docs/superpowers/plans/2026-07-10-context-harness-deepening.md`
  - `PLAN.md` 追加计划摘要。
  - `SPEC_PROCESS.md` 追加计划记录。

## 2026-07-10 Task 8 Final Review, Process Evidence, and Verification

- Task 1: Lightweight Retrieval Core
  - Subagent/process: subagent-driven development with spec and quality review.
  - Spec review: approved after implementation.
  - Code review: approved after implementation.
  - Verification: retrieval/context tests and full suite passed during task execution.
  - Commit: `526f54c`
- Task 2: RAG Select Context Strategy
  - Subagent/process: subagent-driven development with spec and quality review.
  - Spec review: approved after implementation.
  - Code review: approved after implementation.
  - Verification: context strategy tests and full suite passed during task execution.
  - Commit: `ac4842a`
- Task 3: Retrieval Evidence in Trace, Metrics, Report, and Eval
  - Subagent/process: subagent-driven development with spec and quality review.
  - Spec review: approved after implementation.
  - Code review: approved after implementation.
  - Verification: runner/report/eval metrics tests and full suite passed during task execution.
  - Commit: `5c6a51b`
- Task 4: Deterministic Context Lifecycle Compression
  - Subagent/process: subagent-driven development with spec and quality review.
  - Spec review: approved after implementation.
  - Code review: approved after implementation.
  - Verification: context lifecycle tests and full suite passed during task execution.
  - Commit: `2b0691c`
- Task 5: Role Isolation Core
  - Subagent/process: subagent-driven development with spec and quality review.
  - Spec review: approved after implementation.
  - Code review: approved after implementation.
  - Verification: isolation/runner/report tests and full suite passed during task execution.
  - Commit: `a386dff`
- Task 6: Multi-Strategy Benchmark Aggregation
  - Subagent/process: subagent-driven development with spec and quality review.
  - Spec review: approved after implementation.
  - Code review: approved after implementation.
  - Verification: benchmark CLI/tests and full suite passed during task execution.
  - Commit: `50bbb88`
- Task 7: Mock Eval Cases and Documentation
  - Subagent/process: spec reviewer `019f4d0a-69da-7df0-964e-ae02c8676799`, quality reviewer `019f4d0b-0108-7a82-b4d1-41490445274c`.
  - Spec review: issues fixed (`eval-runs/` ignore rule).
  - Code review: issues fixed (README/SPEC evidence wording).
  - Verification: `rag-select` / `compressed-rag` / `isolated-harness` eval all `expected_matches=7`; benchmark `strategies=4, cases=7`; full suite `Ran 190 tests ... OK`.
  - Commit: `8a602cb`
- Task 8: Final evidence and verification
  - Subagent/process: controller final pass.
  - Spec review: plan checklist reconciled against commits.
  - Code review: final reviewer found one Critical issue: RAG retrieval and selected context did not honor `WorkspacePolicy.allowed_read_paths`.
  - Fix: `9b03490` passes the workspace policy into context construction, filters selected files and retrieved chunks by `allowed_read_paths`, and adds a regression test proving a policy-disallowed matching file is not sent to the LLM context or retrieval evidence.
- Verification: full suite `Ran 191 tests ... OK`; benchmark `strategies=4, cases=7`; `rag-select`, `compressed-rag`, and `isolated-harness` eval each reported `expected_matches=7`.
- Commit: `52964d4` for process evidence, `9b03490` for the final review security fix.

## 2026-07-14 Gate 与 HITL 正确性加固（Task 3–8）

- 时间：2026-07-14（Asia/Shanghai）。
- 分支：`feat-gate-hitl-correctness`。
- 触发的 Superpowers 技能：
  - `using-superpowers`：先检查适用技能与执行约束。
  - `executing-plans`：按既有实施计划逐项审计任务 3–8。
  - `using-git-worktrees`：确认当前已有连续未提交工作后，在现有功能分支原地继续，未新建 worktree。
  - `test-driven-development`：对真正暂停、最终 Gate、applying 恢复、覆盖审批、过期摘要、Web revision 冲突和完整 approve/deny 流程逐项执行 RED→GREEN。
  - `verification-before-completion`：完成前重新运行聚焦测试、全量测试和语法检查。
- 关键上下文：课程要求强调“机制必须编码，并能在移除真实 LLM 后由确定性单测验证”；本轮继续使用 `MockLLM`、SQLite 临时库和临时工作区，不访问真实 LLM 或网络。
- 实现摘要：
  - Action payload 按动作类型验证；Runner 使用明确 outcome，并在创建审批后立即返回。
  - 审批队列升级为 schema 2、单调 revision、跨进程锁和 CAS；恢复先 claim 为 `applying`，支持中断后的幂等判定。
  - `finish` 无条件重跑最终 Gate；Web 发布前校验 Gate 绑定的 SHA-256，过期结果返回 `stale_gate_result`。
  - Web 覆盖已有文件默认进入审批；approve/deny 强制携带 `expected_revision`，冲突返回结构化 409，前端刷新后要求重新确认。
  - 新增真实 Web approve/deny→resume 集成测试；扫描全部示例 Checklist，未发现需要迁移的 `unsupported_check` 或 `invalid_checklist_rule`。
- Subagent：本轮未派发 subagent；当前协作策略未授权自动委派，所有实现与复核由主 Agent 完成。
- 人工干预：用户执行 Git/PR；最终功能 commit `e17b8e5`，PR #11，merge `f2b4e88`。
- 学到的教训：旧测试全部通过并不代表计划已完成；必须把计划中的并发、暂停和恢复不变量逐条映射到代码调用点，才能发现“基础类已实现但 Runner/Web 仍绕过 CAS”的缺口。

### 最终差异审查与验证

- 主线程复核了 `runner.py`、`approvals.py`、`web_approvals.py` 和 `web_runs.py` 的状态迁移、CAS 边界与发布顺序；因当前协作规则未授权自动委派，本轮没有派发审查 subagent。
- 最终审查发现并修复三处证据/边界问题：
  - Gate 原先对解码后的文本计算摘要，带 UTF-8 BOM 的文件会与 Web 原始字节校验不一致；现改为对单次安全读取获得的原始字节计算 SHA-256。
  - Web 在摘要检查后重新读取文件生成 HTML/ZIP，存在检查与读取之间的竞态窗口；现要求实际发布的同一份字节再次匹配最终 Gate 摘要，不一致时以 `stale_gate_result` 失败且不写入制品。
  - Runner Trace 原先未记录审批队列 revision；现记录审批请求、`approved -> applying` claim 和终态转换后的 revision。
- 上述修复均先增加会失败的回归测试，再实现最小修复并确认聚焦测试通过。
- 最终本地全量回归：`python -m unittest discover -s tests`，结果为 `Ran 731 tests in 117.018s`、`OK (skipped=20)`；跳过项为既有 Windows 符号链接或平台权限场景。
- 最终语法与差异检查：`python -m compileall -q src tests` 与 `git diff --check` 均通过；Git 仅提示工作区文件未来可能进行 LF/CRLF 转换，没有空白错误。
- Agent 未执行 `git add`、`git commit`、`git push` 或 PR 操作；用户随后提交功能 commit `e17b8e5`，PR #11，merge `f2b4e88`，远端结果已进入最终证据链。

## 2026-07-14 安全凭据存储

- 分支：`feat-secure-credentials`。
- 已确认架构：
  - CLI 只读进程环境变量，且其优先级最高；日常持久化使用系统 keyring，不再读写 `.env`。
  - Web 仅保存 `openai-compatible` 凭据，使用独立 `SPECGATE_WEB_CREDENTIAL_KEY`、AES-256-GCM、12 字节随机 nonce，以及绑定 user/provider/version/key id 的 AAD。
  - 旧 HMAC 状态迁移为 `requires_reentry`；不实现在线密钥轮换。Web 和课程验收仍只运行 MockLLM。
- Superpowers 流程：使用 `executing-plans`、`using-git-worktrees`、`test-driven-development`、`systematic-debugging`，逐任务执行 RED→GREEN；当前功能分支由用户创建，因此在现有工作区继续。
- TDD 证据：
  - CLI RED：旧接口不接受 `store/environ` 注入，且仍要求 `--env-file`；GREEN：`tests.test_credential_store tests.test_credentials tests.test_cli` 共 49 个测试通过。
  - AES-GCM RED：`specgate.web_credentials` 不存在；GREEN：4 个 cipher 测试通过。
  - 数据库 RED：schema 仍为 v1 且没有 `user_credentials`；GREEN：10 个迁移测试通过，包括幂等、回滚和新版本拒绝。
  - Repository/Settings/Runner GREEN：62 个聚焦测试通过。
  - Web API/静态前端 GREEN：77 个测试通过，1 个既有 Windows 权限场景跳过。
- 数据库迁移结果：新库使用 schema v2；v1 的 HMAC 配置清除旧字段并写入 `requires_reentry`，失败事务保持 v1 状态且不留下半成品表。
- 脱敏边界：新增 CLI stdout/stderr/异常 sentinel 回归；Web 响应、普通数据库表和运行 Trace 均验证不含 secret。
- 最终审查修正：README 删除旧 `SPECGATE_WEB_SECRET` 启动示例，统一使用独立主密钥；CLI `credentials set --value` 帮助文本增加命令行历史泄漏风险提示，并完成 RED→GREEN 回归。
- 最终本地全量测试：`python -m unittest discover -s tests`，结果为 `Ran 753 tests in 254.444s`、`OK (skipped=20)`；跳过项为既有 Windows 符号链接或平台权限场景。
- 最终语法、差异和旧接口扫描均通过；旧 `--env-file` 仅保留在“应被 argparse 拒绝”的回归测试中，`hmac_sha256$legacy` 仅保留在数据库迁移测试中。
- 远端结果：功能 commit `fecc5e3`，PR #12，merge `80be31b`；unit-test 与 docker-build 通过，Pages 在合并后因缺少项目依赖失败。
- Agent 未执行任何 Git 写操作；commit、push、PR 和远端 CI 均由用户负责。

### GitHub Pages 合并后热修复

- 现象：安全凭据 PR 的 unit-test 与 docker-build 通过，但合并到 `main` 后 Pages `build-pages` 在 `Regenerate mock demo` 阶段失败。
- 根因证据：Ubuntu 日志显示 `ModuleNotFoundError: No module named 'keyring'`；`ci.yml` 和 Dockerfile 均先执行项目安装，只有 `pages.yml` 直接运行 CLI。
- TDD RED：`tests.test_workflows` 明确失败，提示 Pages workflow 缺少 `python -m pip install -e .`。
- GREEN：在 `Set up Python` 与 `Regenerate mock demo` 之间增加项目依赖安装步骤，聚焦 workflow 测试通过。
- 本地全量回归：`python -m unittest discover -s tests`，结果为 `Ran 754 tests in 317.027s`、`OK (skipped=20)`。
- 用户提交热修复 commit `20c0102`，PR #13，merge `73fbb34`；Pages 恢复通过。失败与修复顺序均保留为交付证据。

## 2026-07-14 Web 运行时并发与恢复加固

- 分支：`feat-web-runtime-hardening`。
- 已确认边界：单 Web 进程、固定 worker、有界队列、协作式取消、worker 认领后开始计算执行超时；排队和人工审批等待不计时；Web 与自动验收只使用 MockLLM。
- Superpowers 流程：
  - 使用 `brainstorming` 和 `writing-plans` 确认设计并生成 12 个任务的实施计划。
  - 使用 `executing-plans` 和 `test-driven-development` 逐项执行 RED→GREEN。
  - 遇到审批恢复组合回归后使用 `systematic-debugging` 追踪 queued 双语义根因。
  - 完成前使用 `requesting-code-review` 做主线程差异审查，并使用 `verification-before-completion` 获取新鲜证据。
  - 当前协作规则未授权自动委派，因此没有派发 subagent；Git 和 PR 操作继续由用户执行。
- 设计与实现：
  - 数据库升级为 schema v3，新增 `cancel_requested_at`、`deadline_at`，连接统一启用 WAL、`synchronous=NORMAL` 和 5 秒 busy timeout，并覆盖 v1→v2→v3 与 v2→v3 迁移。
  - 新增 `WebRuntimeCoordinator`：默认 4 worker、32 排队槽位、每用户 4 个活动 run、60 秒执行超时；配置严格校验，容量预留确保 429 前不创建数据库或目录副作用。
  - Runner 在首次执行、每步开始、LLM/工具/Gate 返回、HITL resume 和多角色边界调用通用 `stop_check`。
  - Web run 增加取消、超时、发布前停止、产物清理与 CAS 竞争处理；取消 API 覆盖 queued、running 和 needs_approval。
  - 首次运行和 HITL resume 共用有界调度器；启动时按顺序补入持久化 queued，遗留 running 收敛为失败，cancel_requested 收敛为已取消。
  - 应用关闭先冻结调度并取得 pending/running 快照，再写入数据库取消状态，最后共享同一个 5 秒 join deadline；旧 `app.state.run_threads` 和应用层每 run 线程入口已移除。
  - 前端增加取消按钮、`cancel_requested` 持续轮询，以及初始化、发布、取消和超时的中文状态与告警样式。
- TDD 与调试证据：
  - 配置、schema、容量、超时、恢复、关闭、API 和前端契约均先出现缺少接口或状态不符的预期失败，再实现最小行为。
  - 高风险组合首次运行暴露旧测试回归：普通 queued 首次运行被 `resume_run_once()` 当作审批恢复并抛出错误。根因是异步恢复后 queued 同时承担首次执行和 resume 排队语义；修复后的测试同时证明“有已决定审批候选的 queued run 可以恢复”和“普通 queued run 幂等无操作”。
  - 清理旧线程测试桩后，Web 应用测试为 `Ran 46 tests ... OK (skipped=1)`。
  - 高风险组合测试为 `Ran 247 tests in 74.289s`、`OK (skipped=1)`。
  - 最终全量测试为 `Ran 799 tests in 129.557s`、`OK (skipped=20)`；命令中的非法 `unsafe` profile argparse 输出来自预期拒绝测试，不是失败。
  - `python -m compileall -q src tests` 无输出且退出码为 0；`git diff --check` 退出码为 0，仅显示 Windows 工作区的 LF→CRLF 提示，没有空白错误。
- 未执行 `git add`、`git commit`、`git push` 或 PR 操作；用户提交功能 commit `e5fc981`，PR #14，merge `49f66a2`，远端 CI 与 Pages 通过。

## 2026-07-15 Runner 运行配置接线

- 分支：`feat-runtime-config-wiring`。
- 已确认边界：Web 与自动验收只使用 `MockLLM`；不接真实 LLM；Git 暂存、提交、push 和 PR 由用户执行；本轮按用户选择使用 Inline Execution，没有派发 subagent。
- Superpowers 流程：使用 `executing-plans`、`test-driven-development` 和 `systematic-debugging` 逐项执行；完成前使用 `requesting-code-review`、`verification-before-completion` 和 `finishing-a-development-branch`。
- 已确认七项配置：`governance_profile`、`context_strategy`、`max_steps`、`context_budget_chars`、`retrieval_top_k`、`retrieval_budget_chars`、`compression_max_tool_result_chars`。数值默认值分别为 5、12000、6、9000、1200，合法范围由 `RunRuntimeConfig` 统一维护。
- 数据库与不变量：
  - schema 升级为 v4；v3→v4 在单事务内增加 Settings 数值列和 `runs.runtime_config_json`，旧 run 回填 `source=migration`，失败时完整回滚。
  - 创建 run 在 `BEGIN IMMEDIATE` 事务内读取 Settings 并写入 `source=created` 的规范化 JSON，Settings 并发更新不能产生混合字段快照。
  - 首次执行、HITL resume 和 queued 重启补入不再读取最新 Settings，只解析 run 自身快照；Trace 记录 `runtime_config_applied` 及 initial/resume phase。
- Runner 接线：Context builder 和 AgentRunner 显式接收上下文字符预算、`RetrievalConfig` 和 `CompressionConfig`；普通与多角色路径共用同一配置，同时保留安全关键段和 allowed-read 策略。
- TDD 与调试证据：
  - 配置核心 6 项测试通过；schema v4 迁移组合 17 项测试通过；Settings/API 组合 54 项测试通过（跳过 1 项）。
  - 首次执行/resume 快照组合 78 项测试通过。
  - 非法快照测试先暴露错误断言：数据库保留损坏原文用于取证，但错误信息、Debug/API 和 Trace 不得回显。修正测试契约及错位断言后，针对性 2 项与 Web 高风险组合 142 项测试通过（跳过 1 项）。
  - Debug/Audit/Settings 新增 3 条契约测试先因字段和页面能力缺失失败；最小实现后相关组合 100 项测试通过（跳过 1 项）。损坏快照仅返回 `invalid_runtime_config`，不回显原始 JSON sentinel。
- 主线程代码审查发现 queued resume 在“API 已校验、worker 尚未认领”期间若快照损坏，解析异常会逃出并使 run 持续保持 queued；同时首次执行解析失败可能覆盖并发取消终态。新增两条 RED 回归后，以带期望状态的事务更新收敛为 `failed / invalid_runtime_config`，并保留已发生的取消状态；相关 4 条针对性测试和 144 条 Web 恢复组合测试通过（跳过 1 项）。
- 最终高风险聚焦测试：`Ran 282 tests in 91.153s`、`OK (skipped=1)`。
- 最终全量测试：`Ran 822 tests in 131.279s`、`OK (skipped=20)`；命令中的非法 `unsafe` profile argparse 输出来自预期拒绝测试，不是失败。
- `python -m compileall -q src tests` 与 `node --check src/specgate/web_static/app.js` 均无输出且退出码为 0；`git diff --check` 退出码为 0，仅有 Windows LF→CRLF 提示，没有空白错误。
- 未执行 `git add`、`git commit`、`git push` 或 PR 操作；用户提交功能 commit `a523137`，PR #15，merge `f45e73a`；合并后 main CI #43 与 Pages #26 通过。

## 2026-07-15 最终交付材料与验证证据同步

- 分支：`docs-final-evidence-sync`，基线 `main@f45e73a`。
- Superpowers：`brainstorming`、`writing-plans`；执行阶段使用 `executing-plans`、`test-driven-development`，完成前使用 `requesting-code-review` 与 `verification-before-completion`。
- 人工决策：采用“权威证据矩阵 + 仓库内 Actions 截图”；`REFLECTION.md` 不由 Agent 改写，只提供事实核对表；Git/PR 由用户执行。
- 课程/PPT 对齐：目标定义、测试基础设施、PR/CI、持续文档同步和如实保留失败—修复历史共同构成 Harness 工程证据。
- 范围：只修改文档、证据截图和文档一致性测试，不修改生产代码行为；所有复现继续使用 MockLLM/StubLLM。
- RED 基线：功能基线 `Ran 822 tests in 133.849s`、`OK (skipped=20)`；新增文档契约最初因证据矩阵、截图、README 章节及过期描述缺失而按预期失败。
- 远端链：Gate/HITL `e17b8e5` / PR #11 / `f2b4e88`；安全凭据 `fecc5e3` / PR #12 / `80be31b`；Pages 热修复 `20c0102` / PR #13 / `73fbb34`；Web Runtime `e5fc981` / PR #14 / `49f66a2`；Runtime Config `a523137` / PR #15 / `f45e73a`。
- 核心机制复现：Guardrail 1 项、Gate 反馈 1 项、HITL 暂停/恢复 2 项、security/multi-strategy benchmark smoke 2 项全部通过。
- 高风险聚焦套件：`Ran 181 tests in 7.758s`、`OK (skipped=5)`。
- 最终全量回归：`Ran 829 tests in 133.150s`、`OK (skipped=20)`；非法 `unsafe` profile 的 argparse 输出来自预期拒绝测试。
- 主线程最终审查发现并修正 1 个 Important 文档问题：Gate/HITL 阶段末尾仍称等待远端 CI，现已回填 `e17b8e5` / PR #11 / `f2b4e88`；其余旧术语扫描命中均为明确的历史或迁移说明。

## 2026-07-15 后端审计安全边界加固

- 分支：`fix-backend-audit-hardening`，基线 `main@e73e937`；Git 暂存、提交、推送和 PR 仍由用户执行。
- 产品边界：Web 与课程验收继续默认使用 MockLLM；用户配置 API Key 后启用真实 LLM 的能力留到 `feat-real-llm-web-integration`。
- Superpowers：使用 `brainstorming`、`writing-plans`、`executing-plans`、`test-driven-development` 和 `systematic-debugging`；按用户选择采用 Inline Execution，没有派发 subagent。
- RED→GREEN：
  - 安全追加接口缺失导致 ImportError；实现 `append_workspace_text()` 并迁移 Trace 后，Task 1 的 96 项回归通过（跳过 8 项平台能力测试）。
  - Memory、Report、Runner 未调用安全边界的三个跨平台测试先失败；迁移后 Task 2 的 98 项回归通过（跳过 5 项）。
  - Tool、Gate 与 Runner 的非法 UTF-8 用例均先抛出 `UnicodeDecodeError`；修复同时发现 Context artifact summary 的直接读取，统一安全读取后 112 项回归通过（跳过 6 项）。
  - Provider 异常先回显任意正文哨兵，CLI 先回显密钥；丢弃正文并纵深脱敏后 LLM/CLI 46 项回归通过。
  - Web 架构测试先证明 `start_run_background` 仍存在；删除后 Web runtime/run/app/approvals 共 145 项通过（跳过 1 项）。
- 系统调试：第一次全量 `Ran 845 tests` 时，Web debug 把安全重置的空 evidence `{}` 返回给前端，破坏既有 `null` 契约；在 `_read_json_evidence()` 边界规范化空对象后，原失败测试及 `tests.test_web_debug` 20 项通过。
- 定向安全回归：`Ran 422 tests in 153.419s`、`OK (skipped=17)`。
- 主线程审查补充远端控制 HTTP reason 与 `fp=None` 场景，测试先回显 reason 哨兵，再改为标准库状态原因并安全关闭可选响应流；最终全量回归：`Ran 846 tests in 216.617s`、`OK (skipped=27)`。新增跳过项均为 Windows 当前无符号链接权限的真实攻击测试，另有既有平台跳过。
- 本阶段未访问真实 LLM 或外部模型网络，也未执行任何 Git 写操作。

## 2026-07-15 Web 真实 LLM 接入

- 分支：`feat-real-llm-web-integration`，基线 `main@8d30ca5`；用户负责 Git、commit、push 与 PR。
- 产品决策：默认 MockLLM；完整 API key、Base URL、Model 只影响新 run；真实模式失败不降级。真实模型只生成严格 JSON Action，Harness 继续负责路径策略、HITL、Gate 与发布 SHA-256。
- 安全边界：schema v5 冻结 `llm_config_json`；每次调用重查凭据 fingerprint；精确公网 HTTPS 白名单、DNS 固定 IP、TLS SNI/Host、禁止重定向/代理、有界重试和响应。
- TDD：前端模型设置契约先因缺少字段、按钮、模式提示与连接测试函数而 RED；实现后 `tests.test_web_static` 33 项通过，Node 语法检查通过。
- TDD：DNS 饱和测试先因 `PublicDNSResolver` 缺少 `max_pending` 而 RED；新增固定待处理容量后 `tests.test_llm_transport` 通过。resolver canary 首先出现在格式化异常链中；抑制底层 cause 后回归通过。
- 安全回归：新增无真实 DNS/socket 守卫、响应读取中取消、真实 Provider 认证失败不降级且不落盘 canary。高风险组合 `Ran 318 tests in 115.002s`、`OK (skipped=3)`。
- Task 12：材料契约首次出现 20 个预期失败，定位 schema v4、Web 仅 Mock、真实模型安全链和证据路径等过期事实；同步 SPEC、README、部署、walkthrough、证据矩阵与事实核对后，材料/工作流契约 9 项通过。
- 最终验证：全量 `Ran 896 tests in 216.620s`、`OK (skipped=27)`；compileall、Node 语法、材料契约与 `git diff --check` 退出码均为 0。凭据扫描命中均为测试哨兵、攻击 fixture、历史计划示例或主密钥占位符。
- 当前状态：Task 1–12 完成。全程未访问真实 Provider，也未执行 Git 写操作；远端 commit、PR、CI 与部署证据等待用户实际操作后补充。

## 2026-07-16 最终合规阶段补充冷启动

- Agent 类型与环境：Claude Code v2.1.70 无法连接 `api.anthropic.com`，且用户没有可用 Anthropic 服务条件；OpenCode 的官方签名/校验 Windows x64 二进制在本机无法加载，本机无可用 WSL distribution；Gemini CLI 0.50.0 可启动，但用户账户没有 Gemini Code Assist 使用权限，未能执行任务。
- 会话隔离：用户改用全新独立 Gemini Web 会话，只上传 `SPEC.md` 与 `docs/superpowers/plans/2026-07-16-final-delivery-compliance.md`，没有提供聊天历史、Agent memory 或其他仓库文件。
- 尝试任务：Gemini Web 尝试任务 2“同步当前发布版本与证据链”和任务 3“增加完整的直接依赖许可证表”。
- 暂停与问题：任务 2 在步骤 1 和步骤 3、任务 3 在步骤 1 和步骤 4 暂停，因为缺少当前完整文件内容。Gemini Web 明确请求 `tests/test_final_evidence.py`、`docs/FINAL_EVIDENCE_MATRIX.md`、`docs/FINAL_SUBMISSION_CHECKLIST.md`、`docs/REFLECTION_FACT_CHECK.md`、`PLAN.md`、`AGENT_LOG.md`、`README.md`。
- 实际产出：Gemini Web 给出任务 2 与任务 3 的骨架补丁草案，明确声明没有本地 shell、没有可供任务使用的外部网络工具，也无法直接操作工作区文件；没有修改任何文件，也没有运行任何测试。该草案未被记录为已应用，整个尝试约 3 分钟。
- 计划修订：最终合规实施计划增加“执行环境前提”，`SPEC.md` 增加交付材料 Agent 执行环境边界；不再上传七个目标文件，缺少上下文本身作为能力边界证据保留，实际修改、TDD 和 Git 操作交由本地 Subagent。
- 人工参与：用户完成工具选择、Gemini Web 独立会话创建、两个文件上传、结果转交，并决定保留隔离边界、不再上传七个目标文件。
- 追溯边界：本记录是最终合规阶段的补充冷启动验证，不替代 2026-07-08 的早期 SPEC/PLAN 审查，也不声称 MVP 实现前做过完整实现试跑。

## 2026-07-16 最终交付合规修复：任务 2 发布证据链同步

- Agent 与工作区：由本地 Subagent 在独立 worktree `final-delivery-implementation` 和分支 `codex/final-delivery-compliance-impl` 实施，起点为 `89fef8d5570916aaf194bdcd4a7b8aa1e004d5c1`；未修改主工作区或 `src/specgate/` 生产代码。
- TDD RED：先扩展 `test_release_chain_and_screenshot_links_are_recorded` 并新增 PR #20 快照契约；聚焦命令结果为 `Ran 2 tests in 0.002s`、`FAILED (failures=4)`，失败原因是证据矩阵缺少 PR #18、#19、#20 链接，且快照不含 `main@c39d101`。
- TDD GREEN：最小同步权威证据矩阵与关联事实材料后，同一聚焦命令结果为 `Ran 2 tests in 0.001s`、`OK`。
- 聚焦验证：`python -m unittest tests.test_final_evidence` 结果为 `Ran 10 tests in 0.008s`、`OK`；`git diff --check` 退出码为 0，只有 Windows 工作副本的 LF→CRLF 提示，没有 whitespace error。
- 事实口径：审查起点为 PR #20 合并后的 `main@c39d101`，完整回归证据为 `Ran 908 tests in 210.559s`、`OK (skipped=27)`；`896` 项结果仅保留为 2026-07-15 Web 真实 LLM 接入分支的历史阶段记录。
- 学生归属：只更新 `docs/REFLECTION_FACT_CHECK.md` 中供学生核对的事实，没有修改 `REFLECTION.md` 或代写观点。
- 人工/远端边界：本任务只核对本地 Git 历史中 PR #18 至 PR #20 的功能 commit、merge commit 与 PR 编号；未打开或修改远端 PR，未核对 PR #20 合并后 CI/Pages，未生成或伪造新截图，这些项目继续标记为待人工核对。
- 质量审查测试加固：新契约在正确材料上直接通过，因此执行可控 mutation：临时将第 5 节 PR #20 同行 merge SHA 从 `c39d101` 改为 `c39d102`。精确行契约因期望元组计数为 0 而失败（`Ran 1 test`、`FAILED (failures=1)`）；随即恢复 `c39d101` 后同一测试通过，错误 mutation 未进入提交。
- 质量审查验证：PR 表格精确行、快照语义和跨材料一致性 3 项测试结果为 `Ran 3 tests in 0.002s`、`OK`；完整 `tests.test_final_evidence` 结果为 `Ran 12 tests in 0.009s`、`OK`，`git diff --check` 退出码为 0。

## 2026-07-16 最终交付合规修复：任务 4 Open Design 流程偏离

- Agent 与工作区：由本地 Codex Subagent 在独立 worktree `final-delivery-implementation` 实施，起点为 `01cae8ce8ee3b0578bf74b4ef90354dc9a23140c`；未修改主工作区。
- TDD RED：先新增 `test_spec_records_the_actual_open_design_decision`，指定聚焦测试结果为 `Ran 1 test in 0.001s`、`FAILED (failures=1)`；失败原因为 `SPEC.md` 尚不包含 `Open Design`，符合预期。
- TDD GREEN：在 `SPEC.md` 最小增加真实流程偏离决策并同步 README 后，聚焦测试结果为 `Ran 1 test in 0.000s`、`OK`；完整 `tests.test_final_evidence` 结果为 `Ran 15 tests in 0.012s`、`OK`。
- 决策同步：当前 WebUI 早期实现使用项目自定义的轻量界面样式，未采用 Open Design 设计系统或 skill；原因是交互式 Web 产品面在最初 CLI 与静态报告范围之后加入，当时没有重新执行前端设计系统选型。项目如实记录课程推荐流程偏离，不追溯性声称已经采用 Open Design。
- 变更边界：本任务只同步测试与事实材料，不借最终材料修复重做 UI，未修改 `src/specgate/`、任何 UI 生产实现、产品功能规范或部署状态。
- 人工确认范围：仅核对跨文档措辞是否一致、是否如实保留历史偏离以及是否没有生产代码变化；本任务不把该核对表述为重新完成前端选型、UI 重构或视觉验收。后续若重构 UI，将先选择并记录设计系统与 skill。

## 2026-07-16 最终交付合规修复：任务 5 交付状态边界

- Agent 与工作区：由本地 Codex Subagent 在独立 worktree `final-delivery-implementation` 实施，起点为 `63804102d9c11448941ed967756d724263dcf89f`；未修改主工作区或 `src/specgate/`。
- TDD RED：先新增 `test_submission_docs_do_not_claim_public_backend_or_registry`，指定聚焦测试结果为 `Ran 1 test in 0.006s`、`FAILED (failures=5)`；失败原因是提交材料缺少公开静态入口、公网交互后端、公开 registry 与待完成状态的拆分，且仍包含 `公开 WebUI URL | 已完成`。
- TDD GREEN：最小修正文档边界后，最新聚焦测试结果为 `Ran 1 test in 0.001s`、`OK`；完整 `tests.test_final_evidence` 结果为 `Ran 16 tests in 0.014s`、`OK`，`git diff --check` 退出码为 0，只有 Windows LF→CRLF 提示，没有 whitespace error。
- 状态拆分：公开静态评审入口、本地交互式 WebUI、Docker 本地与 CI 构建标记为已完成；公网交互式 Web 后端和公开容器 registry 标记为待完成。README 与 SPEC 明确发布镜像不等于部署服务。
- 部署与发布边界：本任务未部署公网服务、未发布容器镜像，也未把 `Dockerfile`、CI smoke 或 GitHub Pages 当作相关完成证据。
- 人工确认范围：PR #20 合并后的当前远端 CI、Pages 与新截图继续保留给任务 6 人工门禁；本任务只核对本地材料的状态一致性，不声称已完成远端核验。

### 任务 5 质量审查修复

- 审查验证：原边界测试只拼接两份文档全文查找短语，不能证明目标表格中的名称唯一、状态精确或数据列数正确；提交清单还把历史截图与 PR #20 后待核验截图泛化为同一条“已完成”。
- TDD RED：先将测试改为解析两份文档的指定课程交付物章节和唯一 Markdown 表格，精确检查五类交付状态、行唯一性、表头/列数及旧行拒绝；聚焦结果为 `Ran 1 test in 0.003s`、`FAILED (failures=2)`，仅因两条截图状态尚未拆分。
- TDD GREEN：把清单拆为“历史 CI/Pages 截图（截至 PR #15/#17）—已完成”和“PR #20 后 CI/Pages 与新截图—待核验”后，聚焦结果为 `Ran 1 test in 0.001s`、`OK`。
- 边界保持：任务 6 的远端人工核验门禁不变；本次未修改生产代码，未部署、未发布镜像、未 push 或创建 PR。

## 2026-07-16 最终交付合规修复：任务 6 远端证据门禁

- Agent 与工作区：由本地 Codex Subagent 在独立 worktree `final-delivery-implementation` 实施，起点为 `41aa125052262bf9f5295452f88619d99069cf6d`；未修改主工作区或 `src/specgate/` 生产代码。
- 人工 PR 归属：用户编辑并完成 PR #18、PR #19、PR #20 的“执行归属”；主线程只读复核三份描述均包含 OpenAI Codex、人工参与与自动测试边界。本地 Subagent 没有打开或编辑远端 PR，也没有执行远端写入。
- 人工 Actions 证据：用户提供 `YuGarden404/SpecGate` Actions 列表截图；截图显示 PR #20 合并标题，以及 `main@c39d101` 的 CI #53 与 Pages #31 为绿色成功。主线程只读复核 CI #53 的 `unit-test`、`docker-build` 和 Pages #31 的 `build-pages`、`deploy-pages` 均成功。
- 截图处理：仅将用户指定的合格源图复制为 `docs/evidence/github-actions-pr20-final.png`，未纳入其余六张截图，也未修改或拼接图片；检查结果为 PNG 签名有效、343772 字节、2557×1491，未见凭据或账户敏感信息。
- TDD RED：把新截图加入 `SCREENSHOTS` 后，指定两项测试结果为 `Ran 2 tests in 0.032s`、`FAILED (failures=1, errors=1)`；失败原因分别是 PNG 不存在和证据矩阵未引用。增强当前发布状态契约后的单项测试结果为 `Ran 1 test in 0.003s`、`FAILED (failures=1)`，失败原因是任务 6 日志章节尚不存在。
- TDD GREEN：加入真实截图、矩阵链接与远端事实后，计划指定的两项截图/链接测试结果为 `Ran 2 tests in 0.002s`、`OK`；远端状态契约也纳入 PR 归属、四个 job 和部署边界检查。
- 完整材料验证：第一次运行暴露任务 5 契约仍把 PR #20 后截图固定为“待核验”；根因是旧阶段常量未随已完成的人工门禁更新。仅把该截图证据状态改为“已完成”后，部署边界单项测试结果为 `Ran 1 test in 0.001s`、`OK`，完整 `tests.test_final_evidence` 结果为 `Ran 16 tests in 0.012s`、`OK`；公网后端与公开 registry 的“待完成”断言保持不变。
- 部署边界：CI #53、Pages #31 与截图只证明自动测试、Docker CI 构建和静态 Pages 发布链成功；公网交互式 Web 后端与公开容器 registry 仍待后续独立阶段完成。本任务未部署服务、未发布镜像、未 push 或创建 PR。
