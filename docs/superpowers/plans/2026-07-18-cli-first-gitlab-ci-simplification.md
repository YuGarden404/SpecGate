# SpecGate CLI-first 与 GitLab CI 收缩 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 SpecGate 明确定位为以 GitHub 为开发基线的 CLI-first Coding Agent Harness，并把 NJU GitLab CI 收缩为可靠的 `unit-test` 验证。

**Architecture:** `specgate` CLI、Harness 内核与 GitHub Actions 保持不变；GitHub 继续承担完整测试、Docker 构建与 Pages 发布。NJU GitLab 作为课程镜像只运行 `unit-test` 和 CLI smoke，WebUI 保留为配套评审入口，不作为 Harness 内核。

**Tech Stack:** Python 3.11、`unittest`、GitLab CI YAML、GitHub Actions、Markdown、PNG 证据

---

### Task 1: 固化 GitLab CI 与第三次失败证据契约

**Files:**
- Modify: `tests/test_workflows.py`
- Modify: `tests/test_final_evidence.py`
- Create: `docs/evidence/gitlab-pipeline-buildkit-permission-failure.png`
- Create: `docs/evidence/gitlab-buildkit-rootless-permission-failure.png`

- [x] **Step 1: 将 GitLab 工作流契约改为 unit-test only**

把现有 BuildKit 断言替换为下列测试：

```python
def test_gitlab_pipeline_is_unit_test_only_on_shared_runner(self):
    workflow = (ROOT / ".gitlab-ci.yml").read_text(encoding="utf-8")
    normalized_lines = {line.strip() for line in workflow.splitlines()}

    self.assertIn("unit-test:", workflow)
    self.assertIn("python -m unittest discover -s tests -v", workflow)
    self.assertIn("- specgate --help", normalized_lines)

    for unsupported_build_dependency in (
        "docker-build:",
        "docker:26-dind",
        "kaniko-project",
        "moby/buildkit",
        "DOCKER_HOST",
        "docker build",
        "docker run",
        "buildctl",
    ):
        with self.subTest(dependency=unsupported_build_dependency):
            self.assertNotIn(unsupported_build_dependency, workflow)
```

- [x] **Step 2: 扩展最终证据契约**

在 `SCREENSHOTS` 中加入：

```python
ROOT / "docs" / "evidence" / "gitlab-pipeline-buildkit-permission-failure.png",
ROOT / "docs" / "evidence" / "gitlab-buildkit-rootless-permission-failure.png",
```

在 GitLab 事实短语契约中加入：

```python
"Pipeline #312797",
"operation not permitted",
"CLI-first",
"只保留 `unit-test`",
```

同时删除把 `moby/buildkit:rootless` 当作当前修复方案的要求；历史文本仍可记录 BuildKit。

- [x] **Step 3: 运行测试并确认 RED**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest `
  tests.test_workflows `
  tests.test_final_evidence.FinalEvidenceTests.test_nju_gitlab_initial_pipeline_failure_is_recorded_truthfully `
  tests.test_final_evidence.FinalEvidenceTests.test_required_evidence_artifacts_exist_and_pngs_are_readable
```

Expected: FAIL，原因包括 `.gitlab-ci.yml` 仍含 `docker-build`/BuildKit、仍 smoke `specgate-web`，以及新截图和 #312797 材料尚不存在。

- [x] **Step 4: 归档用户提供的两张 PNG**

```powershell
Copy-Item -LiteralPath `
  "C:\Users\Lenovo\AppData\Local\Temp\codex-clipboard-93700a81-a741-4a8b-af9f-e32be80f02a4.png" `
  -Destination "docs\evidence\gitlab-pipeline-buildkit-permission-failure.png"

Copy-Item -LiteralPath `
  "C:\Users\Lenovo\AppData\Local\Temp\codex-clipboard-46afdc67-25c9-46f5-a65c-b45d749dd400.png" `
  -Destination "docs\evidence\gitlab-buildkit-rootless-permission-failure.png"
```

Expected: 两张文件均存在且由 PNG 证据测试成功解析。

### Task 2: 收缩 GitLab CI 并统一 CLI-first 定位

**Files:**
- Modify: `.gitlab-ci.yml`
- Modify: `SPEC.md`
- Modify: `README.md`
- Modify: `docs/FINAL_EVIDENCE_MATRIX.md`
- Modify: `docs/FINAL_SUBMISSION_CHECKLIST.md`
- Modify: `docs/REFLECTION_FACT_CHECK.md`
- Modify: `PLAN.md`
- Modify: `AGENT_LOG.md`

- [x] **Step 1: 最小化 GitLab CI**

把 `.gitlab-ci.yml` 改为：

```yaml
stages:
  - test

unit-test:
  stage: test
  image: python:3.11-slim
  script:
    - python -m pip install -e .
    - export PYTHONPATH=src
    - python -m unittest discover -s tests -v
    - specgate --help
```

- [x] **Step 2: 更新 SPEC 与 README 产品定位**

在开头和范围说明中统一使用：

```text
SpecGate 是 CLI-first 的 Coding Agent Harness。`specgate` CLI 与 Harness 内核是核心产品；WebUI 是课程要求的配套评审与演示入口，不参与替代 Agent loop、工具、治理或 Gate。
```

保留 Web 模块、Web 测试、公开 URL 和部署边界；不新增 TUI/REPL，也不删除现有能力。

- [x] **Step 3: 更新三次 GitLab 失败时间线与 CI 分工**

所有最终材料统一记录：

```text
Pipeline #312781：DinD 因缺少 privileged 权限失败。
Pipeline #312784：Kaniko 镜像访问 gcr.io 超时。
Pipeline #312797：BuildKit 镜像拉取成功，但 RootlessKit 因 operation not permitted 无法启动。
三次 unit-test 均通过；Docker 构建由 GitHub Actions 成功证据覆盖。GitLab CI 现只保留 unit-test，等待新 Pipeline 验证。
```

在证据矩阵中引用两张新截图，并继续保留前两次失败截图。

- [x] **Step 4: 运行聚焦测试并确认 GREEN**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest `
  tests.test_workflows `
  tests.test_final_evidence.FinalEvidenceTests.test_nju_gitlab_initial_pipeline_failure_is_recorded_truthfully `
  tests.test_final_evidence.FinalEvidenceTests.test_required_evidence_artifacts_exist_and_pngs_are_readable `
  tests.test_final_evidence.FinalEvidenceTests.test_release_chain_and_screenshot_links_are_recorded
```

Expected: `OK`。

### Task 3: 完整验证与人工 Git 交接

**Files:**
- Verify: `.gitlab-ci.yml`
- Verify: `tests/test_final_evidence.py`
- Verify: `tests/test_workflows.py`
- Verify: all modified Markdown files

- [x] **Step 1: 验证 YAML 结构**

```powershell
python -c "import yaml; data=yaml.safe_load(open('.gitlab-ci.yml', encoding='utf-8')); assert set(data) == {'stages', 'unit-test'}; print('GitLab CI YAML: OK')"
```

Expected: `GitLab CI YAML: OK`。

- [x] **Step 2: 运行完整材料与工作流测试**

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_final_evidence tests.test_workflows
```

Expected: `OK`，0 failures。

- [x] **Step 3: 检查改动文件尾随空格**

对所有本轮修改的 YAML、Python 与 Markdown 文件执行尾随空格扫描。

Expected: 无命中。

- [x] **Step 4: 交给用户手动提交和推送**

建议中文 commit：

```text
fix(ci): 收缩 GitLab 流水线并突出 CLI 核心
```

用户将 `final-submission-sync` 推送到 NJU GitLab `main`。Pipeline #312806 与 job #595758 已通过并归档 URL 和截图；完成本次成功证据提交后，将完整分支推送到 GitHub 创建中文 PR。
