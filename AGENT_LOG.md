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
  - GitHub Pages workflow 需要 push 后由远端 Actions 验证。
- 人工参与：
  - 用户需要 push 后在 GitHub Actions 查看 `Pages` workflow，并在 Settings / Pages 确认 source 为 GitHub Actions。
