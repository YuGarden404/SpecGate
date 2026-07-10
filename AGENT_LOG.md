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
  - Code review: final verification before completion.
  - Verification: full suite `Ran 190 tests ... OK`; benchmark `strategies=4, cases=7`; `git status --short --branch --ignored` shows only process docs modified plus ignored local artifacts.
  - Commit: final process-evidence commit.
