---
name: specgate-static-html-harness
description: "当处理 SpecGate 静态 HTML 任务时使用：任务包含 TASK_SPEC.md、CHECKLIST.md、可选 index.html，并需要通过受控 Coding Agent Harness 完成上下文选择、注册工具调用、安全护栏、Gate 反馈、trace 日志和静态报告。"
---

# SpecGate 静态 HTML Harness

## 目的

使用这个 Skill 时，应把 SpecGate 任务当作一个受控的 Coding Agent Harness 流程，而不是普通的自由编码任务。

目标任务通常是一个静态 HTML 工作区，包含：

- `TASK_SPEC.md`：用户侧页面需求。
- `CHECKLIST.md`：确定性验收清单。
- `index.html`：已经生成或需要修复的静态 HTML 产物。
- `specgate.toml`：允许使用的工具和文件白名单配置。

## 工作流

1. 读取 `TASK_SPEC.md`、`CHECKLIST.md`、`specgate.toml`，以及已有的 `index.html`。
2. 将根目录的 `SPEC.md`、`PLAN.md` 等文件视为 harness 项目设计文档，不要当作运行时任务输入。
3. 优先从任务相关文件构建上下文。优先选择 `TASK_SPEC.md`、`CHECKLIST.md`、`README.md`、`index.html`；跳过 `runs/`、`reports/`、`.git/`、缓存目录和二进制文件。
4. 只使用 SpecGate Tool Registry 中注册过的工具：
   - `read_file`
   - `write_file`
   - `replace_file`
   - `list_files`
   - `finish`
5. MVP 路径中不要引入 shell、浏览器自动化、网络工具、MCP 工具或任意文件系统访问。
6. 写入文件前必须遵守 `WorkspacePolicy` 白名单和文件快照保护。
7. 每次写入后运行静态 HTML Gate，并把失败信息反馈给下一轮 action。
8. 当 Gate 通过，或达到配置的最大步数后停止。
9. 保留可追踪证据：一次运行应留下 trace 事件和静态报告。

## 决策规则

- 如果用户要求生成或修复静态 HTML 页面，通过 `TASK_SPEC.md` 和 `CHECKLIST.md` 执行。
- 如果用户询问项目架构，阅读根目录的 `SPEC.md`、`PLAN.md`、`SPEC_PROCESS.md`、`AGENT_LOG.md`。
- 如果用户需求需要 shell、Playwright、Browser MCP 或宽泛文件访问，除非项目范围已经明确改变，否则标记为超出当前 MVP 边界。
- 如果运行期间文件被外部修改，不要覆盖它；报告安全拦截结果。
- 如果用户要求真实 LLM provider，保持 `mock` 为默认路径，并要求显式 provider 配置。

## 验证方式

常规项目验证运行：

```powershell
$env:PYTHONPATH="src"
python -m unittest discover -s tests -v
```

内置 demo 运行：

```powershell
$env:PYTHONPATH="src"
python -m specgate.cli run-mock-demo examples/knowledge_nav
```

预期结果：

- 单元测试通过；
- `examples/knowledge_nav/index.html` 存在；
- `examples/knowledge_nav/runs/latest/trace.jsonl` 存在；
- `examples/knowledge_nav/reports/latest/index.html` 存在。

## 汇报格式

总结一次 SpecGate 运行时，说明：

- 选择了哪些上下文，跳过了哪些运行产物；
- model action 数量和 tool call 情况；
- 是否出现 guardrail 拦截；
- Gate 结果和修复提示；
- 最终 HTML 产物路径；
- 静态报告路径或发布 URL。
