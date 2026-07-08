# AI for Coding 知识图谱 Demo

## 任务目标

生成一个单文件 `index.html`，作为 SpecGate 的静态 HTML 生成/修复演示页面。页面主题是“AI for Coding 知识图谱”，用于向课程评审者展示：用户给出任务规约和检查清单后，SpecGate 可以控制 LLM 生成符合要求的静态 HTML 页面。

## 目标用户

- 课程评审者：快速看懂 SpecGate 这个 Coding Agent Harness 的核心机制。
- 学生本人：演示 Spec、Checklist、Guardrail、Gate、Feedback Loop 等概念如何串联。
- 后续开发者：理解示例任务目录中哪些文件是输入、哪些文件是输出、哪些文件是运行证据。

## 页面内容要求

页面必须展示不少于 10 个知识节点。建议节点包括：

- Spec 规范文档
- Checklist 检查清单
- Action Protocol
- MockLLM
- Guardrail 护栏
- Tool Dispatcher
- HTML Gate
- Feedback Loop
- Context Pack
- Trace / Report
- Credentials
- Docker / CI

每个知识节点需要包含：

- 节点标题。
- 所属层级，例如规约层、决策层、治理层、执行层、反馈层、记忆层、安全层、分发层。
- 一段面向课程评审者的简短解释。
- 在 SpecGate 项目中的对应文件或模块。
- 与其它节点的关系。

## 交互要求

- 页面顶部需要有清晰标题：`AI for Coding 知识图谱`。
- 页面需要提供搜索框，支持按标题、层级或文件名过滤知识节点。
- 点击任意知识节点后，右侧详情区域需要展示该节点的详细说明、对应文件和关联节点。
- 点击节点时，应高亮该节点，并用视觉方式标出关联节点。
- 页面需要在桌面宽屏和较窄屏幕上都可读。

## 工程约束

- 产物必须是单文件 `index.html`。
- 不依赖外部网络脚本、样式、字体或图片。
- 不使用 React、Vue、npm 构建、Playwright 或复杂前端框架。
- 不包含 API key、token、`sk-` 样式密钥或其它疑似凭据。
- 生成内容必须能通过 SpecGate 的静态 HTML Gate。

## 输出文件

- `index.html`：最终静态 HTML 页面。
- `reports/latest/index.html`：SpecGate 运行报告。
- `runs/latest/trace.jsonl`：SpecGate 运行 trace，用于展示 LLM 输出、工具执行和 Gate 结果。
