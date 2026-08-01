# Course Compliance Evidence Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Synchronize SpecGate v0.2.0 architecture, process, task, release, and deterministic mechanism evidence with the AI4SE final-project requirements without changing production runtime code or student-authored reflection content.

**Architecture:** Treat the course documents as a one-way evidence chain: `SPEC.md` and `SPEC_PROCESS.md` own architecture and decisions, `PLAN.md` and `AGENT_LOG.md` own execution traceability, and `README.md` owns evaluator entry points. Add narrow `unittest` contracts in `tests/test_final_evidence.py` so stable facts remain synchronized without locking natural-language formatting.

**Tech Stack:** Markdown, Python 3.11+, standard-library `unittest`, PowerShell verification commands.

---

## File Structure

- Create: `docs/superpowers/specs/2026-07-31-course-compliance-evidence-sync-design.md` - approved scope and evidence model; already written before this plan.
- Create: `docs/superpowers/plans/2026-07-31-course-compliance-evidence-sync.md` - this task-by-task plan.
- Modify: `tests/test_final_evidence.py` - stable contracts for v0.2.0 task commits, architecture/process evidence, Release URL, and deterministic demos.
- Modify: `PLAN.md` - authoritative Task 1-18 completion ledger.
- Modify: `AGENT_LOG.md` - auditable per-task execution record and verified human decisions.
- Modify: `SPEC.md` - current v0.2.0 runtime architecture and corrected public-registry status.
- Modify: `SPEC_PROCESS.md` - architecture brainstorming, external review, confirmation, and execution-mode decisions.
- Modify: `README.md` - evaluator-facing Release and deterministic mechanism-demo entry points.
- Do not modify: `src/specgate/**`, `REFLECTION.md`, generated HTML reports, screenshots, or credential handling.

## Task 1: Add the v0.2.0 Task and Commit Evidence Contract

**Files:**
- Modify: `tests/test_final_evidence.py`
- Test: `tests/test_final_evidence.py`

- [x] **Step 1: Add the exact v0.2.0 commit map near `V011_RELEASE_FACTS`**

```python
V020_TASK_COMMITS = {
    1: ("61add59",),
    2: ("b3526b9",),
    3: ("02394f7",),
    4: ("7f6bffb",),
    5: ("9aff214",),
    6: ("556a5cb", "8677fd5"),
    7: ("b2a030d",),
    8: ("a179788",),
    9: ("6f823e9",),
    10: ("999e909",),
    11: ("cffc6e9",),
    12: ("78634b9",),
    13: ("d8ae083",),
    14: ("04743ec",),
    15: ("89bd035",),
    16: ("575af44",),
    17: ("47f639a",),
    18: ("674a1f4",),
}
```

- [x] **Step 2: Add a focused traceability test to `FinalEvidenceTests`**

```python
def test_v020_task_commits_are_traceable(self):
    plan = read_text("PLAN.md")
    agent_log = read_text("AGENT_LOG.md")
    plan_heading = "# 2026-07-31 v0.2.0 Agent Runtime 分层迁移"
    log_heading = "## 2026-07-31 v0.2.0 Agent Runtime 分层迁移"
    self.assertEqual(plan.count(plan_heading), 1)
    self.assertEqual(agent_log.count(log_heading), 1)
    plan_section = plan.split(plan_heading, 1)[1]
    log_section = agent_log.split(log_heading, 1)[1]

    for task, commits in V020_TASK_COMMITS.items():
        with self.subTest(task=task, document="PLAN"):
            self.assertIn(f"- [x] Task {task}:", plan_section)
        with self.subTest(task=task, document="AGENT_LOG"):
            self.assertIn(f"- Task {task}:", log_section)
        for commit in commits:
            with self.subTest(task=task, commit=commit):
                self.assertIn(f"`{commit}`", plan_section)
                self.assertIn(f"`{commit}`", log_section)

    for commit in ("72b791a", "fcd8026"):
        with self.subTest(design_commit=commit):
            self.assertIn(f"`{commit}`", plan_section)
            self.assertIn(f"`{commit}`", log_section)
```

- [x] **Step 3: Run the focused test and verify the intended RED state**

Run:

```powershell
python -m unittest -v tests.test_final_evidence.FinalEvidenceTests.test_v020_task_commits_are_traceable
```

Expected: `FAIL`; the first missing assertion refers to `- [x] Task 1:` or `- Task 1:`. Import and syntax errors are not an acceptable RED state.

- [x] **Step 4: Ask the user to commit the evidence contract**

The agent does not run Git commands. Give the user:

```powershell
git add -- tests/test_final_evidence.py docs/superpowers/specs/2026-07-31-course-compliance-evidence-sync-design.md docs/superpowers/plans/2026-07-31-course-compliance-evidence-sync.md
git diff --cached --check
git commit -m "test: 增加 v0.2.0 流程证据契约"
```

## Task 2: Make PLAN and AGENT_LOG Traceable

**Files:**
- Modify: `PLAN.md`
- Modify: `AGENT_LOG.md`
- Test: `tests/test_final_evidence.py`

- [x] **Step 1: Replace the aggregate v0.2.0 plan summary with an explicit completion ledger**

Keep the existing architecture goal and append these exact entries under `# 2026-07-31 v0.2.0 Agent Runtime 分层迁移`:

```markdown
- 设计基线：架构设计提交 `72b791a`；迁移计划提交 `fcd8026`。
- [x] Task 1: 声明 Agent Runtime 直接依赖（`61add59`）。
- [x] Task 2: 建立类型化运行状态协议（`b3526b9`）。
- [x] Task 3: 统一停止、挂起与恢复语义（`02394f7`）。
- [x] Task 4: 建立统一运行事件流（`7f6bffb`）。
- [x] Task 5: 建立 ToolDefinition 与可执行 Handler（`9aff214`）。
- [x] Task 6: 补充依赖许可证并统一 ToolRuntime（`556a5cb`、`8677fd5`）。
- [x] Task 7: 增加生命周期 HookBus（`b2a030d`）。
- [x] Task 8: 抽取不可绕过的 GovernanceEngine（`a179788`）。
- [x] Task 9: 组合统一 ActionPipeline 与 Gate adapter（`6f823e9`）。
- [x] Task 10: 增加角色无关 AgentLoop（`999e909`）。
- [x] Task 11: 用通用 Loop 执行单 Agent 运行（`cffc6e9`）。
- [x] Task 12: 增加安全、渐进式 Skill Registry（`78634b9`）。
- [x] Task 13: 注册 Skill 工具并接入上下文（`d8ae083`）。
- [x] Task 14: 增加 AgentService 运行边界（`04743ec`）。
- [x] Task 15: 统一审批挂起与恢复服务（`89bd035`）。
- [x] Task 16: 增加结构化多 Agent Workflow（`575af44`）。
- [x] Task 17: 迁移多 Agent 到版本化 Artifact Workflow（`47f639a`）。
- [x] Task 18: 收敛入口、报告、版本和最终验证（`674a1f4`）。
```

Remove unrelated v0.1.1 Stage B bullets currently placed inside the v0.2.0 section; preserve them in their existing v0.1.1 historical section if they are already recorded there.

- [x] **Step 2: Add the corresponding per-task ledger to `AGENT_LOG.md`**

Append these exact task lines within its existing v0.2.0 section:

```markdown
- 设计：`72b791a` 固化分层架构，`fcd8026` 固化迁移计划。
- Task 1: 直接依赖声明，提交 `61add59`。
- Task 2: 类型化 RunState 与 StateDelta，提交 `b3526b9`。
- Task 3: 停止、挂起和恢复语义，提交 `02394f7`。
- Task 4: 统一 RunEvent 流，提交 `7f6bffb`。
- Task 5: ToolDefinition 与 Handler，提交 `9aff214`。
- Task 6: 依赖许可证和 ToolRuntime，提交 `556a5cb`、`8677fd5`。
- Task 7: HookBus 生命周期，提交 `b2a030d`。
- Task 8: GovernanceEngine，提交 `a179788`。
- Task 9: ActionPipeline 与 Gate adapter，提交 `6f823e9`。
- Task 10: 角色无关 AgentLoop，提交 `999e909`。
- Task 11: 单 Agent 入口迁移，提交 `cffc6e9`。
- Task 12: Skill Registry，提交 `78634b9`。
- Task 13: Skill 工具和上下文接入，提交 `d8ae083`。
- Task 14: AgentService 运行边界，提交 `04743ec`。
- Task 15: 审批恢复服务，提交 `89bd035`。
- Task 16: 结构化 Workflow，提交 `575af44`。
- Task 17: 多 Agent Workflow 迁移，提交 `47f639a`。
- Task 18: 入口、报告、版本和最终验证，提交 `674a1f4`。
```

Then append this verified intervention and lesson block:

```markdown
### 人工决策与经验

- 用户要求分支名为 `v020-agent-runtime`，不使用 `codex/` 前缀；所有 Git 操作由用户执行。
- 用户明确排除 `.env`，真实模型凭据继续使用 OS keyring 或进程环境变量。
- Gate 保持独立且强制，Hook 只承担细粒度扩展检查；平台权限、路径和审批规则归 Governance。
- 外部 LLM 评审推动状态 patch 所有权、挂起/恢复、取消、验证阶段、Artifact、Workflow 预算和 Trace 边界进入最终设计。
- 实施开始采用 Subagent-Driven；后续任务按用户决定切换为 Inline Execution。
- 静态架构测试发现重复审批 continuation loop；移除后，审批恢复继续使用同一个 AgentLoop。
```

- [x] **Step 3: Run the traceability contract and verify GREEN**

Run:

```powershell
python -m unittest -v tests.test_final_evidence.FinalEvidenceTests.test_v020_task_commits_are_traceable
```

Expected: `Ran 1 test` and `OK`.

- [x] **Step 4: Ask the user to commit the task ledger**

```powershell
git add -- PLAN.md AGENT_LOG.md
git diff --cached --check
git commit -m "docs: 补齐 v0.2.0 任务与 Agent 记录"
```

## Task 3: Synchronize SPEC and SPEC_PROCESS with the Current Architecture

**Files:**
- Modify: `tests/test_final_evidence.py`
- Modify: `SPEC.md`
- Modify: `SPEC_PROCESS.md`
- Test: `tests/test_final_evidence.py`

- [x] **Step 1: Add the architecture and process evidence test**

```python
def test_v020_architecture_and_process_docs_are_current(self):
    spec = read_text("SPEC.md")
    process = read_text("SPEC_PROCESS.md")

    for phrase in (
        "# 2026-07-31 v0.2.0 Agent Runtime 补充规格",
        "AgentLoop",
        "ActionPipeline",
        "ToolDefinition -> ToolRegistry -> ToolRuntime -> ToolHandler",
        "HookBus",
        "GovernanceEngine",
        "Gate 保持独立",
        "SkillRegistry",
        "AgentService",
        "AgentArtifact",
        "SequentialReviewWorkflow",
    ):
        with self.subTest(document="SPEC", phrase=phrase):
            self.assertIn(phrase, spec)

    for stale in (
        "公开容器 registry 仍待后续 GHCR 分发阶段",
        "公开容器 registry 待后续独立阶段完成",
    ):
        with self.subTest(stale=stale):
            self.assertNotIn(stale, spec)

    for phrase in (
        "## 2026-07-31 v0.2.0 Agent Runtime 过程记录",
        "能力矩阵",
        "外部 LLM 评审",
        "Gate 与 Hook",
        "Subagent-Driven",
        "Inline Execution",
        "所有 Git 操作由用户执行",
        "不采用 `.env`",
    ):
        with self.subTest(document="SPEC_PROCESS", phrase=phrase):
            self.assertIn(phrase, process)
```

- [x] **Step 2: Run the architecture/process test and verify RED**

```powershell
python -m unittest -v tests.test_final_evidence.FinalEvidenceTests.test_v020_architecture_and_process_docs_are_current
```

Expected: `FAIL` because the new v0.2.0 headings and current architecture/process phrases are missing.

- [x] **Step 3: Correct the current distribution statement in `SPEC.md`**

In section 9.2 replace the stale registry sentence with:

```markdown
本地与 CI 构建形态为 Docker，镜像默认启动交互式 WebUI；README 和 `docs/DEPLOYMENT.md` 记录本地构建与后续服务器运行所需的持久化数据目录、Web 主密钥、安全 cookie 和固定 worker/队列配置。Mock 模式无需凭据即可启动。公开 GHCR CLI 镜像 `ghcr.io/yugarden404/specgate:0.1.1` 已发布并完成匿名拉取验证；发布镜像不等于部署公网交互式 Web 后端。
```

Update the historical risk bullet so it explicitly distinguishes then from now:

```markdown
- 风险：把静态 Pages、Dockerfile 或 CI build 误写成公网交互式后端或公开镜像分发。决策：当时先完成合规再部署；目前公开静态评审入口、本地交互式 WebUI 和公开 GHCR 镜像已完成，公网交互式 Web 后端仍未部署。
```

- [x] **Step 4: Append the v0.2.0 architecture supplement to `SPEC.md`**

```markdown
# 2026-07-31 v0.2.0 Agent Runtime 补充规格

本阶段把集中式 Runner 迁移为分层 Agent Runtime。入口层通过 AgentService 运行或恢复 Agent；AgentLoop 只负责上下文、模型调用、动作解析、状态推进和停止决策；ActionPipeline 统一组合 Hook、Governance、工具执行和执行后 Gate；Tool 与 Skill Runtime 提供可注册能力；RunState、RunEvent、WorkspacePolicy、审批和 Trace 形成不可绕过的运行基础。

核心边界如下：

- `AgentLoop` 不包含具体工具、角色、Skill 或 Workflow 名称分支。
- 工具链固定为 `ToolDefinition -> ToolRegistry -> ToolRuntime -> ToolHandler`，新增工具不修改 AgentLoop。
- `HookBus` 提供细粒度生命周期观察和附加限制；`GovernanceEngine` 承担不可关闭的平台权限、路径、配额和审批规则。
- Gate 保持独立，负责执行后结果检查和完成前最终验收，不降级为普通 Hook。
- `SkillRegistry` 采用 Catalog、Instructions、Resources 渐进加载，每个 AgentRun 使用独立 SkillSession。
- `AgentService` 统一运行、挂起、恢复、取消和预算边界；`SequentialReviewWorkflow` 只编排 AgentDefinition，并通过版本化 `AgentArtifact` 传递结果。
- 所有组件只产生类型化 StateDelta，由 RunStateStore 唯一应用；统一 RunEvent 流覆盖 Loop、Pipeline、Gate、审批、Skill 和 Workflow。

CLI、eval 和 Web 通过同一个 composition root 构造运行时。`AgentRunner` 仅保留兼容 facade，不再维护独立工具循环、角色循环或审批 continuation loop。
```

- [x] **Step 5: Append the confirmed decision record to `SPEC_PROCESS.md`**

```markdown
## 2026-07-31 v0.2.0 Agent Runtime 过程记录

本轮先依据课程要求和 learn-claude-code 的 Tool/Handler/Dispatch、Skill/Registry、Hook 与多 Agent 分层关系制作能力矩阵，再逐段确认 SpecGate 的迁移边界。结论不是替换现有 Gate，而是保持 Gate 与 Hook 双机制：Hook 处理细粒度生命周期扩展，Gate 负责不可跳过的确定性结果验收。

外部 LLM 评审指出状态 patch 所有权、挂起与终止区分、取消信号、前后验证阶段、审批恢复入口、Artifact 契约、Workflow 总预算和统一 Trace 等风险。经核对后，这些问题进入最终架构设计；角色差异只存在于 AgentDefinition 和 Workflow，AgentLoop、ContextBuilder 与 StopPolicy 不按角色名分支。

用户逐段确认架构、工具链、Skill、AgentService 和 Workflow 设计，并明确不采用 `.env`、分支名使用 `v020-agent-runtime`、所有 Git 操作由用户执行。实施开始采用 Subagent-Driven；Task 11 补做后，后续任务按用户决定切换为 Inline Execution。生产修改遵循 RED -> GREEN -> focused regression，最终再运行完整离线套件、Mock Demo、静态架构搜索和编译检查。
```

- [x] **Step 6: Run the architecture/process test and verify GREEN**

```powershell
python -m unittest -v tests.test_final_evidence.FinalEvidenceTests.test_v020_architecture_and_process_docs_are_current
```

Expected: `Ran 1 test` and `OK`.

- [x] **Step 7: Ask the user to commit the architecture/process sync**

```powershell
git add -- SPEC.md SPEC_PROCESS.md tests/test_final_evidence.py
git diff --cached --check
git commit -m "docs: 同步 Agent Runtime 架构与决策过程"
```

## Task 4: Add Release and Deterministic Mechanism Demo Entry Points

**Files:**
- Modify: `tests/test_final_evidence.py`
- Modify: `README.md`
- Test: `tests/test_final_evidence.py`

- [x] **Step 1: Add the evaluator-entry contract**

```python
def test_readme_exposes_release_and_deterministic_mechanism_demos(self):
    readme = read_text("README.md")
    release_url = "https://github.com/YuGarden404/SpecGate/releases/tag/v0.1.1"
    self.assertIn(release_url, readme)

    heading = "## 课程机制演示"
    self.assertEqual(readme.count(heading), 1)
    section = readme.split(heading, 1)[1].split("\n## ", 1)[0]
    for phrase in (
        "Guardrail 阻止危险动作",
        "Gate 失败反馈改变下一步动作",
        "HITL 审批挂起与恢复",
        "tests.test_runner.RunnerTests.test_guardrail_block_is_recorded",
        "tests.test_runner.RunnerTests.test_gate_failure_feedback_changes_next_action",
        "tests.test_cli.CliTests.test_cli_pending_approve_resume_applies_queue_and_writes_report",
        "不需要真实模型、网络或私有凭据",
    ):
        with self.subTest(phrase=phrase):
            self.assertIn(phrase, section)
```

- [x] **Step 2: Run the evaluator-entry test and verify RED**

```powershell
python -m unittest -v tests.test_final_evidence.FinalEvidenceTests.test_readme_exposes_release_and_deterministic_mechanism_demos
```

Expected: `FAIL` because the Release URL and `## 课程机制演示` section are absent.

- [x] **Step 3: Add the Release link to the README quick-entry list**

Add this bullet under `## 评审快速入口`:

```markdown
- GitHub Release：[v0.1.1](https://github.com/YuGarden404/SpecGate/releases/tag/v0.1.1)
```

- [x] **Step 4: Add the deterministic mechanism-demo section after `## 本地测试`**

````markdown
## 课程机制演示

下面三项使用 MockLLM、临时工作区和确定性本地规则，不需要真实模型、网络或私有凭据：

1. Guardrail 阻止危险动作：

   ```powershell
   python -m unittest -v tests.test_runner.RunnerTests.test_guardrail_block_is_recorded
   ```

2. Gate 失败反馈改变下一步动作：

   ```powershell
   python -m unittest -v tests.test_runner.RunnerTests.test_gate_failure_feedback_changes_next_action
   ```

3. HITL 审批挂起与恢复：

   ```powershell
   python -m unittest -v tests.test_cli.CliTests.test_cli_pending_approve_resume_applies_queue_and_writes_report
   ```

三项均应显示 `OK`。它们分别证明确定性安全拦截、Gate 反馈闭环，以及审批决定后重新校验并继续同一 Agent Runtime。
````

- [x] **Step 5: Run the evaluator-entry test and the three documented commands**

```powershell
python -m unittest -v tests.test_final_evidence.FinalEvidenceTests.test_readme_exposes_release_and_deterministic_mechanism_demos
python -m unittest -v tests.test_runner.RunnerTests.test_guardrail_block_is_recorded tests.test_runner.RunnerTests.test_gate_failure_feedback_changes_next_action tests.test_cli.CliTests.test_cli_pending_approve_resume_applies_queue_and_writes_report
```

Expected: the evidence contract reports `Ran 1 test` and `OK`; the mechanism command reports `Ran 3 tests` and `OK`.

- [x] **Step 6: Ask the user to commit the evaluator entry points**

```powershell
git add -- README.md tests/test_final_evidence.py
git diff --cached --check
git commit -m "docs: 增加课程机制演示入口"
```

## Task 5: Final Compliance Verification

**Files:**
- Verify: `SPEC.md`
- Verify: `SPEC_PROCESS.md`
- Verify: `PLAN.md`
- Verify: `AGENT_LOG.md`
- Verify: `README.md`
- Verify: `tests/test_final_evidence.py`
- Confirm unchanged: `src/specgate/**`
- Confirm unchanged: `REFLECTION.md`

- [x] **Step 1: Run the full final-evidence suite**

```powershell
python -m unittest -v tests.test_final_evidence
```

Expected: all final-evidence tests pass with `OK`.

- [x] **Step 2: Run the deterministic mechanism demo bundle**

```powershell
python -m unittest -v tests.test_runner.RunnerTests.test_guardrail_block_is_recorded tests.test_runner.RunnerTests.test_gate_failure_feedback_changes_next_action tests.test_cli.CliTests.test_cli_pending_approve_resume_applies_queue_and_writes_report
```

Expected: `Ran 3 tests` and `OK`.

- [x] **Step 3: Run static evidence scans**

```powershell
rg -n "\[x\] Task (1|2|3|4|5|6|7|8|9|10|11|12|13|14|15|16|17|18):" PLAN.md
rg -n "releases/tag/v0.1.1|课程机制演示" README.md
rg -n "公开容器 registry 仍待后续 GHCR 分发阶段|公开容器 registry 待后续独立阶段完成" SPEC.md
```

Expected: the first command reports all 18 tasks, the second reports both evaluator entries, and the third command has no matches.

- [x] **Step 4: Compile all Python source and tests**

```powershell
python -m compileall -q src tests
```

Expected: exit code 0 with no output.

- [x] **Step 5: Run the complete offline test suite**

```powershell
python -m unittest discover -s tests -v
```

Expected: all tests pass with `OK`; the existing platform-dependent skips remain skips rather than failures.

Review refresh on 2026-07-31: final evidence `Ran 34 tests in 0.325s`,
mechanism demos `Ran 3 tests in 2.037s`, compile exit code 0, and complete
offline suite `Ran 1136 tests in 415.001s` with `OK (skipped=29)`.

- [x] **Step 6: Ask the user to verify the final diff boundary**

The user runs:

```powershell
git status --short --branch
git diff --check
git diff --name-only
```

Expected changed files are limited to:

```text
AGENT_LOG.md
PLAN.md
README.md
SPEC.md
SPEC_PROCESS.md
docs/superpowers/plans/2026-07-31-course-compliance-evidence-sync.md
docs/superpowers/specs/2026-07-31-course-compliance-evidence-sync-design.md
tests/test_final_evidence.py
```

`REFLECTION.md` and every file under `src/specgate/` must be absent.

- [x] **Step 7: Ask the user to make the final verification commit if any verification-only text changed**

If no files changed during verification, no extra commit is required. If only truthful verification results were appended to `AGENT_LOG.md`, give the user:

```powershell
git add -- AGENT_LOG.md
git diff --cached --check
git commit -m "docs: 记录课程合规最终验证"
```

Do not record the full-suite result until the command has actually completed successfully.
