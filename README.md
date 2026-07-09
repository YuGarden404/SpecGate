# SpecGate

SpecGate 是 AI4SE 期末项目的 A 类选题：一个从零实现的小型 `Coding Agent Harness`。

MVP 是 Python CLI harness，使用可注入的 `MockLLM`，围绕静态 HTML 生成/修复任务运行 Checklist/Gate 反馈闭环，并生成静态 Web 报告。

## 两类 SPEC

这里有两个层级，不能混在一起：

- 根目录 `SPEC.md`：课程要求的项目设计文档，说明 SpecGate 这个 harness 项目要做什么。
- 示例任务里的 `TASK_SPEC.md`：SpecGate 运行时读取的 HTML 任务输入，说明这一次要生成什么页面。

也就是说，我们要交付的是 SpecGate harness；harness 的 demo 输入会是类似 `examples/knowledge_nav/TASK_SPEC.md` + `CHECKLIST.md` 的 HTML 设计任务。

## MVP 边界

包含：

- 自实现 agent loop。
- `MockLLM`。
- 严格 JSON Action Protocol。
- 白名单文件工具。
- 确定性 guardrail。
- 静态 HTML Gate。
- 失败反馈驱动的修复闭环。
- 静态 Web 报告。

不包含：

- 不开放 shell。
- 不做 Playwright。
- 不做复杂前端。
- 不使用现成 agent framework 作为 harness core。

## 课程交付物

本仓库最终需要包含：

- `SPEC.md`
- `PLAN.md`
- `SPEC_PROCESS.md`
- `README.md`
- `AGENT_LOG.md`
- `REFLECTION.md`
- 源代码和 mock-LLM 单元测试
- `.gitlab-ci.yml`，其中包含 `unit-test` job
- Docker 分发文件
- 静态 Web 报告部署 URL

## 当前状态

项目已完成 MVP 主链路的核心实现：Action 解析、workspace guardrail、文件工具、静态 HTML Gate、trace/context、`MockLLM` runner 和静态报告生成。

CLI demo、凭据边界、Dockerfile、`.gitlab-ci.yml`、GitHub Actions CI、GitHub Pages workflow 和示例静态报告已补齐。

GitHub Pages 已配置为 GitHub Actions 发布，并已成功部署公开 WebUI。

## 本地测试

```powershell
$env:PYTHONPATH="src"
python -m unittest discover -s tests -v
```

## Mock Demo

```powershell
$env:PYTHONPATH="src"
python -m specgate.cli run-mock-demo examples/knowledge_nav
```

运行后打开：

```text
examples/knowledge_nav/reports/latest/index.html
```

示例任务目录说明：

- `examples/knowledge_nav/TASK_SPEC.md`：运行时用户需求，描述要生成的 HTML 页面。
- `examples/knowledge_nav/CHECKLIST.md`：运行时验收清单，其中 `- 必须包含 ...` 会被 Gate 自动检查。
- `examples/knowledge_nav/index.html`：SpecGate 生成的最终 HTML 产物。
- `examples/knowledge_nav/reports/latest/index.html`：一次运行的静态报告。
- `examples/knowledge_nav/runs/latest/trace.jsonl`：逐步运行日志，每行是一条 JSON 事件。

`site/index.html` 是 GitHub Pages 的公开首页，不是 harness 的运行输入；Pages workflow 会把示例产物复制到公开站点中。

## 上下文管理

SpecGate 的 context pack 会扫描任务目录，并生成 `Context Manifest`。默认优先选择 `TASK_SPEC.md`、`CHECKLIST.md`、`README.md`、`index.html`，跳过 `runs/`、`reports/`、`.git/`、`__pycache__/` 等运行产物或缓存目录，并使用字符预算控制进入 LLM 的内容规模。

## 工具管理

SpecGate 使用 `Tool Registry` 结构化描述可用工具。当前注册的工具包括 `read_file`、`write_file`、`replace_file`、`list_files` 和 `finish`。注册表会进入 context pack，并展示在静态报告中；实际权限仍由 `WorkspacePolicy` 和文件快照保护共同执行。

## AgentOS / Superpowers 对齐

当前阶段优先接入 Lab 10 Skill，而不是扩大到浏览器 MCP 或真实 LLM。仓库内新增 `skills/specgate-static-html-harness/SKILL.md`，把 SpecGate 静态 HTML 任务的上下文选择、工具边界、安全检查、Gate 闭环和报告输出沉淀为可复用流程。

Lab 9-12 的取舍记录见 `docs/AI4SE_Lab_9_12_Alignment.md`。当前结论是：Lab 10 已作为本阶段交付；Lab 9 MCP 暂不做；Lab 11 Hook 和 Lab 12 AgentPack 作为后续候选方向。

## Docker

```powershell
docker build -t specgate:local .
docker run --rm specgate:local
```

已由用户在本机 PowerShell 设置代理环境变量后，完成 `python:3.11-slim` 拉取、镜像构建和容器运行验证。

Mock 模式不需要 API key。真实 LLM 模式尚未作为 MVP 默认能力开放。

## CI

`.gitlab-ci.yml` 包含 `unit-test` job，会运行：

```text
python -m unittest discover -s tests -v
```

因为仓库实际托管在 GitHub，`.github/workflows/ci.yml` 也提供同名 `unit-test` job，并额外执行 Docker 镜像构建检查。

## 已知限制

- MVP 不开放 shell。
- MVP 不做 Playwright。
- MVP 只处理静态单页 HTML 任务。
- WebUI 是静态报告，不是实时 dashboard。

## 安全边界

Mock 模式不需要任何凭据。真实 LLM 支持如果后续加入，必须使用 credential manager，不能打印、记录或提交密钥。`.env` 已被忽略，只能作为本地开发 fallback，并且要说明明文风险。

运行期间，SpecGate 会对允许写入的文件建立快照。`write_file` / `replace_file` 写入前会检查目标文件是否被外部修改；如果用户在 run 期间改过文件，harness 会阻止覆盖并在 trace 中记录 blocked tool result。

## 静态 WebUI

本项目的 WebUI 是一次运行的静态报告，不是复杂前端应用。报告会展示：

- run metadata。
- loop steps。
- model actions。
- guardrail decisions。
- gate results。
- final artifact。

GitHub Pages 已部署地址：

- WebUI 首页：`https://yugarden404.github.io/SpecGate/`
- 知识图谱 demo：`https://yugarden404.github.io/SpecGate/demo/`
- 运行报告：`https://yugarden404.github.io/SpecGate/report/`
