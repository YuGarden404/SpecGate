# SpecGate 最终提交检查清单

## 1. 项目定位

SpecGate 是 AI4SE 期末项目 A 类选题 `Coding Agent Harness`。项目目标不是做一个复杂网页应用，而是从零实现一个小型 coding agent harness，展示如何把 LLM 的输出约束在可控、可测、可追踪、可修复的工程闭环中。

MVP 范围：

- Python CLI harness。
- `MockLLM` 默认路径。
- 静态 HTML 生成/修复任务。
- 严格 JSON Action Protocol。
- 文件工具白名单与 WorkspacePolicy。
- Checklist/Gate 反馈闭环。
- Context Manifest、Tool Registry、文件快照保护。
- trace 日志和静态 Web 报告。

明确不做：

- 不开放 shell。
- 不做 Playwright。
- 不做复杂前端。
- 不默认接入真实 LLM。
- 不使用现成 agent framework 作为 harness core。

## 2. 课程交付物对照

| 要求 | 状态 | 对应文件或证据 |
| --- | --- | --- |
| 项目规约 | 已完成 | `SPEC.md` |
| 实施计划 | 已完成 | `PLAN.md`、`docs/superpowers/plans/` |
| 规约过程记录 | 已完成 | `SPEC_PROCESS.md` |
| 开发日志 | 已完成 | `AGENT_LOG.md` |
| 学生反思 | 已完成 | `REFLECTION.md` |
| 源代码 | 已完成 | `src/specgate/` |
| 单元测试 | 已完成 | `tests/` |
| Mock LLM 测试路径 | 已完成 | `src/specgate/llm.py`、`tests/test_runner.py`、`tests/test_cli.py` |
| GitLab CI 文件 | 已完成 | `.gitlab-ci.yml` 包含 `unit-test` job |
| GitHub Actions | 已完成 | `.github/workflows/ci.yml`、`.github/workflows/pages.yml` |
| Docker 分发 | 已完成 | `Dockerfile` |
| 静态 Web 报告 | 已完成 | `examples/knowledge_nav/reports/latest/index.html` |
| 公开 WebUI URL | 已完成 | `https://yugarden404.github.io/SpecGate/` |
| AgentOS / Superpowers 对齐 | 已完成 | `skills/specgate-static-html-harness/SKILL.md`、`docs/AI4SE_Lab_9_12_Alignment.md` |
| Lab 11 Hook sample | 已完成 | `hooks/pre-commit.sample`、`tests/test_hook_sample.py` |

## 3. 核心机制对照

| 机制 | 实现位置 | 说明 |
| --- | --- | --- |
| Action 协议 | `src/specgate/actions.py` | 只接受严格 JSON object，拒绝 Markdown code fence、缺字段和非法参数。 |
| 工具管理 | `src/specgate/tool_registry.py`、`src/specgate/tools.py` | Tool Registry 描述工具名称、权限、参数和结果，dispatcher 只执行注册工具。 |
| 安全边界 | `src/specgate/policy.py`、`src/specgate/snapshot.py` | 阻止未知动作、路径越界、allowlist 外写入和运行期间外部修改覆盖。 |
| 上下文管理 | `src/specgate/context_selector.py`、`src/specgate/context.py` | 优先选择任务文件，跳过运行产物，生成 Context Manifest。 |
| Gate 闭环 | `src/specgate/gate.py`、`src/specgate/runner.py` | Gate 失败摘要回灌给下一轮，驱动 MockLLM 生成修复动作。 |
| trace 与报告 | `src/specgate/trace.py`、`src/specgate/report.py` | 记录运行事件并生成静态报告。 |
| 凭据边界 | `src/specgate/credentials.py` | Mock 模式不需要凭据，真实 provider 默认 fail-closed。 |
| 提交前防线示例 | `hooks/pre-commit.sample` | 可选 Hook sample，用于疑似密钥扫描、必要文件检查和测试提示。 |

## 4. 推荐评审路径

1. 阅读 `README.md` 的“评审快速入口”。
2. 阅读 `SPEC.md` 前 5 节，确认项目定位和 MVP 边界。
3. 阅读 `docs/PROJECT_WALKTHROUGH.md`，按演示脚本理解一次完整运行。
4. 打开公开页面：
   - WebUI 首页：`https://yugarden404.github.io/SpecGate/`
   - demo 页面：`https://yugarden404.github.io/SpecGate/demo/`
   - 运行报告：`https://yugarden404.github.io/SpecGate/report/`
5. 查看测试与 CI：
   - 本地命令：`$env:PYTHONPATH="src"; python -m unittest discover -s tests -v`
   - GitHub Actions 页面中的 CI 和 Pages workflow。
6. 阅读 `REFLECTION.md`，了解人工参与、冷启动验证和方法论反思。

## 5. 本地复现命令

运行单元测试：

```powershell
$env:PYTHONPATH="src"
python -m unittest discover -s tests -v
```

运行 mock demo：

```powershell
$env:PYTHONPATH="src"
python -m specgate.cli run-mock-demo examples/knowledge_nav
```

验证 Skill：

```powershell
$env:PYTHONUTF8="1"
python C:\Users\Lenovo\.codex\skills\.system\skill-creator\scripts\quick_validate.py skills\specgate-static-html-harness
```

构建 Docker 镜像：

```powershell
docker build -t specgate:local .
docker run --rm specgate:local
```

## 6. 当前完成度判断

项目已经达到期末提交的核心要求：

- 有可运行的 harness。
- 有可复现的 mock LLM 闭环。
- 有单元测试和 CI。
- 有 Dockerfile。
- 有静态 WebUI 和公开 URL。
- 有过程文档、计划、反思和日志。
- 有上下文、安全、工具三条工程主线。
- 有 Lab 10 Skill 与 Lab 9-12 取舍说明。

后续可选增强是真实 LLM provider 设计和 AgentPack 草案；Lab 11 Hook sample 已作为可选示例补齐。
