# SpecGate 第二阶段设计：AgentOS / Superpowers 对齐层

## 1. 背景

SpecGate 已经完成静态 HTML Coding Agent Harness 的 MVP，并补齐了上下文管理、安全快照和工具注册表三条主线的第一阶段能力。

课程 Lab 9-12 的重点不是要求所有方向都做满，而是要求项目能说明自己接入了 AgentOS 栈的哪一层。当前项目最适合先接入 Lab 10 Skill：把 SpecGate 的运行方法沉淀成可复用流程。Lab 9 MCP、Lab 11 Hook、Lab 12 AgentPack 可以做取舍说明，避免把 MVP 拉向浏览器自动化或复杂平台。

## 2. 目标

本阶段目标是补齐课程对齐证据，而不是扩张核心 harness 能力：

- 新增一个 SpecGate 专用 Skill，描述静态 HTML 任务的受控执行流程。
- 新增 Lab 9-12 对齐文档，说明哪些内容已接入、哪些暂不做、原因是什么。
- 更新 README 和 AGENT_LOG，让评审能快速看到“上下文、安全、工具、Skill 对齐”的关系。
- 保持真实 LLM 接入后置，当前仍以 Mock LLM 作为可复现测试主路径。

## 3. 非目标

本阶段不做：

- 不接入真实 LLM provider。
- 不新增 MCP、Browser、Playwright 或 shell 工具。
- 不实现 pre-commit hook。
- 不实现 AgentPack 打包或部署。
- 不改变现有 CLI、runner、Gate、policy、context selector 和 Tool Registry 行为。

## 4. 设计

新增仓库内 Skill：

```text
skills/specgate-static-html-harness/SKILL.md
```

它是课程交付物，不默认安装到本机 Codex 全局技能目录。内容聚焦：

- runtime 输入：`TASK_SPEC.md`、`CHECKLIST.md`、`index.html`、`specgate.toml`。
- context 选择：优先任务文件，跳过 `runs/`、`reports/`、缓存和二进制文件。
- 工具边界：只允许当前 Tool Registry 中的 `read_file`、`write_file`、`replace_file`、`list_files`、`finish`。
- 安全边界：继续依赖 `WorkspacePolicy` 和文件快照保护。
- 验证方式：单元测试与 `run-mock-demo`。

新增 Lab 对齐文档：

```text
docs/AI4SE_Lab_9_12_Alignment.md
```

文档说明：

- Lab 10 Skill 是本阶段实际接入方向。
- Lab 9 MCP 暂不做，因为当前项目选择静态 Gate，而不是浏览器自动化。
- Lab 11 Hook 暂作为后续方向，因为可用确定性脚本加强提交前质量底线。
- Lab 12 AgentPack 暂作为后续方向，因为当前先交付本地 harness 和静态报告，不做平台化部署。

## 5. 验证

本阶段主要是文档和 Skill 交付，但仍需要验证：

- Skill frontmatter 通过 `quick_validate.py`。
- 全量单元测试通过。
- mock demo 通过。
- 工作区没有未解释的运行产物改动。

## 6. 风险

- 如果把 Lab 9 MCP 做进来，会明显扩大范围，并与“不做 Playwright / 不做浏览器自动化”的 MVP 边界冲突。
- 如果现在接真实 LLM，会引入 API key、网络、非确定性输出和成本问题，反而削弱当前测试可复现性。
- 如果 Skill 写得太宽，会变成泛泛的提示词；因此本阶段 Skill 只服务 SpecGate 静态 HTML 任务。
