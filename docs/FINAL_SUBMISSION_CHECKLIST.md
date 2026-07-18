# SpecGate 最终提交检查清单

当前证据口径：当前主线为 PR #23 合并后的 `main@5fd86fa`；当前最终验证为 `Ran 921 tests in 403.030s`、`OK (skipped=27)`，退出码 0。[CI #59](https://github.com/YuGarden404/SpecGate/actions/runs/29566219258) 与 [Pages #34](https://github.com/YuGarden404/SpecGate/actions/runs/29566219221) 的精确链接和 job 详情截图已录入；PR #20 的历史运行链接和截图继续保留。

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
- 不把真实 LLM 设为默认或自动验收前提；完整配置后才作为可选决策源。
- 不使用现成 agent framework 作为 harness core。

## 2. 课程交付物对照

| 要求 | 状态 | 对应文件或证据 |
| --- | --- | --- |
| 项目规约 | 已完成 | `SPEC.md` |
| 实施计划 | 已完成 | `PLAN.md`、`docs/superpowers/plans/` |
| 规约过程记录 | 已完成 | `SPEC_PROCESS.md` |
| 开发日志 | 已完成 | `AGENT_LOG.md` |
| 学生反思 | 已由学生确认 | `REFLECTION.md`、`docs/REFLECTION_FACT_CHECK.md`、PR #17 |
| 源代码 | 已完成 | `src/specgate/` |
| 单元测试 | 已完成 | `tests/` |
| Mock LLM 测试路径 | 已完成 | `src/specgate/llm.py`、`tests/test_runner.py`、`tests/test_cli.py` |
| 可选真实模型路径 | 已完成 | `src/specgate/llm_config.py`、`src/specgate/llm_transport.py`、`src/specgate/web_llm.py` |
| GitLab CI 文件 | 已完成 | `.gitlab-ci.yml` 包含 `unit-test` job |
| GitHub Actions | 已完成 | `.github/workflows/ci.yml`、`.github/workflows/pages.yml` |
| 最终证据矩阵 | 已完成 | `docs/FINAL_EVIDENCE_MATRIX.md` |
| 历史 CI/Pages 截图（截至 PR #15/#17） | 已完成 | `docs/evidence/` 中的历史截图与第 5 节记录 |
| PR #20 后 CI/Pages 与新截图 | 已完成 | [CI #53](https://github.com/YuGarden404/SpecGate/actions/runs/29476693238)、[Pages #31](https://github.com/YuGarden404/SpecGate/actions/runs/29476693242)、`docs/evidence/github-actions-pr20-final.png` |
| PR #23 后 CI/Pages 与新截图 | 已完成 | [CI #59](https://github.com/YuGarden404/SpecGate/actions/runs/29566219258)、[Pages #34](https://github.com/YuGarden404/SpecGate/actions/runs/29566219221)、`docs/evidence/github-actions-pr23-final.png` 及两张 job 详情截图 |
| NJU GitLab 课程镜像 | 修复验证中 | [Private 项目](https://git.nju.edu.cn/YuyuanLiang/specgate) 已同步 `main@5fd86fa`；Pipeline #312781 的 `unit-test` 已通过、`docker-build` 失败，正在验证 daemonless 构建；检查前改为 Public |
| 公开静态评审入口 | 已完成 | GitHub Pages 首页、demo、报告 |
| 本地交互式 WebUI | 已完成 | Docker/本地启动与确定性测试 |
| 公网交互式 Web 后端 | 待完成 | 后续独立部署阶段 |
| Docker 本地与 CI 构建 | 已完成 | `Dockerfile` 与 CI smoke |
| 公开容器 registry | 待完成 | 后续 GHCR 分发阶段 |
| AgentOS / Superpowers 对齐 | 已完成 | `skills/specgate-static-html-harness/SKILL.md`、`docs/AI4SE_Lab_9_12_Alignment.md` |
| Lab 11 Hook sample | 已完成 | `hooks/pre-commit.sample`、`tests/test_hook_sample.py` |

## 3. 核心机制对照

| 机制 | 实现位置 | 说明 |
| --- | --- | --- |
| Action 协议 | `src/specgate/actions.py` | 只接受严格 JSON object，拒绝 Markdown code fence、缺字段和非法参数。 |
| 工具管理 | `src/specgate/tool_registry.py`、`src/specgate/tools.py` | Tool Registry 描述工具名称、权限、参数和结果，dispatcher 只执行注册工具。 |
| 安全边界 | `src/specgate/policy.py`、`src/specgate/snapshot.py`、`src/specgate/workspace_fs.py` | 阻止未知动作、路径越界、链接逃逸、allowlist 外写入、非法编码崩溃和运行期间外部修改覆盖。 |
| 上下文与记忆 | `src/specgate/context_selector.py`、`src/specgate/context.py`、`src/specgate/memory.py` | 支持 Select/Compress/Isolate、预算控制、Context Manifest 和跨会话摘要。 |
| Gate 闭环 | `src/specgate/gate.py`、`src/specgate/runner.py` | Gate 失败摘要回灌给下一轮，驱动 MockLLM 生成修复动作。 |
| HITL 正确性 | `src/specgate/approvals.py`、`src/specgate/web_approvals.py` | revision/CAS、`applying` claim、resume 幂等和最终 Gate。 |
| Web 运行时 | `src/specgate/web_runtime.py`、`src/specgate/web_runs.py` | `WebRuntimeCoordinator` 固定 worker、有界队列、取消、超时与重启恢复。 |
| 运行配置 | `src/specgate/runtime_config.py`、`src/specgate/llm_config.py`、`src/specgate/web_db.py` | schema v5 `runtime_config_json` / `llm_config_json` 不可变配置快照。 |
| 真实模型边界 | `src/specgate/llm_transport.py`、`src/specgate/web_llm.py` | 默认 Mock；完整配置后使用真实模型；精确主机白名单、公网固定 IP TLS、失败不降级。 |
| trace 与报告 | `src/specgate/trace.py`、`src/specgate/report.py` | 记录运行事件并生成静态报告。 |
| 凭据边界 | `src/specgate/credentials.py`、`src/specgate/web_credentials.py` | CLI 使用环境变量只读优先和 OS keyring 持久化；Web 使用独立主密钥与 AES-256-GCM；旧 HMAC 迁移为 `requires_reentry`。 |
| 提交前防线示例 | `hooks/pre-commit.sample` | 可选 Hook sample，用于疑似密钥扫描、必要文件检查和测试提示。 |

## 4. 推荐评审路径

1. 阅读 `README.md` 的“评审快速入口”。
2. 阅读 `SPEC.md` 前 5 节，确认项目定位和 MVP 边界。
3. 阅读 `docs/PROJECT_WALKTHROUGH.md`，按演示脚本理解一次完整运行。
4. 打开公开页面：
   - 静态评审首页：`https://yugarden404.github.io/SpecGate/`
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
| 最终材料 | `116cc10` | `fa3278a` | [#16](https://github.com/YuGarden404/SpecGate/pull/16) |
| 学生反思 | `d550032` | `e73e937` | [#17](https://github.com/YuGarden404/SpecGate/pull/17) |
| 后端审计加固 | `d3607c4` | `8d30ca5` | [#18](https://github.com/YuGarden404/SpecGate/pull/18) |
| Web 真实 LLM 接入 | `5279a7c` | `b98563a` | [#19](https://github.com/YuGarden404/SpecGate/pull/19) |
| 真实 LLM 生命周期修复 | `e35eb46` | `c39d101` | [#20](https://github.com/YuGarden404/SpecGate/pull/20) |
| 最终交付合规 | `e34452c` | `2082fc9` | [#21](https://github.com/YuGarden404/SpecGate/pull/21) |
| LLM 连接测试超时修复 | `a5861aa` | `3905e1e` | [#22](https://github.com/YuGarden404/SpecGate/pull/22) |
| NJU SE Hub 真实 LLM 审计 | `5635ad2` | `5fd86fa` | [#23](https://github.com/YuGarden404/SpecGate/pull/23) |

PR #12 合并后 Pages 曾因依赖缺失失败，PR #13 修复后恢复通过；该失败—修复历史保留在 `docs/FINAL_EVIDENCE_MATRIX.md` 和 `docs/evidence/` 中。用户已更新并核对 PR #18、PR #19、PR #20 的“执行归属”：三份描述均记录主开发 Agent 为 OpenAI Codex，并区分人工参与与自动测试边界。PR #20 合并后的来源链为：

- [CI #53](https://github.com/YuGarden404/SpecGate/actions/runs/29476693238) → `main@c39d101` → `unit-test`、`docker-build` → 成功
- [Pages #31](https://github.com/YuGarden404/SpecGate/actions/runs/29476693242) → `main@c39d101` → `build-pages`、`deploy-pages` → 成功

以上运行由主线程只读核验；截图见 `docs/evidence/github-actions-pr20-final.png`。

PR #23 合并后的当前来源链为：

- [CI #59](https://github.com/YuGarden404/SpecGate/actions/runs/29566219258) → `main@5fd86fa` → `unit-test`、`docker-build` → 成功
- [Pages #34](https://github.com/YuGarden404/SpecGate/actions/runs/29566219221) → `main@5fd86fa` → `build-pages`、`deploy-pages` → 成功

列表截图见 `docs/evidence/github-actions-pr23-final.png`；job 详情截图见 `docs/evidence/github-actions-pr23-ci-detail.png` 与 `docs/evidence/github-actions-pr23-pages-detail.png`。CI/Pages 页面显示的 Node.js 20 弃用 warning 不改变本次成功状态。

双仓库交付采用“GitHub 开发主仓库 + NJU GitLab 课程镜像”：GitHub 保留完整 commit、PR、GitHub PR/Actions 与 Pages 证据；GitLab 项目已创建为 Private，检查前改为 Public。初始 Pipeline #312781 的 `unit-test` 已通过、`docker-build` 失败；根因是学校共享 runner 不支持 privileged Docker-in-Docker，当前处于 Kaniko 修复验证中。GitLab Pipeline 是独立验证，不等同于迁移 GitHub Actions。

## 6. 本地复现命令

运行单元测试：

```powershell
$env:PYTHONPATH="src"
python -m unittest discover -s tests -v
```

2026-07-17 当前最终验证：

- 文档与工作流契约：`Ran 20 tests in 0.065s`、`OK`，退出码 0。
- 六项确定性机制：`Ran 6 tests in 47.709s`、`OK`，退出码 0。
- 完整套件：`Ran 921 tests in 403.030s`、`OK (skipped=27)`，退出码 0。
- Python 编译、JavaScript 语法和 Git 空白检查均退出码 0 且无错误输出。
- `.env` 已被忽略且无提交历史；排除测试与实施计划后的疑似密钥模式扫描无命中。
- 主线程只读浏览器复核首页、demo 和 report 均正常加载并显示预期标题与主标题；本地验证 Subagent 没有亲自浏览远端。

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
- 有 Dockerfile、本地交互式 WebUI 和确定性测试；这只证明本地与 CI 构建路径已完成。
- 有公开静态 Pages 评审入口；公网交互式 Web 后端与公开容器 registry 待后续独立阶段完成。
- 有过程文档、计划、反思和日志。
- 有上下文、安全、工具三条工程主线。
- 有 Lab 10 Skill 与 Lab 9-12 取舍说明。
- GitHub 开发主仓库证据已同步到 PR #23；NJU GitLab 课程镜像已创建并取得真实初始 Pipeline 结果，daemonless 构建修复、通过截图和检查前 Public 切换仍待完成。

后续阶段包括公网交互式 Web 后端部署、GHCR 镜像分发、更多 Provider 的人工兼容性验证和 AgentPack 草案；发布镜像不等于部署服务。当前合规阶段不部署、不发布；CI #53 与 Pages #31 成功只证明自动测试、Docker CI 构建和静态 Pages 发布链，不代表公网交互式 Web 后端已经部署或镜像已发布到公开容器 registry。真实 LLM Web 接入代码已经完成，但课程自动验收仍使用 Mock/Fake/Stub，`REFLECTION.md` 继续由学生本人维护。
