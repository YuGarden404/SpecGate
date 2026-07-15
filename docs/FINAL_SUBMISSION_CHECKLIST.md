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
| 学生反思 | 待学生最终事实确认 | `REFLECTION.md`、`docs/REFLECTION_FACT_CHECK.md` |
| 源代码 | 已完成 | `src/specgate/` |
| 单元测试 | 已完成 | `tests/` |
| Mock LLM 测试路径 | 已完成 | `src/specgate/llm.py`、`tests/test_runner.py`、`tests/test_cli.py` |
| GitLab CI 文件 | 已完成 | `.gitlab-ci.yml` 包含 `unit-test` job |
| GitHub Actions | 已完成 | `.github/workflows/ci.yml`、`.github/workflows/pages.yml` |
| 最终证据矩阵 | 已完成 | `docs/FINAL_EVIDENCE_MATRIX.md` |
| CI / Pages 截图 | 已完成 | `docs/evidence/` |
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
| 上下文与记忆 | `src/specgate/context_selector.py`、`src/specgate/context.py`、`src/specgate/memory.py` | 支持 Select/Compress/Isolate、预算控制、Context Manifest 和跨会话摘要。 |
| Gate 闭环 | `src/specgate/gate.py`、`src/specgate/runner.py` | Gate 失败摘要回灌给下一轮，驱动 MockLLM 生成修复动作。 |
| HITL 正确性 | `src/specgate/approvals.py`、`src/specgate/web_approvals.py` | revision/CAS、`applying` claim、resume 幂等和最终 Gate。 |
| Web 运行时 | `src/specgate/web_runtime.py`、`src/specgate/web_runs.py` | `WebRuntimeCoordinator` 固定 worker、有界队列、取消、超时与重启恢复。 |
| 运行配置 | `src/specgate/runtime_config.py`、`src/specgate/web_db.py` | schema v4 `runtime_config_json` 不可变配置快照。 |
| trace 与报告 | `src/specgate/trace.py`、`src/specgate/report.py` | 记录运行事件并生成静态报告。 |
| 凭据边界 | `src/specgate/credentials.py`、`src/specgate/web_credentials.py` | CLI 使用环境变量只读优先和 OS keyring 持久化；Web 使用独立主密钥与 AES-256-GCM；旧 HMAC 迁移为 `requires_reentry`。 |
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
6. 阅读 `REFLECTION.md`；提交前由学生本人依据 `docs/REFLECTION_FACT_CHECK.md` 核对后续阶段事实。

## 5. Git / PR / CI 证据链

| 阶段 | 功能 commit | Merge commit | PR |
| --- | --- | --- | --- |
| Gate/HITL | `e17b8e5` | `f2b4e88` | [#11](https://github.com/YuGarden404/SpecGate/pull/11) |
| 安全凭据 | `fecc5e3` | `80be31b` | [#12](https://github.com/YuGarden404/SpecGate/pull/12) |
| Pages 热修复 | `20c0102` | `73fbb34` | [#13](https://github.com/YuGarden404/SpecGate/pull/13) |
| Web 运行时 | `e5fc981` | `49f66a2` | [#14](https://github.com/YuGarden404/SpecGate/pull/14) |
| Runner 配置 | `a523137` | `f45e73a` | [#15](https://github.com/YuGarden404/SpecGate/pull/15) |

PR #12 合并后 Pages 曾因依赖缺失失败，PR #13 修复后恢复通过；该失败—修复历史与最终 CI/Pages 状态均保留在 `docs/FINAL_EVIDENCE_MATRIX.md` 和 `docs/evidence/` 中。

## 6. 本地复现命令

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

## 7. 当前完成度判断

项目已经达到期末提交的核心要求：

- 有可运行的 harness。
- 有可复现的 mock LLM 闭环。
- 有单元测试和 CI。
- 有 Dockerfile。
- 有交互式 Web 产品壳、静态 Pages 评审入口和公开 URL。
- 有过程文档、计划、反思和日志。
- 有上下文、安全、工具三条工程主线。
- 有 Lab 10 Skill 与 Lab 9-12 取舍说明。

后续可选增强只保留真实 LLM provider 和 AgentPack 草案；Lab 11 Hook sample 已实现并通过测试。`REFLECTION.md` 仍须由学生本人完成最终事实确认。
