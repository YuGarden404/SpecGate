# Final Delivery Compliance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 SpecGate 的最终交付材料与 PR #20 后的真实仓库状态、课程硬性条款和可复核证据保持一致。

**Architecture:** 以 `tests/test_final_evidence.py` 作为确定性材料契约入口，每个合规主题先增加失败断言，再最小化修改对应 Markdown 材料。远端 PR、CI 截图和不同类型 agent 冷启动结果作为人工门禁，只有真实发生后才写入“已完成”；生产代码保持不变。

**Tech Stack:** Python 3.11+、`unittest`、`tomllib`、Markdown、Git/GitHub、全新 Gemini 会话。

---

## File Map

- `tests/test_final_evidence.py`：最终证据、许可证、Open Design、冷启动和部署边界的确定性契约。
- `docs/superpowers/audits/2026-07-16-final-compliance-cold-start.md`：本阶段补充冷启动的事实记录。
- `SPEC_PROCESS.md`：区分 2026-07-08 计划审查与本阶段补充实现验证。
- `docs/FINAL_EVIDENCE_MATRIX.md`：当前版本、PR、CI、测试和课程条款的权威证据入口。
- `docs/FINAL_SUBMISSION_CHECKLIST.md`：最终提交状态与待完成项。
- `docs/REFLECTION_FACT_CHECK.md`：供学生本人核对的最新事实，不改写反思正文。
- `SPEC.md`：Open Design 的真实采用/偏离决策和部署边界。
- `PLAN.md`：PR #18 至 PR #20、本阶段任务及 commit 证据。
- `AGENT_LOG.md`：按时间追加本阶段过程、人工门禁和验证结果。
- `README.md`：第三方许可证表、静态 Pages 与交互式 Web 后端边界。
- `docs/evidence/github-actions-pr20-final.png`：由用户提供的 PR #20 合并后 CI/Pages 截图。

## Pre-Execution Gate: Fresh Gemini Cold Start

此门禁必须在 Task 1 以外的材料实现开始前完成。它是最终合规阶段的补充验证，不追溯性替代 2026-07-08 的早期计划审查。

- [ ] **Step 1: Invoke the worktree skill**

调用 `superpowers:using-git-worktrees`，从包含本计划的 commit 创建独立冷启动 worktree。冷启动 worktree 不导入当前对话、memory 或未提交改动。

- [ ] **Step 2: Start a completely new Gemini session**

在冷启动 worktree 中启动不同类型的 Gemini agent。只向它发送以下指令，不补充口头解释：

```text
这是一次 SpecGate 最终合规阶段的冷启动验证。

你的上下文只允许来自仓库根目录 SPEC.md 与
docs/superpowers/plans/2026-07-16-final-delivery-compliance.md。
不要读取 AGENT_LOG.md、SPEC_PROCESS.md、聊天记录或任何 agent memory。

请尝试执行本计划的 Task 2 和 Task 3。你可以读取这两个任务明确列出的文件，
但不能向我索取项目历史口头说明。严格按测试先失败、最小修改、测试转绿推进。

遇到任何不确定之处必须立即暂停并提出具体问题，不得猜测继续。
请在结束时报告：读取了哪些文件、在哪一步暂停、提出的问题、产生的修改、
测试结果、你认为 SPEC/PLAN 仍缺少的信息，以及总耗时。
不要执行 git push、创建 PR 或修改远端状态。
```

- [ ] **Step 3: Preserve the unedited result**

用户把 Gemini 的问题、最终报告、`git diff --stat`、测试输出和耗时原样提供给主线程。主线程不得先行润色或把失败改写为成功。

- [ ] **Step 4: Decide whether the plan needs correction**

若 Gemini 因计划歧义暂停，先修订本计划并提交该修订，再开始 Task 1。若 Gemini 可以完成任务，也要记录其与预期不同的理解和产出差异。

### Task 1: Record the Supplemental Cold-Start Evidence

**Files:**
- Create: `docs/superpowers/audits/2026-07-16-final-compliance-cold-start.md`
- Modify: `tests/test_final_evidence.py`
- Modify: `SPEC_PROCESS.md`
- Modify: `PLAN.md`
- Modify: `AGENT_LOG.md`

- [ ] **Step 1: Write the failing evidence-contract test**

在 `tests/test_final_evidence.py` 顶部常量区增加：

```python
COLD_START_AUDIT = (
    ROOT
    / "docs"
    / "superpowers"
    / "audits"
    / "2026-07-16-final-compliance-cold-start.md"
)
```

在 `FinalEvidenceTests` 中增加：

```python
def test_supplemental_cold_start_records_required_evidence(self):
    self.assertTrue(COLD_START_AUDIT.is_file())
    audit = COLD_START_AUDIT.read_text(encoding="utf-8")
    for heading in (
        "## 验证边界",
        "## Agent 与会话",
        "## 尝试任务",
        "## 暂停与问题",
        "## 实际产出与测试",
        "## 与预期的差异",
        "## SPEC / PLAN 修订",
        "## 时间记录",
    ):
        with self.subTest(heading=heading):
            self.assertIn(heading, audit)
    self.assertIn("最终合规阶段的补充冷启动验证", audit)
    self.assertIn("不替代 2026-07-08", audit)
```

- [ ] **Step 2: Run the test and verify RED**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_final_evidence.FinalEvidenceTests.test_supplemental_cold_start_records_required_evidence
```

Expected: FAIL because `docs/superpowers/audits/2026-07-16-final-compliance-cold-start.md` does not exist.

- [ ] **Step 3: Write the audit from the actual Gemini result**

创建审计文件并使用测试要求的八个标题。每节只写 Gemini 原始结果能够支持的事实；没有暂停问题时明确写“本次没有暂停提问”，没有成功产出时记录失败和阻塞点。禁止使用推测性补全。

在 `SPEC_PROCESS.md` 的冷启动章节后追加“最终合规阶段补充冷启动”，明确：

```markdown
本记录是最终合规阶段的补充冷启动验证，不替代 2026-07-08 的早期
SPEC/PLAN 可执行性审查，也不追溯性声称 MVP 实现前完成过完整实现试跑。
```

在 `PLAN.md` 与 `AGENT_LOG.md` 追加 agent 类型、会话隔离、任务、问题、产出、测试、修订和人工参与事实。

- [ ] **Step 4: Run focused tests and verify GREEN**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_final_evidence
```

Expected: PASS.

- [ ] **Step 5: Commit the cold-start evidence**

```powershell
git add -- tests/test_final_evidence.py SPEC_PROCESS.md PLAN.md AGENT_LOG.md docs/superpowers/audits/2026-07-16-final-compliance-cold-start.md
git commit -m "docs: record supplemental compliance cold start"
```

### Task 2: Synchronize the Current Release and Evidence Chain

**Files:**
- Modify: `tests/test_final_evidence.py`
- Modify: `docs/FINAL_EVIDENCE_MATRIX.md`
- Modify: `docs/FINAL_SUBMISSION_CHECKLIST.md`
- Modify: `docs/REFLECTION_FACT_CHECK.md`
- Modify: `PLAN.md`
- Modify: `AGENT_LOG.md`

- [ ] **Step 1: Extend the release-chain test and add a current-snapshot test**

在 `test_release_chain_and_screenshot_links_are_recorded` 的 `releases` 中补充：

```python
(16, "116cc10", "fa3278a"),
(17, "d550032", "e73e937"),
(18, "d3607c4", "8d30ca5"),
(19, "5279a7c", "b98563a"),
(20, "e35eb46", "c39d101"),
```

新增当前快照测试：

```python
def test_final_snapshot_uses_pr20_baseline_without_stale_branch_claims(self):
    matrix = MATRIX.read_text(encoding="utf-8")
    snapshot = matrix.split("## 3. 课程交付物", 1)[0]
    self.assertIn("main@c39d101", snapshot)
    self.assertIn("PR #20", snapshot)
    self.assertIn("Ran 908 tests", snapshot)
    self.assertNotIn("当前未提交分支", snapshot)
    self.assertNotIn("main@e73e937", snapshot)
    self.assertNotIn("Ran 896 tests", snapshot)
```

- [ ] **Step 2: Run the two tests and verify RED**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_final_evidence.FinalEvidenceTests.test_release_chain_and_screenshot_links_are_recorded tests.test_final_evidence.FinalEvidenceTests.test_final_snapshot_uses_pr20_baseline_without_stale_branch_claims
```

Expected: FAIL because PR #18 to #20 and the PR #20 baseline are missing.

- [ ] **Step 3: Update the authoritative evidence documents**

将 `docs/FINAL_EVIDENCE_MATRIX.md` 的当前快照改为以下事实口径：

```markdown
- 审查起点主线基线：`main@c39d101`。
- 最近已合并功能修复：PR #20。
- 审查起点完整回归：`Ran 908 tests in 210.559s`、`OK (skipped=27)`。
- 当前工作阶段：最终交付合规修复；最终测试数字将在本阶段结束时刷新。
```

在 PR 表中增加：

```markdown
| 后端审计加固 | `d3607c4` | `8d30ca5` | [#18](https://github.com/YuGarden404/SpecGate/pull/18) |
| Web 真实 LLM 接入 | `5279a7c` | `b98563a` | [#19](https://github.com/YuGarden404/SpecGate/pull/19) |
| 真实 LLM 生命周期修复 | `e35eb46` | `c39d101` | [#20](https://github.com/YuGarden404/SpecGate/pull/20) |
```

同步 `docs/FINAL_SUBMISSION_CHECKLIST.md`、`docs/REFLECTION_FACT_CHECK.md`、`PLAN.md` 和 `AGENT_LOG.md`。旧测试数字保留在历史阶段段落，不再出现在“当前最终状态”中。

- [ ] **Step 4: Run focused evidence tests and verify GREEN**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_final_evidence
```

Expected: PASS.

- [ ] **Step 5: Commit the evidence-chain synchronization**

```powershell
git add -- tests/test_final_evidence.py docs/FINAL_EVIDENCE_MATRIX.md docs/FINAL_SUBMISSION_CHECKLIST.md docs/REFLECTION_FACT_CHECK.md PLAN.md AGENT_LOG.md
git commit -m "docs: synchronize final release evidence"
```

### Task 3: Add a Complete Direct-Dependency License Table

**Files:**
- Modify: `tests/test_final_evidence.py`
- Modify: `README.md`

- [ ] **Step 1: Add dependency parsing imports and the failing test**

在 `tests/test_final_evidence.py` 增加：

```python
import re
import tomllib
```

增加辅助函数和测试：

```python
def direct_dependency_names() -> set[str]:
    data = tomllib.loads(read_text("pyproject.toml"))
    names = set()
    for requirement in data["project"]["dependencies"]:
        name = re.split(r"[<>=!~\[; ]", requirement, maxsplit=1)[0]
        names.add(name.lower().replace("_", "-"))
    return names


def test_readme_lists_every_direct_dependency_license(self):
    readme = read_text("README.md")
    self.assertIn("## 第三方依赖与许可证", readme)
    for dependency in direct_dependency_names():
        with self.subTest(dependency=dependency):
            self.assertIn(f"| `{dependency}` |", readme)
```

- [ ] **Step 2: Run the license test and verify RED**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_final_evidence.FinalEvidenceTests.test_readme_lists_every_direct_dependency_license
```

Expected: FAIL because README has no license section.

- [ ] **Step 3: Verify installed package metadata**

Run:

```powershell
python -c "from importlib.metadata import metadata; names=['cryptography','fastapi','httpx','keyring','python-multipart','uvicorn']; [(lambda m: print(n, m.get('License-Expression') or m.get('License'), m.get_all('Project-URL')))(metadata(n)) for n in names]"
```

Expected licenses:

```text
cryptography: Apache-2.0 OR BSD-3-Clause
fastapi: MIT
httpx: BSD-3-Clause
keyring: MIT
python-multipart: Apache-2.0
uvicorn: BSD-3-Clause
```

- [ ] **Step 4: Add the README license table**

在安全边界之前增加：

```markdown
## 第三方依赖与许可证

| 依赖 | 版本范围 | 用途 | 许可证 | 官方项目 |
| --- | --- | --- | --- | --- |
| `cryptography` | `>=44,<47` | Web 凭据 AES-256-GCM 加密 | Apache-2.0 OR BSD-3-Clause | https://github.com/pyca/cryptography |
| `fastapi` | `>=0.115,<1` | Web API 框架 | MIT | https://github.com/fastapi/fastapi |
| `httpx` | `>=0.27,<1` | 测试与 HTTP 客户端支持 | BSD-3-Clause | https://github.com/encode/httpx |
| `keyring` | `>=25,<26` | CLI 操作系统凭据存储 | MIT | https://github.com/jaraco/keyring |
| `python-multipart` | `>=0.0.9,<1` | Web 表单与文件上传解析 | Apache-2.0 | https://github.com/Kludex/python-multipart |
| `uvicorn` | `>=0.30,<1` | ASGI Web 服务器 | BSD-3-Clause | https://github.com/Kludex/uvicorn |
```

补充一句：该表只覆盖直接运行时依赖，完整传递依赖以安装环境中的 package metadata 为准。

- [ ] **Step 5: Run the focused test and verify GREEN**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_final_evidence.FinalEvidenceTests.test_readme_lists_every_direct_dependency_license
```

Expected: PASS.

- [ ] **Step 6: Commit the license documentation**

```powershell
git add -- tests/test_final_evidence.py README.md
git commit -m "docs: document third-party dependency licenses"
```

### Task 4: Document the Open Design Deviation Honestly

**Files:**
- Modify: `tests/test_final_evidence.py`
- Modify: `SPEC.md`
- Modify: `README.md`
- Modify: `AGENT_LOG.md`

- [ ] **Step 1: Write the failing Open Design contract test**

```python
def test_spec_records_the_actual_open_design_decision(self):
    spec = read_text("SPEC.md")
    self.assertIn("Open Design", spec)
    self.assertIn("未采用", spec)
    self.assertIn("不追溯性声称", spec)
```

- [ ] **Step 2: Run the test and verify RED**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_final_evidence.FinalEvidenceTests.test_spec_records_the_actual_open_design_decision
```

Expected: FAIL because SPEC does not mention Open Design.

- [ ] **Step 3: Add the explicit deviation decision**

在 `SPEC.md` 技术选型中增加：

```markdown
### Open Design 决策

当前 WebUI 在早期实现中使用项目自定义的轻量界面样式，未采用 Open Design
设计系统或 skill。原因是最初范围被定义为 CLI 与静态报告，交互式 Web 产品壳
在后续阶段加入，而当时没有重新执行前端设计系统选型。这是对课程推荐流程的
真实偏离；本项目不追溯性声称已经使用 Open Design。本阶段只记录偏离和影响，
不借最终材料修复重做 UI；若后续进行 UI 重构，将先选择并记录设计系统与 skill。
```

在 README 已知限制和 `AGENT_LOG.md` 本阶段记录中引用同一事实，避免只有 SPEC 单点声明。

- [ ] **Step 4: Run focused tests and verify GREEN**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_final_evidence
```

Expected: PASS.

- [ ] **Step 5: Commit the Open Design decision**

```powershell
git add -- tests/test_final_evidence.py SPEC.md README.md AGENT_LOG.md
git commit -m "docs: record Open Design process deviation"
```

### Task 5: Separate Static Pages, Interactive WebUI, and Distribution Status

**Files:**
- Modify: `tests/test_final_evidence.py`
- Modify: `docs/FINAL_EVIDENCE_MATRIX.md`
- Modify: `docs/FINAL_SUBMISSION_CHECKLIST.md`
- Modify: `README.md`
- Modify: `SPEC.md`

- [ ] **Step 1: Write the failing boundary test**

```python
def test_submission_docs_do_not_claim_public_backend_or_registry(self):
    checklist = read_text("docs/FINAL_SUBMISSION_CHECKLIST.md")
    matrix = read_text("docs/FINAL_EVIDENCE_MATRIX.md")
    combined = "\n".join((checklist, matrix))
    self.assertIn("公开静态评审入口", combined)
    self.assertIn("公网交互式 Web 后端", combined)
    self.assertIn("公开容器 registry", combined)
    self.assertIn("待完成", combined)
    self.assertNotIn("| 公开 WebUI URL | 已完成 |", checklist)
```

- [ ] **Step 2: Run the test and verify RED**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_final_evidence.FinalEvidenceTests.test_submission_docs_do_not_claim_public_backend_or_registry
```

Expected: FAIL because the checklist currently labels the static Pages URL as a completed public WebUI and Dockerfile as completed distribution.

- [ ] **Step 3: Correct the status model**

在证据矩阵和提交清单中拆分：

```markdown
| 公开静态评审入口 | 已完成 | GitHub Pages 首页、demo、报告 |
| 本地交互式 WebUI | 已完成 | Docker/本地启动与确定性测试 |
| 公网交互式 Web 后端 | 待完成 | 后续独立部署阶段 |
| Docker 本地与 CI 构建 | 已完成 | Dockerfile 与 CI smoke |
| 公开容器 registry | 待完成 | 后续 GHCR 分发阶段 |
```

README 和 SPEC 保留已有静态/交互式边界，并明确“发布镜像不等于部署服务”。

- [ ] **Step 4: Run focused tests and verify GREEN**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_final_evidence
```

Expected: PASS.

- [ ] **Step 5: Commit the corrected delivery statuses**

```powershell
git add -- tests/test_final_evidence.py docs/FINAL_EVIDENCE_MATRIX.md docs/FINAL_SUBMISSION_CHECKLIST.md README.md SPEC.md
git commit -m "docs: distinguish static review and public deployment"
```

### Task 6: Close the Remote PR and CI Evidence Gate

**Files:**
- Create: `docs/evidence/github-actions-pr20-final.png`
- Modify: `tests/test_final_evidence.py`
- Modify: `docs/FINAL_EVIDENCE_MATRIX.md`
- Modify: `docs/FINAL_SUBMISSION_CHECKLIST.md`
- Modify: `AGENT_LOG.md`

- [ ] **Step 1: Verify and update PR attribution manually**

用户打开 PR #18、#19、#20，确认每个 PR 描述包含以下真实归属：

```markdown
## 执行归属

- 主开发 Agent：OpenAI Codex，按 Superpowers 流程执行。
- Subagent：本阶段采用 Inline Execution，未派发 subagent；原因记录在 AGENT_LOG.md。
- 人工参与：用户确认范围与设计，执行真实 LLM 手工验证、Git 暂存、提交、push 和 PR 操作。
- 自动测试：使用 Mock/Fake/Stub，不访问真实 Provider；手工真实 LLM 结果单独记录。
```

如某个 PR 的真实情况不同，按对应 `AGENT_LOG.md` 修正文案，不能机械复制错误事实。

- [ ] **Step 2: Capture current Actions evidence**

用户在 GitHub Actions 页面确认 PR #20 合并后的 `unit-test`、`docker-build` 和 Pages 均为成功状态，并保存完整截图到：

```text
docs/evidence/github-actions-pr20-final.png
```

截图必须显示仓库、工作流、commit/PR 和成功状态，不包含凭据或账户敏感信息。

- [ ] **Step 3: Add the new screenshot to the evidence test**

在 `SCREENSHOTS` 中增加：

```python
ROOT / "docs" / "evidence" / "github-actions-pr20-final.png",
```

- [ ] **Step 4: Run screenshot and evidence tests**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_final_evidence.FinalEvidenceTests.test_required_evidence_artifacts_exist_and_pngs_are_readable tests.test_final_evidence.FinalEvidenceTests.test_release_chain_and_screenshot_links_are_recorded
```

Expected: FAIL until the PNG exists and the matrix links it; then PASS after the real screenshot and link are added.

- [ ] **Step 5: Record only completed remote facts**

在证据矩阵、提交清单和 Agent Log 中记录已核对的 PR 归属与截图。若用户没有完成某项远端更新，该项保持“待完成”，本任务不得宣称 GREEN。

- [ ] **Step 6: Commit the remote evidence**

```powershell
git add -- tests/test_final_evidence.py docs/evidence/github-actions-pr20-final.png docs/FINAL_EVIDENCE_MATRIX.md docs/FINAL_SUBMISSION_CHECKLIST.md AGENT_LOG.md
git commit -m "docs: add current PR and CI attribution evidence"
```

### Task 7: Run Final Verification and Freeze the Evidence Snapshot

**Files:**
- Modify: `docs/FINAL_EVIDENCE_MATRIX.md`
- Modify: `docs/FINAL_SUBMISSION_CHECKLIST.md`
- Modify: `PLAN.md`
- Modify: `AGENT_LOG.md`

- [ ] **Step 1: Run document contracts**

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_final_evidence tests.test_workflows
```

Expected: PASS with no errors.

- [ ] **Step 2: Run the six deterministic mechanism demonstrations**

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_runner.RunnerTests.test_guardrail_block_is_recorded tests.test_runner.RunnerTests.test_gate_failure_feedback_changes_next_action tests.test_runner.RunnerTests.test_review_action_pauses_before_next_llm_call tests.test_runner.RunnerTests.test_resume_from_approved_approval_applies_payload_once_and_continues tests.test_cli.CliTests.test_repository_security_benchmark_smoke tests.test_cli.CliTests.test_repository_multi_strategy_benchmark_smoke
```

Expected: `Ran 6 tests` and `OK`.

- [ ] **Step 3: Run the complete suite**

```powershell
$env:PYTHONPATH="src"
python -m unittest discover -s tests
```

Expected: exit code 0 and `OK`. Capture the exact test count, duration and skipped count from this run.

- [ ] **Step 4: Run syntax and whitespace verification**

```powershell
python -m compileall -q src tests
node --check src/specgate/web_static/app.js
git diff --check
```

Expected: all commands exit 0 with no error output.

- [ ] **Step 5: Run credential-history checks**

```powershell
git check-ignore -v .env
git log --all --oneline -- .env
git grep -n -I -E "(sk-[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{30,})" -- . ":(exclude)tests" ":(exclude)docs/superpowers/plans"
```

Expected: `.env` is ignored; `.env` history is empty; credential scan has no real secret matches. Any fixture or documentation match must be inspected and documented rather than automatically ignored.

- [ ] **Step 6: Recheck public Pages**

Open and verify:

```text
https://yugarden404.github.io/SpecGate/
https://yugarden404.github.io/SpecGate/demo/
https://yugarden404.github.io/SpecGate/report/
```

Expected: all three pages load with their expected title and primary heading.

- [ ] **Step 7: Freeze the exact final result**

Replace the 908-test starting baseline in the “current final result” fields with the exact Step 3 output. Preserve 908 only where explicitly labeled as the 2026-07-16 review starting point. Add all task commit hashes to `PLAN.md` and the chronological result to `AGENT_LOG.md`.

- [ ] **Step 8: Re-run document contracts after the numeric update**

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_final_evidence tests.test_workflows
git diff --check
```

Expected: PASS and no whitespace errors.

- [ ] **Step 9: Commit the final verified snapshot**

```powershell
git add -- docs/FINAL_EVIDENCE_MATRIX.md docs/FINAL_SUBMISSION_CHECKLIST.md PLAN.md AGENT_LOG.md
git commit -m "docs: freeze verified final compliance snapshot"
```

- [ ] **Step 10: Perform two-stage review**

先运行规格合规审查，逐项对照设计文档第 2、3、5 至 13 节；再运行文档质量审查，检查事实冲突、模糊状态、失效链接、格式和敏感信息。Critical 或 Important 问题必须修复并重新执行相关测试。

- [ ] **Step 11: Verify branch cleanliness**

```powershell
git status --short
git log --oneline --decorate -10
```

Expected: working tree clean; recent commits correspond to Tasks 1 through 7 and the design/plan documents.
