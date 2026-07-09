# AI4SE Lab 9-12 对齐说明

## 1. 当前结论

SpecGate 当前已经完成 A 类 Coding Agent Harness 的 MVP，并完成三条工程主线的第一阶段：

- 上下文管理：Context Manifest、优先文件选择、运行产物跳过、预算控制。
- 安全性：WorkspacePolicy、文件 allowlist、凭据 fail-closed、文件快照保护。
- 工具管理：Tool Registry、工具元数据进入 context pack 和静态报告。

Lab 9-12 对本项目有参考价值，但不需要全部实现。本阶段选择优先接入 Lab 10 Skill，把 SpecGate 的静态 HTML harness 流程沉淀为可复用技能。

## 2. Lab 9：MCP

课程方向：浏览器观察步骤、Console / DOM / Network 证据、回灌给 Agent 的上下文。

SpecGate 当前决策：暂不接入。

原因：

- 本项目 MVP 明确不做 Playwright 和复杂浏览器自动化。
- 当前核心贡献是静态 HTML Gate、工具边界、上下文选择和安全控制。
- 引入 Browser MCP 会把项目重心从 harness 机制转向浏览器集成，范围过大。

对齐方式：

- 在文档中明确说明：SpecGate 当前用静态 Gate 和静态报告替代浏览器 MCP 证据链。
- 后续如果需要视觉验证，可以把 MCP 作为可选实验，而不是 MVP 主路径。

## 3. Lab 10：Skill

课程方向：把可复用检查步骤沉淀成 Skill，包括触发条件、输入文件、输出报告格式和禁止事项。

SpecGate 当前决策：本阶段实际接入。

交付物：

```text
skills/specgate-static-html-harness/SKILL.md
```

该 Skill 说明：

- 什么时候使用 SpecGate 静态 HTML harness；
- 运行时应读取哪些任务文件；
- 如何选择上下文；
- 只能使用哪些工具；
- 如何执行 Gate 反馈闭环；
- 如何输出 trace 和静态报告。

价值：

- 证明项目不是只写了 CLI，而是把 agent 工作流沉淀为可复用方法。
- 让后续智能体能按同一套边界执行任务，减少随意发挥。
- 与 Superpowers / AgentOS 的“技能化工程流程”一致。

## 4. Lab 11：Hook

课程方向：密钥扫描、Gate 文件存在性检查、提交前提示。

SpecGate 当前决策：暂不实现，作为下一阶段候选。

原因：

- 当前已有 CI、单元测试、Docker 和静态报告验证。
- Hook 是很合适的质量底线，但不是当前最缺的交付证据。
- 如果现在加入，也应保持为 `hooks/pre-commit.sample`，不强制安装到用户环境。

后续可做：

- 检查 `.env`、API key 字样和疑似密钥。
- 检查 `TASK_SPEC.md`、`CHECKLIST.md`、`specgate.toml` 是否存在。
- 提示运行 `python -m unittest discover -s tests -v`。

## 5. Lab 12：AgentPack / LambdAgentPaaS

课程方向：AgentPack 元数据、权限、模型建议、checker agent 的 system prompt 和 maxSteps。

SpecGate 当前决策：暂不实现，作为后续轻量草案。

原因：

- 当前项目是本地 Python CLI harness，不是部署型 Agent 平台。
- AgentPack 适合在最终展示阶段做“可打包说明”，但现在先不引入额外运行时。

后续可做：

- 新增 `agentpack-draft/manifest.yml`。
- 声明 provider 默认 `mock`。
- 声明工具权限只包含 read/write/list/finish。
- 声明不开放 shell、network、browser、MCP。

## 6. Mock LLM 的支撑作用

当前不急于接入真实 LLM。Mock LLM 支撑的是 harness 机制本身：

- Action JSON 协议是否严格；
- 工具调用是否受 Tool Registry 和 policy 控制；
- Gate 失败是否能反馈给下一轮；
- trace、context pack 和 report 是否完整；
- 安全边界是否可测试、可复现。

真实 LLM 后续可以作为可选 provider，但不应替代 Mock LLM 的默认测试路径。真实 LLM 接入前应先完成 provider 设计，明确凭据管理、非确定性输出和失败重试边界。

## 7. 阶段判断

本阶段选择：

- 做 Lab 10 Skill；
- 做 Lab 9-12 对齐说明；
- 继续保留 Mock LLM 作为默认路径；
- 暂不扩大到 MCP、Hook、AgentPack 和真实 LLM。

这样能在不破坏 MVP 边界的前提下，明确说明 SpecGate 接入了 AgentOS 栈中的“Skill / 可复用流程”这一层。
