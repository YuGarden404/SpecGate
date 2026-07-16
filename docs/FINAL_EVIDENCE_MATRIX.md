# SpecGate 最终验证证据矩阵

## 1. 证据口径

本文件是最终交付的权威证据入口。事实优先级为：当前代码与测试 → Git/PR → CI/Pages 与截图 → 当时的 Agent Log → 旧说明文档。课程自动验收只使用 MockLLM/Fake/Stub，不需要真实 LLM、API key 或网络；Web 后端在用户完整配置后可为新 run 启用真实模型，失败不会降级到 Mock。

## 2. 最终版本快照

- 审查起点主线基线：`main@c39d101`。
- 最近已合并功能修复：PR #20。
- 审查起点完整回归：`Ran 908 tests in 210.559s`、`OK (skipped=27)`。
- 当前工作阶段：最终交付合规修复；最终测试数字将在本阶段结束时刷新。
- 远端证据边界：PR #18 至 PR #20 的 commit、merge commit 与 PR 链接已按仓库 Git 历史记录；PR #20 合并后的 CI、Pages 和新截图仍待人工远端核对。
- 公开入口：<https://yugarden404.github.io/SpecGate/>。

## 3. 课程交付物

| 要求 | 状态 | 仓库证据 | 复现方式 |
| --- | --- | --- | --- |
| SPEC / PLAN / 过程记录 | 已完成 | `SPEC.md`、`PLAN.md`、`SPEC_PROCESS.md` | 从 README 评审入口阅读 |
| 自实现 Harness | 已完成 | `src/specgate/runner.py`、`src/specgate/actions.py`、`src/specgate/tools.py` | Runner 机制测试 |
| MockLLM 确定性测试 | 已完成 | `tests/test_runner.py`、`tests/test_cli.py` | `python -m unittest tests.test_runner tests.test_cli` |
| 凭据治理 | 已完成 | `src/specgate/credentials.py`、`src/specgate/web_credentials.py` | 凭据测试，无明文回显 |
| 公开静态评审入口 | 已完成 | GitHub Pages 首页、demo、报告 | 打开 README 中的三个 Pages URL |
| 本地交互式 WebUI | 已完成 | `Dockerfile`、Web 运行时与确定性测试 | Docker/本地启动与确定性测试 |
| 公网交互式 Web 后端 | 待完成 | 后续独立部署阶段 | 任务 6 人工门禁之后另行部署与核验 |
| Docker 本地与 CI 构建 | 已完成 | `Dockerfile`、`.gitlab-ci.yml` | Docker build/smoke 与 CI |
| 公开容器 registry | 待完成 | 后续 GHCR 分发阶段 | 发布后另行记录公开镜像地址与摘要 |
| 学生反思 | 已由学生确认 | `REFLECTION.md`、`docs/REFLECTION_FACT_CHECK.md` | PR #17 与学生确认记录 |

## 4. 核心机制

| 机制 | 实现 | 确定性测试 | 演示证据 |
| --- | --- | --- | --- |
| Agent loop / 停机 | `src/specgate/runner.py` | `tests/test_runner.py` | Gate 反馈改变下一步 action |
| Action / Tool Dispatcher | `src/specgate/actions.py`、`src/specgate/tools.py` | `tests/test_actions.py`、`tests/test_tools.py` | 非法 action 与越权工具失败关闭 |
| WorkspacePolicy / 路径安全 | `src/specgate/policy.py`、`src/specgate/workspace_fs.py` | `tests/test_policy.py`、`tests/test_workspace_fs.py` | `.env`、路径逃逸、链接路径被阻止 |
| Checklist / Gate | `src/specgate/gate.py`、`src/specgate/checklist_rules.py` | `tests/test_gate.py`、`tests/test_checklist_rules.py` | 最终 Gate 与输入 SHA-256 |
| HITL / CAS / resume | `src/specgate/approvals.py`、`src/specgate/web_approvals.py` | `tests/test_approvals.py`、`tests/test_web_approvals.py` | approve/deny → resume 闭环 |
| Context Select/Compress/Isolate | `src/specgate/context.py`、`src/specgate/retrieval.py`、`src/specgate/context_lifecycle.py` | `tests/test_context.py`、`tests/test_runner.py` | security benchmark 与多策略 benchmark |
| 安全凭据 | `src/specgate/credentials.py`、`src/specgate/web_credentials.py` | `tests/test_credentials.py`、`tests/test_credential_store.py`、`tests/test_web_credentials.py` | OS keyring / AES-256-GCM，不回显明文 |
| Web 有界运行时 | `src/specgate/web_runtime.py`、`src/specgate/web_runs.py` | `tests/test_web_runtime.py`、`tests/test_web_runs.py` | 固定 worker、有界队列、取消/超时/恢复 |
| 不可变运行配置 | `src/specgate/runtime_config.py`、`src/specgate/web_db.py` | `tests/test_runtime_config.py`、`tests/test_web_db.py` | schema v5 `runtime_config_json` 快照 |
| 可选真实模型 | `src/specgate/llm_config.py`、`src/specgate/llm_transport.py`、`src/specgate/web_llm.py` | `tests/test_llm_config.py`、`tests/test_llm_transport.py`、`tests/test_web_llm.py` | schema v5 `llm_config_json`、SSRF/TLS/重试/取消与 Factory 冻结 |
| Trace / Debug / Audit | `src/specgate/trace.py`、`src/specgate/web_debug.py` | `tests/test_web_debug.py`、`tests/test_web_static.py` | 实际运行配置和审计证据 |

## 5. 最近阶段 Git / PR / CI

| 阶段 | 功能 commit | Merge commit | PR | 远端证据 |
| --- | --- | --- | --- | --- |
| Gate/HITL | `e17b8e5` | `f2b4e88` | [#11](https://github.com/YuGarden404/SpecGate/pull/11) | PR 与最终 main CI |
| 安全凭据 | `fecc5e3` | `80be31b` | [#12](https://github.com/YuGarden404/SpecGate/pull/12) | Pages 失败历史保留在截图 |
| Pages 热修复 | `20c0102` | `73fbb34` | [#13](https://github.com/YuGarden404/SpecGate/pull/13) | `evidence/github-actions-web-runtime-and-credentials.png` |
| Web 运行时 | `e5fc981` | `49f66a2` | [#14](https://github.com/YuGarden404/SpecGate/pull/14) | `evidence/github-actions-web-runtime-and-credentials.png` |
| Runner 配置 | `a523137` | `f45e73a` | [#15](https://github.com/YuGarden404/SpecGate/pull/15) | `evidence/github-actions-runtime-config.png` |
| 最终材料 | `116cc10` | `fa3278a` | [#16](https://github.com/YuGarden404/SpecGate/pull/16) | 合并后 CI/Pages |
| 学生反思 | `d550032` | `e73e937` | [#17](https://github.com/YuGarden404/SpecGate/pull/17) | CI #47、Pages #28 |
| 后端审计加固 | `d3607c4` | `8d30ca5` | [#18](https://github.com/YuGarden404/SpecGate/pull/18) | 本地 Git 历史；CI/Pages 待人工核对 |
| Web 真实 LLM 接入 | `5279a7c` | `b98563a` | [#19](https://github.com/YuGarden404/SpecGate/pull/19) | 本地 Git 历史；CI/Pages 待人工核对 |
| 真实 LLM 生命周期修复 | `e35eb46` | `c39d101` | [#20](https://github.com/YuGarden404/SpecGate/pull/20) | 本地 Git 历史；CI/Pages 与新截图待人工核对 |

## 6. CI 与截图说明

![安全凭据、Pages 热修复与 Web Runtime Actions](evidence/github-actions-web-runtime-and-credentials.png)

截图如实保留 PR #12 合并后的 Pages 失败，以及 PR #13 修复后 CI/Pages 和 PR #14 成功。失败不是最终状态，但属于重要调试证据。

![Runner 配置接线与最终 main Actions](evidence/github-actions-runtime-config.png)

截图记录 PR #15、合并后 main CI #43 和 Pages #26 均通过。Workflow 定义见 `.github/workflows/ci.yml`、`.github/workflows/pages.yml`；GitLab 课程要求见 `.gitlab-ci.yml`，Docker 本地与 CI 构建定义见 `Dockerfile`。这些历史证据不代表镜像已经发布到公开容器 registry，也不代表公网交互式 Web 后端已经部署。

## 7. 核心机制复现

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_runner.RunnerTests.test_guardrail_block_is_recorded
python -m unittest tests.test_runner.RunnerTests.test_gate_failure_feedback_changes_next_action
python -m unittest tests.test_runner.RunnerTests.test_review_action_pauses_before_next_llm_call tests.test_runner.RunnerTests.test_resume_from_approved_approval_applies_payload_once_and_continues
python -m unittest tests.test_cli.CliTests.test_repository_security_benchmark_smoke tests.test_cli.CliTests.test_repository_multi_strategy_benchmark_smoke
```

## 8. 完整验证

```powershell
$env:PYTHONPATH="src"
python -m unittest discover -s tests
python -m compileall -q src tests
node --check src/specgate/web_static/app.js
git diff --check
```

历史阶段结果（2026-07-15 Web 真实 LLM 接入分支）：`Ran 896 tests in 216.620s`、`OK (skipped=27)`。该数字早于 PR #20 生命周期修复，不代表当前快照。非法 `unsafe` governance profile 的 argparse 输出来自预期拒绝测试，不是失败；跳过项主要来自 Windows 当前没有创建符号链接的权限和仓库既有平台条件。

## 9. 边界

- 自动验收只使用 MockLLM/Fake/Stub，不访问真实 DNS、socket 或 Provider。
- Web 默认使用 MockLLM；完整配置后新 run 可使用真实模型，Provider 失败不会降级。
- GitHub Pages 仅为静态展示，真实模式需要部署 Web 后端、持久化数据库、凭据主密钥与 `SPECGATE_LLM_ALLOWED_HOSTS` 网络策略。
- 本地交互式 WebUI 已具备 Docker/本地启动与确定性测试；公网交互式 Web 后端和公开容器 registry 均待后续独立阶段完成。发布镜像不等于部署服务。
- 不开放 shell，不执行同源模型生成 HTML。
- CLI 持久化凭据使用 OS keyring；Web 使用独立主密钥和 AES-256-GCM。
- `.env` 只作为被保护路径和威胁示例出现，SpecGate 不读写 `.env`。
- 旧 HMAC 只作为迁移来源，迁移后要求重新录入。
- `REFLECTION.md` 的观点和最终文字由学生本人负责。
