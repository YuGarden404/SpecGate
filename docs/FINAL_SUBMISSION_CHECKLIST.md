# SpecGate 最终提交检查清单

当前证据口径：教师已验证源码基线为 PR #27 合并后的 `main@6dbaa75`；空目录克隆验证得到 `Ran 954 tests in 213.679s`、`OK (skipped=27)`，退出码 0。阶段 A 发布准备分支验证得到 `Ran 954 tests in 418.617s`，同步后的独立复跑得到 `Ran 954 tests in 417.907s`，两次均 `OK (skipped=27)` 且退出码 0。教师基线的 CI #67、Pages #38、NJU Pipeline #313088 / job #596503 均成功；`glm-5.2` 真实 CLI smoke 得到 `passed=True, steps=2`、最终 Gate 通过、`trusted`、`parse_errors=0`，且 keyring 凭据已清除。当前发布基线为 PR #28 合并后的 `main@9cf9093`；CI #69 / run 29678498485、Pages #39 / run 29678498457、GHCR #2 / run 29679264248 与 NJU Pipeline #313118 / job #596642 均成功。`v0.1.1` 已发布，annotated tag object 为 `adb74ca0586b20e3cb5e32767bb409370e70c2ef`，peeled commit 与 OCI revision 为 `9cf909341cd1a5feb8ed2b244ce31f0495016c4c`；`ghcr.io/yugarden404/specgate:0.1.1` 的 digest 为 `sha256:8cb8e5b9c9483a7f6bb70cc27fc3f3053b48be2f4a69374865e7bcbbaca4fd0f`，匿名 pull 与四项 smoke 均通过。

Stage B 证据包为 `docs/evidence/github-actions-ghcr-v0.1.1-success.png`、`docs/evidence/github-package-specgate-v0.1.1-public.png`、`docs/evidence/ghcr-v0.1.1-anonymous-smoke.png`。历史 `v0.1.0` 的 `main@44b236f`、[CI #63](https://github.com/YuGarden404/SpecGate/actions/runs/29649068245)、[Pages #36](https://github.com/YuGarden404/SpecGate/actions/runs/29649068246)、[GHCR #1](https://github.com/YuGarden404/SpecGate/actions/runs/29649149933)、digest `sha256:324fad1d8ae82880990a3e032847408b9339bf52bd81dc53b61e74dcb4b6ea3d` 与 `docs/evidence/github-actions-pr25-ci-success.png`、`docs/evidence/github-actions-pr25-pages-success.png`、`docs/evidence/github-actions-ghcr-v0.1.0-success.png`、`docs/evidence/github-package-specgate-public.png`、`docs/evidence/ghcr-anonymous-pull-smoke.png` 继续保留。公网交互式 Web 后端未部署；发布公开 CLI 镜像不等于部署公网交互式 Web 后端。

Stage B 证据同步分支验证得到 `Ran 955 tests in 404.159s`、`OK (skipped=27)`，退出码 0；这是新增发布事实契约后的独立结果，不替换教师 `Ran 954 tests in 213.679s` 基线。

## 1. 项目定位

SpecGate 是 AI4SE 期末项目 A 类选题，是一个 CLI-first 的 `Coding Agent Harness`。`specgate` CLI 和自行实现的 Harness 内核是核心；WebUI 是配套评审与演示入口。项目目标不是做一个复杂网页应用，而是展示如何把 LLM 的输出约束在可控、可测、可追踪、可修复的工程闭环中。

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
| PR #25 后 CI/Pages/GHCR 与新截图 | 已完成 | CI #63、Pages #36、GHCR #1、Public Package、匿名 pull 与五张当前截图 |
| PR #27 Windows 锁竞态修复 | 已完成 | `main@6dbaa75`、锁准备失败恢复分支回归测试、CI #67 与 Pages #38 |
| 教师空目录验证 | 已完成 | Python 3.13.5；`Ran 954 tests in 213.679s`、`OK (skipped=27)`、退出码 0 |
| Mock 工作区 smoke | 已完成 | 固定 Mock Demo 退出码 0、Gate 通过、trust 为 `trusted` |
| `glm-5.2` 真实 CLI smoke | 已完成 | `passed=True, steps=2`、Gate 通过、`parse_errors=0`，keyring 凭据已清除 |
| `v0.1.1` 发布 | 已完成 | 标签双远端一致，GHCR #2、Public Package、匿名 smoke、digest 与 OCI revision 均已核验 |
| NJU GitLab 课程镜像 | CI 已通过且公开 | [公开项目](https://git.nju.edu.cn/YuyuanLiang/specgate)：Pipeline #313118 / job #596642 覆盖当前 `main@9cf9093`；教师基线 Pipeline #313088 / job #596503 与历史 Pipeline #312806 继续保留 |
| 公开静态评审入口 | 已完成 | GitHub Pages 首页、demo、报告 |
| 本地交互式 WebUI | 已完成 | Docker/本地启动与确定性测试 |
| 公网交互式 Web 后端 | 待完成 | 后续独立部署阶段 |
| Docker 本地与 CI 构建 | 已完成 | `Dockerfile` 与 CI smoke |
| 公开容器 registry | 已完成 | `ghcr.io/yugarden404/specgate:0.1.1` 已公开，匿名 pull、四项 smoke、digest 与 OCI revision 已核验 |
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
| 最终提交同步与双仓库交付 | `9c25621` | `7cecbb1` | [#24](https://github.com/YuGarden404/SpecGate/pull/24) |
| CLI 易用性与 GHCR 分发 | `f8c5c7a` | `44b236f` | [#25](https://github.com/YuGarden404/SpecGate/pull/25) |
| GHCR 公开镜像发布证据 | `ee97b3d` | `fce51a0` | [#26](https://github.com/YuGarden404/SpecGate/pull/26) |
| Windows 并发锁竞态修复与反思 | `2999599` | `6dbaa75` | [#27](https://github.com/YuGarden404/SpecGate/pull/27) |

PR #12 合并后 Pages 曾因依赖缺失失败，PR #13 修复后恢复通过；该失败—修复历史保留在 `docs/FINAL_EVIDENCE_MATRIX.md` 和 `docs/evidence/` 中。用户已更新并核对 PR #18、PR #19、PR #20 的“执行归属”：三份描述均记录主开发 Agent 为 OpenAI Codex，并区分人工参与与自动测试边界。PR #20 合并后的来源链为：

- [CI #53](https://github.com/YuGarden404/SpecGate/actions/runs/29476693238) → `main@c39d101` → `unit-test`、`docker-build` → 成功
- [Pages #31](https://github.com/YuGarden404/SpecGate/actions/runs/29476693242) → `main@c39d101` → `build-pages`、`deploy-pages` → 成功

以上运行由主线程只读核验；截图见 `docs/evidence/github-actions-pr20-final.png`。

PR #23 合并后的历史来源链为：

- [CI #59](https://github.com/YuGarden404/SpecGate/actions/runs/29566219258) → `main@5fd86fa` → `unit-test`、`docker-build` → 成功
- [Pages #34](https://github.com/YuGarden404/SpecGate/actions/runs/29566219221) → `main@5fd86fa` → `build-pages`、`deploy-pages` → 成功

列表截图见 `docs/evidence/github-actions-pr23-final.png`；job 详情截图见 `docs/evidence/github-actions-pr23-ci-detail.png` 与 `docs/evidence/github-actions-pr23-pages-detail.png`。CI/Pages 页面显示的 Node.js 20 弃用 warning 不改变本次成功状态。

PR #25 合并与 `v0.1.0` 发布后的历史来源链为：

- [CI #63](https://github.com/YuGarden404/SpecGate/actions/runs/29649068245) → `main@44b236f` → `unit-test`、`docker-build` → 成功
- [Pages #36](https://github.com/YuGarden404/SpecGate/actions/runs/29649068246) → `main@44b236f` → `build-pages`、`deploy-pages` → 成功
- [GHCR #1](https://github.com/YuGarden404/SpecGate/actions/runs/29649149933) → `v0.1.0@44b236f` → `publish-ghcr` → 成功

GHCR 公开镜像已完成匿名拉取验证；镜像为 `ghcr.io/yugarden404/specgate:0.1.0`，digest 为 `sha256:324fad1d8ae82880990a3e032847408b9339bf52bd81dc53b61e74dcb4b6ea3d`。五张证据图见本清单开头的当前证据包；公网交互式 Web 后端未部署。

PR #28 合并与 `v0.1.1` 发布后的当前来源链为：

- [CI #69](https://github.com/YuGarden404/SpecGate/actions/runs/29678498485) → `main@9cf9093` → 成功
- [Pages #39](https://github.com/YuGarden404/SpecGate/actions/runs/29678498457) → `main@9cf9093` → 成功
- [GHCR #2](https://github.com/YuGarden404/SpecGate/actions/runs/29679264248) → `v0.1.1@9cf9093` → 成功
- [Pipeline #313118](https://git.nju.edu.cn/YuyuanLiang/specgate/-/pipelines/313118) / [job #596642](https://git.nju.edu.cn/YuyuanLiang/specgate/-/jobs/596642) → `main@9cf9093` → 成功

双仓库交付采用“GitHub 开发主仓库 + NJU GitLab 课程镜像”：GitHub 保留完整 commit、PR、GitHub PR/Actions、Docker 构建与 Pages 证据；GitLab 项目已经 Public，可直接用于教师克隆。Pipeline #312781 的 `docker-build` 因学校共享 Runner 不支持 privileged Docker-in-Docker 而失败；Pipeline #312784 因访问 `gcr.io` 出现 `context deadline exceeded`；Pipeline #312797 已成功拉取 BuildKit 镜像，但 RootlessKit 因 `operation not permitted` 无法启动。三次 `unit-test` 已通过，GitLab CI 随后只保留 `unit-test`。[Pipeline #312806](https://git.nju.edu.cn/YuyuanLiang/specgate/-/pipelines/312806) 是历史成功链，Pipeline #313088 / job #596503 是教师源码基线，当前 Pipeline #313118 / job #596642 覆盖 `main@9cf9093` 并成功。GitLab Pipeline 已通过，且不等同于迁移 GitHub Actions。

## 6. 本地复现命令

运行单元测试：

```powershell
$env:PYTHONPATH="src"
python -m unittest discover -s tests -v
```

2026-07-19 教师空目录验证（`main@6dbaa75`，PR #27）：

- 完整套件：`Ran 954 tests in 213.679s`、`OK (skipped=27)`，退出码 0。

阶段 A 发布准备分支验证：首次为 `Ran 954 tests in 418.617s`，同步后的独立复跑为 `Ran 954 tests in 417.907s`，两次均 `OK (skipped=27)` 且退出码 0。聚焦套件、Python 编译、JavaScript 语法和疑似真实密钥模式扫描均通过；这些耗时不替换教师基线 `Ran 954 tests in 213.679s`。

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
docker run --rm specgate:local --help
docker run --rm specgate:local run-mock-demo /opt/specgate/examples/knowledge_nav
docker run --rm --entrypoint specgate-web specgate:local --help
```

## 7. 当前完成度判断

项目已经达到期末提交的核心要求：

- 有可运行的 harness。
- 有可复现的 mock LLM 闭环。
- 有单元测试和 CI。
- 有 Dockerfile、本地交互式 WebUI 和确定性测试；这只证明本地与 CI 构建路径已完成。
- 有公开静态 Pages 评审入口；GHCR 公开镜像已完成匿名拉取验证，公开容器 registry 已完成；公网交互式 Web 后端未部署。
- 有过程文档、计划、反思和日志。
- 有上下文、安全、工具三条工程主线。
- 有 Lab 10 Skill 与 Lab 9-12 取舍说明。
- GitHub 开发主仓库当前源码证据已同步到 PR #28；NJU GitLab 已公开，当前 unit-test-only Pipeline #313118 / job #596642 已通过。`v0.1.1` 标签、GHCR、匿名 smoke、digest、OCI revision 与双仓库 tags 同步均已完成并核验。

后续阶段包括公网交互式 Web 后端部署、更多 Provider 的人工兼容性验证和 AgentPack 草案；发布镜像不等于部署服务。当前公开容器 registry 已完成，但 CI、Pages 与 GHCR 成功都不代表公网交互式 Web 后端已经部署。真实 LLM Web 接入代码已经完成，但课程自动验收仍使用 Mock/Fake/Stub，`REFLECTION.md` 继续由学生本人维护。
