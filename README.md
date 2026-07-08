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

CLI demo、凭据边界、Dockerfile、`.gitlab-ci.yml` 和示例静态报告已补齐。

剩余人工事项：

- GitHub Pages 首次部署后，在仓库设置中确认 Pages source 为 GitHub Actions。

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

## 静态 WebUI

本项目的 WebUI 是一次运行的静态报告，不是复杂前端应用。报告会展示：

- run metadata。
- loop steps。
- model actions。
- guardrail decisions。
- gate results。
- final artifact。

GitHub Pages 部署目标：

- WebUI 首页：`https://yugarden404.github.io/SpecGate/`
- 知识图谱 demo：`https://yugarden404.github.io/SpecGate/demo/`
- 运行报告：`https://yugarden404.github.io/SpecGate/report/`
