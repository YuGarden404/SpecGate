# 最终提交同步与双仓库交付 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 SpecGate 的最终材料同步到 PR #23 和 921 项测试快照，建立 NJU GitLab 课程镜像与 Pipeline 证据，并让学生反思、双仓库、截图和最终验收满足课程提交边界。

**Architecture:** GitHub 继续作为开发、PR、Actions 和 Pages 的权威来源；NJU GitLab 作为私有课程镜像并独立运行 `.gitlab-ci.yml`。仓库内通过 `tests/test_final_evidence.py` 先建立失败契约，再同步事实材料；`REFLECTION.md` 正文只由学生本人修改，外部 Git/截图/可见性操作只由用户执行。

**Tech Stack:** Python 3、`unittest`、Markdown 事实契约、GitHub Actions、GitLab CI、Docker、PowerShell、PNG 结构校验

---

## 执行约束

- Agent 不得执行任何 Git 命令，包括只读命令；所有 Git 命令由用户执行。
- 分支固定为 `final-submission-sync`，不得使用 `codex/` 前缀。
- 不修改 `src/specgate/`、WebUI 或其他生产代码。
- 不修改或代写 `REFLECTION.md` 正文；学生修改后 Agent 只做字数和事实检查。
- 不猜测 GitHub run URL、NJU GitLab 项目 URL、Pipeline URL、commit 或状态。
- 不把 GitHub Actions 成功写成 GitLab Pipeline 成功。
- 教师尚未回复前，公网交互式 Web 后端和公开容器 registry 保持待确认/待完成。
- NJU GitLab 首次同步只推送 `main` 与 tags，不推送旧本地功能分支。
- 截图必须不含 token、API key、主密钥、登录凭据或其他敏感信息。
- 主工作区 `docs/FINAL_SUBMISSION_CHECKLIST.md` 当前只有 LF/CRLF 换行差异；不得修改、覆盖或清理主工作区。

## 文件边界

计划内仓库变更：

- Create: `docs/superpowers/plans/2026-07-17-final-submission-sync.md`
- Create: `docs/evidence/github-actions-pr23-final.png`
- Create after user evidence: `docs/evidence/gitlab-pipeline-final.png`
- Modify: `tests/test_final_evidence.py`
- Modify: `docs/FINAL_EVIDENCE_MATRIX.md`
- Modify: `docs/FINAL_SUBMISSION_CHECKLIST.md`
- Modify: `docs/REFLECTION_FACT_CHECK.md`
- Modify: `README.md`
- Modify: `PLAN.md`
- Modify: `AGENT_LOG.md`
- Student-only modify: `REFLECTION.md`

不修改：

- `src/specgate/`
- `.gitlab-ci.yml`，除非真实 GitLab Pipeline 失败并证明配置需要修复
- `.github/workflows/`
- `Dockerfile`
- 公网部署与 GHCR 状态

### Task 1: 提交实施计划

**Files:**
- Create: `docs/superpowers/plans/2026-07-17-final-submission-sync.md`

- [ ] **Step 1: 用户检查计划文件**

在当前 worktree 执行：

```powershell
cd D:\code\NJU\SpecGate\.worktrees\final-submission-sync
git status --short --branch
git diff --check
git diff -- docs/superpowers/plans/2026-07-17-final-submission-sync.md
```

Expected：分支为 `final-submission-sync`；除新计划文件外没有意外改动；空白检查无错误。

- [ ] **Step 2: 用户提交计划文件**

```powershell
git add -- docs/superpowers/plans/2026-07-17-final-submission-sync.md
git diff --cached --check
git diff --cached --stat
git commit -m "docs: 规划最终提交同步与双仓库交付"
```

Expected：提交只包含实施计划。

### Task 2: 用 TDD 同步 PR #23 当前快照与 GitHub 证据

**Files:**
- Modify: `tests/test_final_evidence.py`
- Modify: `docs/FINAL_EVIDENCE_MATRIX.md`
- Modify: `docs/FINAL_SUBMISSION_CHECKLIST.md`
- Modify: `docs/REFLECTION_FACT_CHECK.md`
- Modify: `README.md`
- Modify: `PLAN.md`
- Modify: `AGENT_LOG.md`
- Create: `docs/evidence/github-actions-pr23-final.png`
- Test: `tests/test_final_evidence.py`

- [ ] **Step 1: 更新当前测试结果解析器**

把 `extract_current_final_run()` 改为只接受新的当前快照行：

```python
def extract_current_final_run(snapshot: str) -> tuple[str, str, float]:
    pattern = re.compile(
        r"^- 当前最终验证（2026-07-17 NJU SE Hub 审计分支）：`"
        r"(?P<result>Ran 921 tests in (?P<duration>[0-9]+(?:\.[0-9]+)?)s)`、"
        r"`OK \(skipped=27\)`，命令退出码为 0。$",
        re.MULTILINE,
    )
    matches = list(pattern.finditer(snapshot))
    if len(matches) != 1:
        raise AssertionError(
            f"expected one current final run in matrix snapshot, found {len(matches)}"
        )
    match = matches[0]
    duration = float(match.group("duration"))
    if duration <= 0:
        raise AssertionError("current final run duration must be positive")
    return match.group(0), match.group("result"), duration
```

- [ ] **Step 2: 扩展发布链和当前快照契约**

把发布列表补充为：

```python
releases = (
    (16, "116cc10", "fa3278a"),
    (17, "d550032", "e73e937"),
    (18, "d3607c4", "8d30ca5"),
    (19, "5279a7c", "b98563a"),
    (20, "e35eb46", "c39d101"),
    (21, "e34452c", "2082fc9"),
    (22, "a5861aa", "3905e1e"),
    (23, "5635ad2", "5fd86fa"),
)
```

将 `test_pr18_through_pr20_release_rows_are_exact_and_unique` 重命名为 `test_pr18_through_pr23_release_rows_are_exact_and_unique`，并把 `expected_releases` 替换为：

```python
expected_releases = (
    (
        "后端审计加固",
        "d3607c4",
        "8d30ca5",
        18,
        "https://github.com/YuGarden404/SpecGate/pull/18",
    ),
    (
        "Web 真实 LLM 接入",
        "5279a7c",
        "b98563a",
        19,
        "https://github.com/YuGarden404/SpecGate/pull/19",
    ),
    (
        "真实 LLM 生命周期修复",
        "e35eb46",
        "c39d101",
        20,
        "https://github.com/YuGarden404/SpecGate/pull/20",
    ),
    (
        "最终交付合规",
        "e34452c",
        "2082fc9",
        21,
        "https://github.com/YuGarden404/SpecGate/pull/21",
    ),
    (
        "LLM 连接测试超时修复",
        "a5861aa",
        "3905e1e",
        22,
        "https://github.com/YuGarden404/SpecGate/pull/22",
    ),
    (
        "NJU SE Hub 真实 LLM 审计",
        "5635ad2",
        "5fd86fa",
        23,
        "https://github.com/YuGarden404/SpecGate/pull/23",
    ),
)
```

将旧 `test_final_snapshot_uses_pr20_baseline_without_stale_branch_claims` 替换为：

```python
def test_final_snapshot_uses_pr23_main_and_latest_verification(self):
    matrix = MATRIX.read_text(encoding="utf-8")
    snapshot = matrix.split("## 3. 课程交付物", 1)[0]
    self.assertIn("main@5fd86fa", snapshot)
    self.assertIn("PR #23", snapshot)
    self.assertIn("当前最终验证", snapshot)
    current_line, current_run, duration = extract_current_final_run(snapshot)
    self.assertEqual(snapshot.count(current_line), 1)
    self.assertEqual(current_run.split(" in ", 1)[0], "Ran 921 tests")
    self.assertGreater(duration, 0)
    self.assertIn("CI #59", snapshot)
    self.assertIn("Pages #34", snapshot)
    self.assertIn("github-actions-pr23-final.png", snapshot)
    self.assertNotIn("最近已合并功能修复：PR #20", snapshot)
    self.assertNotIn("当前未提交分支", snapshot)
    self.assertNotIn("最终测试数字将在本阶段结束时刷新", snapshot)
```

同时把 `test_current_release_status_is_consistent_across_factual_materials` 的“当前状态”断言改为在矩阵快照、提交清单、反思事实清单、`PLAN.md` 最新阶段和 `AGENT_LOG.md` 最新阶段中共同要求：

```python
current_phrases = (
    "main@5fd86fa",
    "PR #23",
    "Ran 921 tests in 403.030s",
    "OK (skipped=27)",
    "CI #59",
    "Pages #34",
    "docs/evidence/github-actions-pr23-final.png",
)
for document, section in current_sections.items():
    for phrase in current_phrases:
        with self.subTest(document=document, phrase=phrase):
            self.assertIn(phrase, section)
```

原有 CI #53、Pages #31、`main@c39d101` 和 PR #20 断言保留在“历史证据”范围中，不得继续作为当前快照断言，也不得从历史表与截图说明中删除。

- [ ] **Step 3: 新增双仓库边界契约**

在 `FinalEvidenceTests` 中加入：

```python
def test_delivery_docs_distinguish_github_source_and_nju_gitlab_mirror(self):
    readme = read_text("README.md")
    matrix = read_text("docs/FINAL_EVIDENCE_MATRIX.md")
    checklist = read_text("docs/FINAL_SUBMISSION_CHECKLIST.md")
    combined = "\n".join((readme, matrix, checklist))

    for phrase in (
        "GitHub 开发主仓库",
        "NJU GitLab 课程镜像",
        "GitHub PR/Actions",
        "GitLab Pipeline",
        "Private",
        "检查前改为 Public",
    ):
        with self.subTest(phrase=phrase):
            self.assertIn(phrase, combined)

    self.assertNotIn("GitHub Actions 已迁移到 GitLab", combined)
    self.assertNotIn("公网交互式 Web 后端 | 已完成", combined)
    self.assertNotIn("公开容器 registry | 已完成", combined)
```

- [ ] **Step 4: 把 PR #23 截图加入截图契约**

在 `SCREENSHOTS` 元组追加：

```python
ROOT / "docs" / "evidence" / "github-actions-pr23-final.png",
```

并在发布链测试中要求矩阵包含：

```python
self.assertIn("docs/evidence/github-actions-pr23-final.png", matrix)
```

- [ ] **Step 5: 运行红灯**

```powershell
$env:PYTHONPATH="src"
python -m unittest `
  tests.test_final_evidence.FinalEvidenceTests.test_release_chain_and_screenshot_links_are_recorded `
  tests.test_final_evidence.FinalEvidenceTests.test_final_snapshot_uses_pr23_main_and_latest_verification `
  tests.test_final_evidence.FinalEvidenceTests.test_delivery_docs_distinguish_github_source_and_nju_gitlab_mirror
```

Expected：FAIL/ERROR。失败必须来自 PR #21–#23、当前快照、双仓库文字或截图尚未同步；不得通过放宽断言消除。

- [ ] **Step 6: 核验并复制 GitHub 截图**

源文件由用户提供：

```text
C:\Users\Lenovo\AppData\Local\Temp\codex-clipboard-a0418f5a-a9e2-424d-aed1-02aad479d069.png
```

复制到：

```text
docs/evidence/github-actions-pr23-final.png
```

复制前后使用 `validate_png_bytes()` 同等级检查确认 PNG 签名、CRC、IDAT 和 IEND 有效；人工确认截图显示 PR #23、CI #59、Pages #34 为绿色且不含凭据。

- [ ] **Step 7: 更新权威材料**

在 `docs/FINAL_EVIDENCE_MATRIX.md` 和 `docs/FINAL_SUBMISSION_CHECKLIST.md` 中使用同一当前行：

```markdown
- 当前最终验证（2026-07-17 NJU SE Hub 审计分支）：`Ran 921 tests in 403.030s`、`OK (skipped=27)`，命令退出码为 0。
```

同步加入：

```markdown
- 当前主线：`main@5fd86fa`，最近已合并阶段为 PR #23。
- GitHub 开发主仓库保留 commit、PR、Actions 与 Pages 证据。
- NJU GitLab 课程镜像初始为 Private，等待用户创建、首次同步和 Pipeline 通过；检查前改为 Public。
```

PR 表加入 #21–#23 精确行，并在截图章节加入：

```markdown
![PR #23 合并后的 GitHub Actions](evidence/github-actions-pr23-final.png)
```

`README.md` 增加“双仓库与课程提交”小节；`PLAN.md` 和 `AGENT_LOG.md` 追加 PR #22、PR #23 与当前阶段事实；`docs/REFLECTION_FACT_CHECK.md` 更新最新主线和审计事实。所有材料继续把公网后端和公开 registry 标为待教师确认/待完成。

- [ ] **Step 8: 运行绿灯和材料回归**

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_final_evidence tests.test_workflows
```

Expected：PASS；没有外部 GitLab 成功断言，因为该事实尚未发生。

- [ ] **Step 9: 用户提交当前快照同步**

```powershell
git add -- `
  tests/test_final_evidence.py `
  docs/FINAL_EVIDENCE_MATRIX.md `
  docs/FINAL_SUBMISSION_CHECKLIST.md `
  docs/REFLECTION_FACT_CHECK.md `
  docs/evidence/github-actions-pr23-final.png `
  README.md `
  PLAN.md `
  AGENT_LOG.md
git diff --cached --check
git diff --cached --stat
git commit -m "docs: 同步 PR23 最终证据与双仓库边界"
```

Expected：提交不包含 `REFLECTION.md`、生产代码或 GitLab 截图。

### Task 3: 学生本人修订反思并通过人工门禁

**Files:**
- Modify: `tests/test_final_evidence.py`
- Modify: `docs/REFLECTION_FACT_CHECK.md`
- Student-only Modify: `REFLECTION.md`
- Test: `tests/test_final_evidence.py`

- [ ] **Step 1: 写反思字数与过期事实失败契约**

在 `FinalEvidenceTests` 中加入：

```python
def test_reflection_is_student_owned_in_range_and_factually_current(self):
    reflection = read_text("REFLECTION.md")
    compact = re.sub(r"\s+", "", reflection)

    self.assertIn("本文件由学生本人完成", reflection)
    self.assertGreaterEqual(len(compact), 1500)
    self.assertLessEqual(len(compact), 2500)
    self.assertNotIn("未来 provider", reflection)
```

该测试只检查课程声明、机械字数和已确认过期事实，不检查观点或结论。

- [ ] **Step 2: 运行红灯**

```powershell
$env:PYTHONPATH="src"
python -m unittest `
  tests.test_final_evidence.FinalEvidenceTests.test_reflection_is_student_owned_in_range_and_factually_current
```

Expected：FAIL，因为当前非空白字符约 2877，且正文仍包含“未来 provider”。

- [ ] **Step 3: 更新事实核对清单**

`docs/REFLECTION_FACT_CHECK.md` 必须提示学生本人处理：

```text
- 将全文压缩到 1500–2500 字；建议 2200–2450 字。
- 把“未来 provider”改为 NJU SE Hub 四模型真实验证后的实际理解。
- 可选择 PR #22 假超时修复或 GitHub/NJU GitLab 双仓库作为判断变化案例。
- 教师未回复前，不声称公网后端或公开 registry 已豁免或已完成。
```

- [ ] **Step 4: 用户本人修改 `REFLECTION.md`**

用户自行删改、重写和确认观点。Agent 不提供可直接替换的段落，不执行该步骤。

- [ ] **Step 5: 运行反思门禁**

```powershell
$env:PYTHONPATH="src"
python -m unittest `
  tests.test_final_evidence.FinalEvidenceTests.test_reflection_remains_student_owned `
  tests.test_final_evidence.FinalEvidenceTests.test_reflection_is_student_owned_in_range_and_factually_current
```

Expected：PASS。若字数超限或仍有过期事实，只报告实际失败，不由 Agent 修改正文。

- [ ] **Step 6: 用户提交学生反思**

```powershell
git add -- REFLECTION.md docs/REFLECTION_FACT_CHECK.md tests/test_final_evidence.py
git diff --cached --check
git diff --cached --stat
git commit -m "docs: 更新学生反思与最终事实"
```

Expected：commit/PR 描述注明 `REFLECTION.md` 由学生本人修改，Agent 只提供事实和字数检查。

### Task 4: 用户创建 NJU GitLab 镜像并取得初始 Pipeline 证据

**Files:**
- Read: `.gitlab-ci.yml`
- External: NJU GitLab project and Pipeline

- [ ] **Step 1: 用户创建空项目**

在 `https://git.nju.edu.cn/` 创建名为 `SpecGate` 的 Private 空项目。不要初始化 README、`.gitignore` 或 License。

Expected：项目提供 HTTPS clone URL，默认仓库为空。

- [ ] **Step 2: 用户添加 NJU remote**

```powershell
cd D:\code\NJU\SpecGate
$njuUrl = Read-Host "NJU GitLab HTTPS clone URL"
git remote add nju $njuUrl
git remote -v
```

Expected：`origin` 仍指向 GitHub，`nju` 的 fetch/push 均指向 `git.nju.edu.cn`。clone URL 不得包含 token 或密码。

- [ ] **Step 3: 用户首次同步 `main` 与 tags**

```powershell
git push nju main
git push nju --tags
```

Expected：GitLab 收到 `main` 与 tags，只触发主线 Pipeline。旧本地分支不推送；其已合并提交仍由 `main` 的 merge 历史保留。

- [ ] **Step 4: 用户核对 commit 身份**

```powershell
$githubMain = git rev-parse origin/main
$njuMain = git rev-parse nju/main
"GitHub main: $githubMain"
"NJU main:    $njuMain"
"same commit: $($githubMain -eq $njuMain)"
```

Expected：`same commit: True`。若 `nju/main` 尚未获取，先由用户执行 `git fetch nju` 后重试。

- [ ] **Step 5: 用户等待初始 GitLab Pipeline**

打开 GitLab 项目的 Pipelines 页面，确认 `.gitlab-ci.yml` 的：

```text
unit-test: passed
docker-build: passed
pipeline: passed
```

若失败，保存 job 名、错误阶段和脱敏日志。不得用 GitHub Actions 的成功替代；只有真实失败证明 `.gitlab-ci.yml` 需要变更时，才进入单独的 systematic-debugging/TDD 修复。

- [ ] **Step 6: 用户提供脱敏证据**

提供：

- NJU GitLab 项目 URL。
- 通过的 Pipeline URL。
- 显示当前 commit 与项目的截图。
- 显示 `unit-test`、`docker-build` 和 Passed 的 Pipeline 截图。

截图不得显示 access token、密码、API key、主密钥、浏览器密码提示或个人敏感通知。

### Task 5: 用 TDD 记录 NJU GitLab 项目与 Pipeline 证据

**Files:**
- Modify: `tests/test_final_evidence.py`
- Modify: `docs/FINAL_EVIDENCE_MATRIX.md`
- Modify: `docs/FINAL_SUBMISSION_CHECKLIST.md`
- Modify: `README.md`
- Modify: `PLAN.md`
- Modify: `AGENT_LOG.md`
- Create: `docs/evidence/gitlab-pipeline-final.png`
- Test: `tests/test_final_evidence.py`

- [ ] **Step 1: 增加 GitLab 截图路径**

在 `SCREENSHOTS` 元组追加：

```python
ROOT / "docs" / "evidence" / "gitlab-pipeline-final.png",
```

- [ ] **Step 2: 写 GitLab 证据失败契约**

在 `FinalEvidenceTests` 中加入：

```python
def test_nju_gitlab_submission_mirror_and_pipeline_are_recorded(self):
    readme = read_text("README.md")
    matrix = read_text("docs/FINAL_EVIDENCE_MATRIX.md")
    checklist = read_text("docs/FINAL_SUBMISSION_CHECKLIST.md")
    combined = "\n".join((readme, matrix, checklist))

    project_urls = re.findall(
        r"https://git\.nju\.edu\.cn/[A-Za-z0-9_.~/-]+/SpecGate",
        combined,
        flags=re.IGNORECASE,
    )
    pipeline_urls = re.findall(
        r"https://git\.nju\.edu\.cn/[A-Za-z0-9_.~/-]+/SpecGate/-/pipelines/\d+",
        combined,
        flags=re.IGNORECASE,
    )
    self.assertTrue(project_urls)
    self.assertTrue(pipeline_urls)
    self.assertIn("unit-test", combined)
    self.assertIn("docker-build", combined)
    self.assertIn("Pipeline 已通过", combined)
    self.assertIn("docs/evidence/gitlab-pipeline-final.png", matrix)
    self.assertNotIn("GitLab Pipeline 待运行", combined)
```

若 GitLab 实际项目路径不是大小写为 `SpecGate`，先把正则中的末段改为用户提供的真实路径，再运行红灯；不得更改为不受约束的任意 URL。

- [ ] **Step 3: 运行红灯**

```powershell
$env:PYTHONPATH="src"
python -m unittest `
  tests.test_final_evidence.FinalEvidenceTests.test_nju_gitlab_submission_mirror_and_pipeline_are_recorded
```

Expected：FAIL/ERROR，因为截图和完成状态尚未进入材料。

- [ ] **Step 4: 核验并复制 GitLab 截图**

仅使用用户提供并确认脱敏的最终 Pipeline 截图，复制为：

```text
docs/evidence/gitlab-pipeline-final.png
```

使用 `validate_png_bytes()` 同等级结构检查；人工确认截图与用户提供的项目 URL、Pipeline URL 和 job 状态一致。

- [ ] **Step 5: 更新双仓库完成证据**

在 README、矩阵和清单中写入用户提供的精确项目 URL、Pipeline URL，并使用：

```markdown
- NJU GitLab 课程镜像：Private；检查前由学生改为 Public。
- GitLab Pipeline 已通过：`unit-test`、`docker-build` 均成功。
- GitHub PR/Actions 历史继续保留在 GitHub，没有迁移为 GitLab 平台元数据。
```

同步 `PLAN.md` 与 `AGENT_LOG.md`，明确 remote/push、项目创建、截图和可见性操作均由用户执行。

- [ ] **Step 6: 运行绿灯**

```powershell
$env:PYTHONPATH="src"
python -m unittest `
  tests.test_final_evidence.FinalEvidenceTests.test_nju_gitlab_submission_mirror_and_pipeline_are_recorded `
  tests.test_final_evidence
```

Expected：PASS；所有 URL 和状态来自实际 GitLab 页面。

- [ ] **Step 7: 用户提交 GitLab 证据**

```powershell
git add -- `
  tests/test_final_evidence.py `
  docs/FINAL_EVIDENCE_MATRIX.md `
  docs/FINAL_SUBMISSION_CHECKLIST.md `
  docs/evidence/gitlab-pipeline-final.png `
  README.md `
  PLAN.md `
  AGENT_LOG.md
git diff --cached --check
git diff --cached --stat
git commit -m "docs: 记录 NJU GitLab 镜像与流水线证据"
```

Expected：提交只记录真实 GitLab 证据，不包含 token、部署或 registry 完成声明。

### Task 6: 最终验证、GitHub PR 与双仓库收敛

**Files:**
- Verify: `tests/`
- Verify: `src/`
- Verify: `src/specgate/web_static/app.js`
- Verify: `Dockerfile`
- Verify: final evidence documents and screenshots

- [ ] **Step 1: 运行材料与工作流契约**

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_final_evidence tests.test_workflows
```

Expected：退出码 0，记录实际测试数量、耗时和 skipped 数量。

- [ ] **Step 2: 运行六项确定性核心机制**

```powershell
$env:PYTHONPATH="src"
python -m unittest `
  tests.test_runner.RunnerTests.test_guardrail_block_is_recorded `
  tests.test_runner.RunnerTests.test_gate_failure_feedback_changes_next_action `
  tests.test_runner.RunnerTests.test_review_action_pauses_before_next_llm_call `
  tests.test_runner.RunnerTests.test_resume_from_approved_approval_applies_payload_once_and_continues `
  tests.test_cli.CliTests.test_repository_security_benchmark_smoke `
  tests.test_cli.CliTests.test_repository_multi_strategy_benchmark_smoke
```

Expected：6 tests，全部通过。

- [ ] **Step 3: 运行完整测试套件**

```powershell
$env:PYTHONPATH="src"
python -m unittest discover -s tests -p "test*.py"
```

Expected：退出码 0；记录本阶段实际数量和耗时，不沿用 921 作为新分支测试数量。

- [ ] **Step 4: 运行静态检查**

```powershell
python -m compileall -q src tests
node --check src/specgate/web_static/app.js
```

Expected：两条命令退出码 0 且无错误输出。

- [ ] **Step 5: 运行 Docker smoke**

```powershell
docker build -t specgate:final-submission .
docker run --rm specgate:final-submission specgate-web --help
```

Expected：镜像构建成功，WebUI entrypoint 帮助命令退出码 0。该结果只证明本地分发构建，不代表公开 registry 或公网部署完成。

- [ ] **Step 6: 执行脱敏扫描**

对将提交的 Markdown、PNG 路径、源代码和配置执行疑似秘密模式扫描，至少覆盖：

```text
sk-[A-Za-z0-9_-]{8,}
ghp_[A-Za-z0-9]{20,}
github_pat_[A-Za-z0-9_]{20,}
AKIA[A-Z0-9]{16}
Authorization: Bearer followed by a non-example value
OPENAI_COMPATIBLE_API_KEY followed by a non-example value
SPECGATE_WEB_CREDENTIAL_KEY followed by a non-example value
```

排除明确的测试 fixture 和实施计划示例后，实际材料必须无命中。扫描只输出文件路径和分类，不输出秘密正文。

- [ ] **Step 7: 用户检查并推送 GitHub 分支**

```powershell
git status --short --branch
git diff --check
git log --oneline --decorate -8
git push -u origin final-submission-sync
```

Expected：阶段提交完整，工作区干净，远端创建同名分支。

- [ ] **Step 8: 用户创建中文 GitHub PR**

PR 标题：

```text
docs: 同步最终提交证据与 NJU GitLab 镜像
```

PR 描述必须区分：

```text
- Agent：设计、计划、事实契约、材料同步与测试。
- 学生：REFLECTION.md 正文、所有 Git 操作、GitLab 项目/remote/push、截图和访问权限。
- 自动验证：Mock/Fake/Stub，不访问真实 Provider。
- 公网后端与公开 registry：等待教师回复，未在本阶段完成。
```

- [ ] **Step 9: 用户合并并同步最终 main**

GitHub PR、CI 和 Pages 全部通过后，用户在主工作区执行：

```powershell
cd D:\code\NJU\SpecGate
git switch main
git pull --ff-only
git push nju main
git push nju --tags
git fetch nju
$githubMain = git rev-parse origin/main
$njuMain = git rev-parse nju/main
"same final commit: $($githubMain -eq $njuMain)"
```

Expected：`same final commit: True`。

- [ ] **Step 10: 用户核对最终外部门禁**

- GitHub 最终 PR 合并，Actions 与 Pages 通过。
- NJU GitLab 最新 `main` Pipeline 通过。
- NJU GitLab 当前仍为 Private，并已记录检查前改 Public 的步骤。
- 未登录访问测试留到改 Public 后执行。
- 教师部署/registry 回复仍按真实状态记录。

如果最终同步触发了新的 GitLab Pipeline，该最新 Pipeline 必须通过。仓库内已保存的截图可以是前一条证明 `.gitlab-ci.yml` 有效的通过记录；课程提交时还应提供 GitLab 页面上的最新 Pipeline 链接或外部截图，避免为更新截图再制造无限提交/Pipeline 循环。
