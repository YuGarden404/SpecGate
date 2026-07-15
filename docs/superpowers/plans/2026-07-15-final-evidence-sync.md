# 最终交付材料与验证证据同步 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立可自动检查的最终证据矩阵，并让课程交付材料与 `main@f45e73a` 的代码、Git/PR、CI/Pages 和 MockLLM 验证结果一致。

**Architecture:** 以 `docs/FINAL_EVIDENCE_MATRIX.md` 作为唯一权威证据账本，其他材料只保留面向各自读者的摘要和链接。新增 `tests/test_final_evidence.py` 对最终材料、截图、PR/commit 链和当前安全/运行时边界做确定性检查；生产代码保持不变，`REFLECTION.md` 只做事实核对、不由 Agent 改写。

**Tech Stack:** Markdown、Python 3.11 `unittest`、Git 历史、GitHub Actions/Pages 截图、MockLLM/StubLLM。

---

## 实施约束

- 当前分支必须是 `docs-final-evidence-sync`，基线为 `main@f45e73a`。
- 不修改 `src/specgate/`、Web 静态资源、Dockerfile 或 workflow 行为。
- 不调用真实 LLM，不依赖网络完成本地验收。
- 不伪造截图、Actions run ID、测试数量或未保存的阶段证据。
- `REFLECTION.md` 正文保持不变；只新增学生事实核对指南。
- Git 暂存、提交、推送和 PR 由用户执行；计划中的 Git 命令仅供最终交付使用。
- 两张截图来自用户在本会话提供的 GitHub Actions 页面，导入前必须人工确认不含凭据、本地文件路径或私有仓库信息。

## 文件职责映射

**新增：**

- `docs/FINAL_EVIDENCE_MATRIX.md`：课程要求、实现、测试、演示、Git/PR、CI/Pages 的权威账本。
- `docs/REFLECTION_FACT_CHECK.md`：只供学生本人核对过期事实，不提供代写段落。
- `docs/evidence/github-actions-web-runtime-and-credentials.png`：PR #13/#14 与安全凭据 Pages 失败/修复历史。
- `docs/evidence/github-actions-runtime-config.png`：PR #15、合并后 CI 与 Pages 成功证据。
- `tests/test_final_evidence.py`：最终材料一致性契约。

**修改：**

- `SPEC.md`：当前凭据、WebUI、运行时和 schema v4 配置模型。
- `README.md`：安装、目录结构、最终证据入口和当前能力摘要。
- `PLAN.md`：PR/commit/CI 回填和本阶段摘要。
- `AGENT_LOG.md`：最近阶段远端结果与本阶段过程证据。
- `SPEC_PROCESS.md`：最终审计的 brainstorming、人工决策和课程/PPT 对齐。
- `docs/FINAL_SUBMISSION_CHECKLIST.md`：最终交付与核心机制证据。
- `docs/PROJECT_WALKTHROUGH.md`：最终讲解和演示路径。
- `docs/AI4SE_Lab_9_12_Alignment.md`：从早期 MVP 描述同步为当前边界。
- `docs/DEPLOYMENT.md`：只在审计发现当前部署描述冲突时修改。
- `docs/superpowers/plans/2026-07-15-final-evidence-sync.md`：执行状态和最终验证证据。

**明确不修改：**

- `REFLECTION.md`。
- `src/specgate/**`。
- `.github/workflows/**`、`.gitlab-ci.yml`、`Dockerfile`。

## Task 1：记录基线并建立最终材料失败契约

**Files:**

- Create: `tests/test_final_evidence.py`
- Verify: `REFLECTION.md`

- [x] **Step 1：确认分支、基线和反思文件无改动**

Run:

```powershell
git status --short --branch
git rev-parse --short HEAD
git diff -- REFLECTION.md
```

Expected:

```text
## docs-final-evidence-sync
?? docs/superpowers/plans/2026-07-15-final-evidence-sync.md
?? docs/superpowers/specs/2026-07-15-final-evidence-sync-design.md
f45e73a
```

`git diff -- REFLECTION.md` 无输出。设计与计划文件是 brainstorming/writing-plans 阶段的预期未跟踪文件。

- [x] **Step 2：运行当前全量基线**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest discover -s tests
```

Expected: `OK (skipped=20)`，测试数不少于 822。命令中非法 `unsafe` governance profile 的 argparse 输出来自预期拒绝测试，不是失败。

- [x] **Step 3：写最终证据失败测试**

Create `tests/test_final_evidence.py`:

```python
from __future__ import annotations

import struct
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MATRIX = ROOT / "docs" / "FINAL_EVIDENCE_MATRIX.md"
REFLECTION_GUIDE = ROOT / "docs" / "REFLECTION_FACT_CHECK.md"
SCREENSHOTS = (
    ROOT / "docs" / "evidence" / "github-actions-web-runtime-and-credentials.png",
    ROOT / "docs" / "evidence" / "github-actions-runtime-config.png",
)
KEY_EVIDENCE_PATHS = (
    "src/specgate/runner.py",
    "src/specgate/actions.py",
    "src/specgate/tools.py",
    "src/specgate/policy.py",
    "src/specgate/gate.py",
    "src/specgate/approvals.py",
    "src/specgate/context.py",
    "src/specgate/credentials.py",
    "src/specgate/web_credentials.py",
    "src/specgate/web_runtime.py",
    "src/specgate/runtime_config.py",
    "tests/test_runner.py",
    "tests/test_gate.py",
    "tests/test_approvals.py",
    "tests/test_web_runtime.py",
    "tests/test_runtime_config.py",
    ".gitlab-ci.yml",
    ".github/workflows/ci.yml",
    ".github/workflows/pages.yml",
    "Dockerfile",
)


def read_text(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


class FinalEvidenceTests(unittest.TestCase):
    def test_required_evidence_artifacts_exist_and_pngs_are_readable(self):
        self.assertTrue(MATRIX.is_file())
        self.assertTrue(REFLECTION_GUIDE.is_file())
        for screenshot in SCREENSHOTS:
            with self.subTest(screenshot=screenshot.name):
                raw = screenshot.read_bytes()
                self.assertEqual(raw[:8], b"\x89PNG\r\n\x1a\n")
                self.assertGreaterEqual(len(raw), 24)
                width, height = struct.unpack(">II", raw[16:24])
                self.assertGreaterEqual(width, 1000)
                self.assertGreaterEqual(height, 500)

    def test_release_chain_and_screenshot_links_are_recorded(self):
        matrix = MATRIX.read_text(encoding="utf-8")
        releases = (
            (11, "e17b8e5", "f2b4e88"),
            (12, "fecc5e3", "80be31b"),
            (13, "20c0102", "73fbb34"),
            (14, "e5fc981", "49f66a2"),
            (15, "a523137", "f45e73a"),
        )
        for pr, feature_commit, merge_commit in releases:
            with self.subTest(pr=pr):
                self.assertIn(
                    f"https://github.com/YuGarden404/SpecGate/pull/{pr}",
                    matrix,
                )
                self.assertIn(feature_commit, matrix)
                self.assertIn(merge_commit, matrix)
        for screenshot in SCREENSHOTS:
            self.assertIn(f"evidence/{screenshot.name}", matrix)

    def test_readme_has_required_delivery_sections(self):
        readme = read_text("README.md")
        for heading in (
            "## 评审快速入口",
            "## 安装",
            "## 本地测试",
            "## Mock Demo",
            "## 目录结构",
            "## Docker / 服务器部署",
            "## 已知限制",
            "## 安全边界",
        ):
            with self.subTest(heading=heading):
                self.assertIn(heading, readme)
        self.assertIn("docs/FINAL_EVIDENCE_MATRIX.md", readme)

    def test_spec_describes_current_credentials_runtime_and_config(self):
        spec = read_text("SPEC.md")
        for phrase in (
            "操作系统 keyring",
            "AES-256-GCM",
            "固定 worker",
            "有界队列",
            "schema v4",
            "runtime_config_json",
            "不可变配置快照",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, spec)
        for stale in (
            "`.env` 只作为本地开发 fallback",
            "实现 `.env` 本地开发 fallback",
            "WebUI 是静态报告站点",
        ):
            with self.subTest(stale=stale):
                self.assertNotIn(stale, spec)

    def test_final_review_docs_describe_current_boundaries(self):
        combined = "\n".join(
            read_text(path)
            for path in (
                "docs/FINAL_SUBMISSION_CHECKLIST.md",
                "docs/PROJECT_WALKTHROUGH.md",
                "docs/AI4SE_Lab_9_12_Alignment.md",
            )
        )
        for phrase in (
            "AES-256-GCM",
            "WebRuntimeCoordinator",
            "runtime_config_json",
            "HITL",
            "MockLLM",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, combined)
        self.assertNotIn("支持 `.env` fallback", combined)

    def test_matrix_references_existing_implementation_and_test_paths(self):
        matrix = MATRIX.read_text(encoding="utf-8")
        for relative in KEY_EVIDENCE_PATHS:
            with self.subTest(relative=relative):
                self.assertTrue((ROOT / relative).is_file())
                self.assertIn(f"`{relative}`", matrix)

    def test_reflection_remains_student_owned(self):
        reflection = read_text("REFLECTION.md")
        guide = REFLECTION_GUIDE.read_text(encoding="utf-8")
        self.assertIn("本文件由学生本人完成", reflection)
        self.assertIn("不提供可直接替换的反思段落", guide)
        self.assertIn("由学生本人修改", guide)


if __name__ == "__main__":
    unittest.main()
```

- [x] **Step 4：运行失败测试确认 RED**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_final_evidence
```

Expected: FAIL/ERROR，至少包括：

- `docs/FINAL_EVIDENCE_MATRIX.md` 不存在。
- `docs/REFLECTION_FACT_CHECK.md` 不存在。
- 两张截图不存在。
- README 缺少 `## 安装` 和 `## 目录结构`。
- `SPEC.md` 仍包含 `.env fallback` 和静态 WebUI-only 描述。

不要为了让测试提前通过而削弱断言。

## Task 2：导入截图并建立权威证据账本

**Files:**

- Create: `docs/evidence/github-actions-web-runtime-and-credentials.png`
- Create: `docs/evidence/github-actions-runtime-config.png`
- Create: `docs/FINAL_EVIDENCE_MATRIX.md`
- Create: `docs/REFLECTION_FACT_CHECK.md`
- Test: `tests/test_final_evidence.py`

- [x] **Step 1：创建证据目录并复制已审核截图**

Run:

```powershell
New-Item -ItemType Directory -Force docs/evidence
Copy-Item -LiteralPath "C:\Users\Lenovo\AppData\Local\Temp\codex-clipboard-e81df422-8bf6-46c6-b58a-fc820961d6ba.png" -Destination "docs\evidence\github-actions-web-runtime-and-credentials.png"
Copy-Item -LiteralPath "C:\Users\Lenovo\AppData\Local\Temp\codex-clipboard-6a418f04-90a4-400c-abda-2e0fb749d6ce.png" -Destination "docs\evidence\github-actions-runtime-config.png"
```

Expected: 两个目标 PNG 存在。第一张展示安全凭据 Pages 失败、PR #13 修复成功和 PR #14 成功；第二张展示 PR #15 及合并后的 CI/Pages 成功。截图不得裁剪或重新绘制，保留原始证据。

- [x] **Step 2：创建权威证据矩阵**

Create `docs/FINAL_EVIDENCE_MATRIX.md`，使用以下固定结构和事实：

```markdown
# SpecGate 最终验证证据矩阵

## 1. 证据口径

本文件是最终交付的权威证据入口。事实优先级为：当前代码与测试 → Git/PR → CI/Pages 与截图 → 当时的 Agent Log → 旧说明文档。课程自动验收只使用 MockLLM/StubLLM，不需要真实 LLM、API key 或网络。

## 2. 最终版本快照

- 文档同步基线：`main@f45e73a`。
- 最近功能合并：PR #15，Runner 配置接线。
- 本地功能基线：`Ran 822 tests ... OK (skipped=20)`，记录于 `AGENT_LOG.md`。
- 远端最终状态：PR #15 合并后的 CI #43 与 Pages #26 为绿色，见 `evidence/github-actions-runtime-config.png`。
- 公开入口：<https://yugarden404.github.io/SpecGate/>。

## 3. 课程交付物

| 要求 | 状态 | 仓库证据 | 复现方式 |
| --- | --- | --- | --- |
| SPEC / PLAN / 过程记录 | 已完成 | `SPEC.md`、`PLAN.md`、`SPEC_PROCESS.md` | 从 README 评审入口阅读 |
| 自实现 Harness | 已完成 | `src/specgate/runner.py`、`src/specgate/actions.py`、`src/specgate/tools.py` | Runner 机制测试 |
| MockLLM 确定性测试 | 已完成 | `tests/test_runner.py`、`tests/test_cli.py` | `python -m unittest tests.test_runner tests.test_cli` |
| 凭据治理 | 已完成 | `src/specgate/credentials.py`、`src/specgate/web_credentials.py` | 凭据测试，无明文回显 |
| 分发 | 已完成 | `Dockerfile`、`.gitlab-ci.yml` | Docker build/smoke 与 CI |
| 公开 WebUI | 已完成 | `README.md`、`.github/workflows/pages.yml` | 打开 Pages URL |
| 学生反思 | 学生负责最终确认 | `REFLECTION.md`、`docs/REFLECTION_FACT_CHECK.md` | 学生本人复核过期事实 |

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
| 不可变运行配置 | `src/specgate/runtime_config.py`、`src/specgate/web_db.py` | `tests/test_runtime_config.py`、`tests/test_web_db.py` | schema v4 `runtime_config_json` 快照 |
| Trace / Debug / Audit | `src/specgate/trace.py`、`src/specgate/web_debug.py` | `tests/test_web_debug.py`、`tests/test_web_static.py` | 实际运行配置和审计证据 |

## 5. 最近阶段 Git / PR / CI

| 阶段 | 功能 commit | Merge commit | PR | 远端证据 |
| --- | --- | --- | --- | --- |
| Gate/HITL | `e17b8e5` | `f2b4e88` | [#11](https://github.com/YuGarden404/SpecGate/pull/11) | PR 与最终 main CI |
| 安全凭据 | `fecc5e3` | `80be31b` | [#12](https://github.com/YuGarden404/SpecGate/pull/12) | Pages 失败历史保留在截图 |
| Pages 热修复 | `20c0102` | `73fbb34` | [#13](https://github.com/YuGarden404/SpecGate/pull/13) | `evidence/github-actions-web-runtime-and-credentials.png` |
| Web 运行时 | `e5fc981` | `49f66a2` | [#14](https://github.com/YuGarden404/SpecGate/pull/14) | `evidence/github-actions-web-runtime-and-credentials.png` |
| Runner 配置 | `a523137` | `f45e73a` | [#15](https://github.com/YuGarden404/SpecGate/pull/15) | `evidence/github-actions-runtime-config.png` |

## 6. CI 与截图说明

![安全凭据、Pages 热修复与 Web Runtime Actions](evidence/github-actions-web-runtime-and-credentials.png)

截图如实保留 PR #12 合并后的 Pages 失败，以及 PR #13 修复后 CI/Pages 和 PR #14 成功。失败不是最终状态，但属于重要调试证据。

![Runner 配置接线与最终 main Actions](evidence/github-actions-runtime-config.png)

截图记录 PR #15、合并后 main CI #43 和 Pages #26 均通过。Workflow 定义见 `.github/workflows/ci.yml`、`.github/workflows/pages.yml`；GitLab 课程要求见 `.gitlab-ci.yml`，Docker 分发见 `Dockerfile`。

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

## 9. 边界

- 自动验收只使用 MockLLM/StubLLM。
- 不开放 shell，不执行同源模型生成 HTML。
- CLI 持久化凭据使用 OS keyring；Web 使用独立主密钥和 AES-256-GCM。
- `.env` 只作为被保护路径和威胁示例出现，SpecGate 不读写 `.env`。
- 旧 HMAC 只作为迁移来源，迁移后要求重新录入。
- `REFLECTION.md` 的观点和最终文字由学生本人负责。
```

在 Task 6 得到新鲜全量结果后，在“最终版本快照”和“完整验证”下追加 unittest 实际输出中以 `Ran ` 开头的完整统计行；不得预填未经运行的数字。

- [x] **Step 3：创建学生反思事实核对表**

Create `docs/REFLECTION_FACT_CHECK.md`:

```markdown
# REFLECTION.md 事实核对清单

> 本文件只帮助学生核对仓库事实，不提供可直接替换的反思段落。`REFLECTION.md` 的观点、案例选择、批判结论和最终文字必须由学生本人修改并确认。

## 1. 凭据与分发章节

- 过期事实：正文仍把 `credential_status()` 存根和 `.env fallback` 描述为最终实现。
- 当前事实：CLI 的进程环境变量只读且优先；持久化使用操作系统 keyring；Web 使用独立主密钥和 AES-256-GCM；SpecGate 不读写 `.env`。
- 请学生本人说明：安全凭据阶段如何改变了你对“mock 项目也要做凭据治理”的理解。

## 2. Subagent 工作流章节

- 需要限定时间范围：早期 MVP 确实主要使用 Gemini 冷启动验证；Context Harness Deepening 阶段后来使用了独立实现/规格/质量审查 agent；Gate/HITL 之后因当前协作规则和人工选择改为主线程 Inline Execution。
- 请学生本人判断：不同阶段的 agent 使用方式如何影响你对 subagent 边界的结论。

## 3. WebUI 与部署章节

- 过期事实：部分表述仍把 WebUI 等同于静态报告。
- 当前事实：仓库同时包含交互式 Web 产品壳和 GitHub Pages 静态展示；Web 产品壳具备项目导入、运行、审批、取消、Debug/Audit 与产物下载。
- 请学生本人决定是否补充：为何保留静态 Pages 作为低成本评审入口。

## 4. 上下文与主要贡献章节

- 过期事实：只描述 Context Manifest，没有覆盖后续 Select/Compress/Isolate、Prompt Injection Benchmark、Gate/HITL 和运行配置快照。
- 当前事实：治理是主要贡献；上下文深化和 Web 运行可靠性提供了可测的辅助证据。
- 请学生本人选择最能代表判断变化的一个案例，不要罗列所有功能。

## 5. 最终证据

- 当前最终功能基线为 `main@f45e73a`；PR #11–#15 已合并。
- PR #12 合并后一度出现 Pages 依赖失败，PR #13 修复；这是适合人工反思的“验证发现真实交付缺口”案例。
- 请学生本人核对全文是否满足课程要求的 1500–2500 字，并确认“AI 只参与润色和结构整理”的声明与实际使用方式一致。
```

- [x] **Step 4：运行证据文件聚焦测试**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest `
  tests.test_final_evidence.FinalEvidenceTests.test_required_evidence_artifacts_exist_and_pngs_are_readable `
  tests.test_final_evidence.FinalEvidenceTests.test_release_chain_and_screenshot_links_are_recorded `
  tests.test_final_evidence.FinalEvidenceTests.test_matrix_references_existing_implementation_and_test_paths `
  tests.test_final_evidence.FinalEvidenceTests.test_reflection_remains_student_owned
```

Expected: PASS。其他 final evidence tests 仍可能因尚未同步 SPEC/README/最终讲解材料而失败。

## Task 3：同步 SPEC 与 README 当前事实

**Files:**

- Modify: `SPEC.md:296-314, 340-479`
- Modify: `README.md:7-78, 296-440`
- Test: `tests/test_final_evidence.py`

- [x] **Step 1：修正 SPEC 凭据威胁模型**

Replace `SPEC.md` §6.2 的旧 `.env fallback` 对策为：

```markdown
对策：

- 课程自动验收、WebUI 和默认 demo 使用 `MockLLM`，不需要凭据。
- CLI 允许进程环境变量作为只读、最高优先级的临时来源；日常持久化使用操作系统 keyring，包括 Windows Credential Manager、macOS Keychain 和 Linux Secret Service。
- SpecGate 不读取或写入 `.env`，keyring 不可用时真实 provider fail closed。
- Web 只保存 `openai-compatible` 凭据，使用独立 `SPECGATE_WEB_CREDENTIAL_KEY` 和 AES-256-GCM；普通数据库表、HTTP 响应、异常和 Trace 不得出现明文。
- 旧 HMAC 状态只作为 schema v1→v2 迁移来源，迁移后标记 `requires_reentry`，不能继续作为凭据使用。
- `credentials status` 只返回配置状态，所有日志和 trace 继续执行 redaction。
- guardrail、WorkspacePolicy 和安全文件接口强制动作、路径和链接边界。
```

- [x] **Step 2：扩展 SPEC 当前架构与配置模型**

After the core architecture diagram in `SPEC.md`, add:

```markdown
### 7.1 当前 Web 运行架构

交互式 Web 产品壳使用 `WebRuntimeCoordinator` 的固定 worker 和有界队列。SQLite schema v4 保存用户 Settings 和每个 run 的 `runtime_config_json` 不可变配置快照；首次执行、HITL resume 和 queued 重启恢复只使用创建时快照。取消、超时、发布和恢复使用显式状态转换，Debug/Audit 展示实际生效配置。

GitHub Pages 仍提供静态首页、demo 和报告，作为无需登录、无需服务器进程的公开评审入口；它与交互式 Web 产品壳是两个不同入口。
```

Append to `SPEC.md` §8.5 Config:

```markdown
Web run 的 schema v4 配置模型额外包含：`governance_profile`、`context_strategy`、`max_steps`、`context_budget_chars`、`retrieval_top_k`、`retrieval_budget_chars` 和 `compression_max_tool_result_chars`。创建 run 时七项字段规范化为 `runtime_config_json` 不可变配置快照；后续 Settings 修改不得影响已有 run。
```

- [x] **Step 3：修正 SPEC 凭据、分发与验收状态**

Replace `SPEC.md` §9.1–9.3 current-state paragraphs with:

```markdown
### 9.1 凭据

Mock 模式不需要 key。CLI 的 `specgate credentials status/set/clear <provider>` 使用操作系统 keyring；进程环境变量是只读、最高优先级的临时来源。Web 使用独立主密钥和 AES-256-GCM 保存 `openai-compatible` API key，支持查看状态、更新和清除，但当前 Web Runner 不读取该凭据，课程验收继续只运行 MockLLM。

### 9.2 分发

分发形态为 Docker。镜像默认启动交互式 WebUI；README 和 `docs/DEPLOYMENT.md` 说明本地构建、服务器运行、持久化数据目录、Web 主密钥、安全 cookie 和固定 worker/队列配置。Mock 模式无需凭据即可启动。

### 9.3 WebUI URL

GitHub Pages 发布静态首页、知识图谱 demo 和运行报告，README 提供三个公开 URL。交互式 Web 产品壳由 Docker/服务器启动，支持项目导入、MockLLM run、HITL、取消、Debug/Audit 和产物下载；生成 HTML 不在同源认证上下文中直接执行。
```

Add to `SPEC.md` acceptance criteria:

```markdown
- Web 使用固定 worker、有界队列，并对取消、超时、重启恢复和发布竞争进行确定性测试。
- schema v4 run 配置快照对首次执行、resume 和重启恢复保持一致。
- 最终证据矩阵把重要能力映射到实现、测试、PR 和 CI/Pages。
```

- [x] **Step 4：补齐 README 安装和目录结构**

Add after `## 当前状态`:

~~~~markdown
## 安装

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
```

课程自动验收和 Mock Demo 不需要 API key。CLI 可选真实 provider 的安全配置见“CLI 凭据管理”，Web 主密钥见“Docker / 服务器部署”。

## 目录结构

```text
src/specgate/                 自实现 harness、Web 服务与安全原语
tests/                        MockLLM 和确定性机制测试
examples/knowledge_nav/       可重复运行的 mock demo
examples/eval_cases/          治理、注入、上下文和 HITL eval cases
docs/superpowers/             设计与实施计划
docs/evidence/                最终 CI/Pages 截图证据
skills/                       SpecGate 可复用 Skill
.github/workflows/            GitHub CI 与 Pages
```
~~~~

When writing the outer Markdown, use four-space indentation or a longer fence so the nested `powershell` and `text` fences render correctly.

- [x] **Step 5：强化 README 评审入口与当前状态**

Add to `## 评审快速入口`:

```markdown
- 最终证据矩阵：`docs/FINAL_EVIDENCE_MATRIX.md`
- 反思事实核对：`docs/REFLECTION_FACT_CHECK.md`（由学生本人修改 `REFLECTION.md`）
```

Replace `## 当前状态` with a concise current summary covering:

```markdown
- 自实现 Agent loop、Action/Tool、Gate 反馈和 MockLLM 确定性闭环。
- Workspace 路径安全、HITL revision/CAS、最终 Gate 和发布摘要绑定。
- Select/Compress/Isolate 上下文策略与安全 benchmark。
- OS keyring、Web AES-256-GCM 和旧 HMAC `requires_reentry` 迁移。
- 固定 worker、有界队列、取消/超时/重启恢复。
- schema v4 `runtime_config_json` 不可变配置快照与 Debug/Audit 展示。
- Docker、GitLab CI、GitHub CI/Pages 和公开静态评审入口。
```

- [x] **Step 6：运行 SPEC/README 聚焦测试**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest `
  tests.test_final_evidence.FinalEvidenceTests.test_readme_has_required_delivery_sections `
  tests.test_final_evidence.FinalEvidenceTests.test_spec_describes_current_credentials_runtime_and_config
```

Expected: PASS。

## Task 4：同步最终清单、项目讲解和 Lab 对齐材料

**Files:**

- Modify: `docs/FINAL_SUBMISSION_CHECKLIST.md`
- Modify: `docs/PROJECT_WALKTHROUGH.md`
- Modify: `docs/AI4SE_Lab_9_12_Alignment.md`
- Inspect/Modify if stale: `docs/DEPLOYMENT.md`
- Test: `tests/test_final_evidence.py`

- [x] **Step 1：升级最终提交清单**

In `docs/FINAL_SUBMISSION_CHECKLIST.md`:

1. Add `docs/FINAL_EVIDENCE_MATRIX.md` and `docs/evidence/` to the delivery table.
2. Replace the credential row with:

```markdown
| 凭据边界 | `src/specgate/credentials.py`、`src/specgate/web_credentials.py` | CLI 使用环境变量只读优先和 OS keyring 持久化；Web 使用独立主密钥与 AES-256-GCM；旧 HMAC 迁移为 `requires_reentry`。 |
```

3. Add rows:

```markdown
| HITL 正确性 | `src/specgate/approvals.py`、`src/specgate/web_approvals.py` | revision/CAS、`applying` claim、resume 幂等和最终 Gate。 |
| Web 运行时 | `src/specgate/web_runtime.py`、`src/specgate/web_runs.py` | `WebRuntimeCoordinator` 固定 worker、有界队列、取消、超时与重启恢复。 |
| 运行配置 | `src/specgate/runtime_config.py`、`src/specgate/web_db.py` | schema v4 `runtime_config_json` 不可变配置快照。 |
```

4. Add the PR #11–#15 table and link to the evidence matrix rather than duplicating full test details.
5. State that `REFLECTION.md` is pending final student fact confirmation until the student completes `docs/REFLECTION_FACT_CHECK.md`; do not mark AI review as authorship.

- [x] **Step 2：升级项目讲解稿的数据流和模块表**

Update `docs/PROJECT_WALKTHROUGH.md` so the data flow includes:

```text
Settings transaction → runtime_config_json snapshot
→ Context Select/Compress/Isolate
→ MockLLM → Action Parser
→ WorkspacePolicy / ApprovalQueue revision-CAS
→ Tool Dispatcher
→ final Gate + artifact SHA-256
→ Trace / Debug / Audit / artifacts
```

Add module rows for:

- `src/specgate/approvals.py` / `src/specgate/web_approvals.py`.
- `src/specgate/web_runtime.py` / `src/specgate/web_runs.py`.
- `src/specgate/runtime_config.py` / `src/specgate/web_db.py`.
- `src/specgate/credentials.py` / `src/specgate/web_credentials.py`.

Extend the demo script with the exact focused mechanism tests from the evidence matrix. Remove “Lab 11 Hook is a future direction” because the sample and test already exist; keep real LLM and AgentPack as optional non-goals.

- [x] **Step 3：同步 Lab 9–12 对齐说明**

In `docs/AI4SE_Lab_9_12_Alignment.md`:

- Keep the explicit decision not to add Browser MCP or AgentPack.
- Replace early “credential fail-closed only” wording with current OS keyring/AES-256-GCM behavior.
- State that governance remains the main contribution, while Skill, Context strategies, HITL, Web runtime and config snapshots are supporting harness evidence.
- Preserve Hook as an optional installed sample, not part of the runtime tool surface.

- [x] **Step 4：审计部署文档，只修正真实冲突**

Run:

```powershell
Select-String -Path docs/DEPLOYMENT.md -Pattern '.env fallback','HMAC','SPECGATE_WEB_SECRET','run_threads','unbounded'
```

Expected: no current-state stale claim. Historical migration wording mentioning HMAC is allowed if it clearly says `requires_reentry`。若无冲突，不修改 `docs/DEPLOYMENT.md`；若发现当前态冲突，只替换对应段落，不扩大部署范围。

- [x] **Step 5：运行最终评审材料测试**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_final_evidence.FinalEvidenceTests.test_final_review_docs_describe_current_boundaries
```

Expected: PASS。

## Task 5：回填 PLAN、AGENT_LOG 与 SPEC_PROCESS 过程证据

**Files:**

- Modify: `PLAN.md:2083-end`
- Modify: `AGENT_LOG.md:718-end`
- Modify: `SPEC_PROCESS.md:end`
- Modify: `docs/superpowers/plans/2026-07-15-final-evidence-sync.md`

- [x] **Step 1：回填 PLAN 最近阶段远端证据**

Replace “待用户提交/待填写” blocks in the recent stage summaries with:

```markdown
Gate/HITL：功能 commit `e17b8e5`，PR #11，merge `f2b4e88`。
安全凭据：功能 commit `fecc5e3`，PR #12，merge `80be31b`；Pages 依赖热修复 `20c0102`，PR #13，merge `73fbb34`。
Web Runtime：功能 commit `e5fc981`，PR #14，merge `49f66a2`。
Runtime Config：功能 commit `a523137`，PR #15，merge `f45e73a`；合并后 CI #43 与 Pages #26 通过。
```

Keep historical uncompleted checkboxes in the original MVP plan as originally written. Add a final note explaining that completion truth is represented by the later completion summaries and Git evidence, not by rewriting the original plan transcript.

- [x] **Step 2：回填 AGENT_LOG 用户 Git/PR 结果**

For each recent stage, append or replace the final remote line with the corresponding commit/PR/merge mapping from Step 1. Preserve the secure credential Pages failure and PR #13 fix chronology.

Append a new section:

```markdown
## 2026-07-15 最终交付材料与验证证据同步

- 分支：`docs-final-evidence-sync`，基线 `main@f45e73a`。
- Superpowers：`brainstorming`、`writing-plans`、执行阶段使用 `executing-plans`/`test-driven-development`、最终使用 `requesting-code-review` 与 `verification-before-completion`。
- 人工决策：采用权威证据矩阵；将 Actions 截图提交到仓库；`REFLECTION.md` 不由 Agent 改写，只提供事实核对表；Git/PR 由用户执行。
- 课程/PPT 对齐：目标定义、测试基础设施、PR/CI、文档同步和诚实保留失败历史共同构成 Harness 工程证据。
- 范围：只修改文档、证据截图和文档一致性测试，不修改生产代码。
```

Final test counts are appended only after Task 6 fresh verification.

- [x] **Step 3：追加 SPEC_PROCESS 最终审计过程**

Append a section recording four concrete brainstorming decisions:

1. 课程材料审计发现 `.env fallback`、静态 WebUI-only 和等待回填状态不再符合 `main`。
2. 人工选择“权威证据矩阵 + 仓库内截图”，拒绝只贴链接和全面重写历史材料。
3. 人工要求 `REFLECTION.md` 保持学生所有，Agent 只提供事实核对清单。
4. PPT 中“目标定义/测试基础设施/PR 审查/文档同步”和“真实记录失败→修复”的 Harness 观念被落实为本阶段验收规则。

Also record that this stage has no production code behavior and therefore uses a documentation contract test rather than changing runtime code.

- [x] **Step 4：标记本实施计划 Task 1–5 的实际状态**

In this plan, change only completed implementation checkboxes for Task 1–5 to `[x]`. Leave Task 6–7 unchecked until their commands have actually run. Do not mark Git commands complete because the user performs them after handoff.

- [x] **Step 5：运行完整文档契约测试确认 GREEN**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_final_evidence
```

Expected: all tests PASS。

## Task 6：复现核心机制并取得最终验证证据

**Files:**

- Modify: `docs/FINAL_EVIDENCE_MATRIX.md`
- Modify: `AGENT_LOG.md`
- Modify: `PLAN.md`
- Modify: `docs/superpowers/plans/2026-07-15-final-evidence-sync.md`
- Verify: all tests and documentation

- [x] **Step 1：运行课程要求的三类机制演示**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_runner.RunnerTests.test_guardrail_block_is_recorded
python -m unittest tests.test_runner.RunnerTests.test_gate_failure_feedback_changes_next_action
python -m unittest `
  tests.test_runner.RunnerTests.test_review_action_pauses_before_next_llm_call `
  tests.test_runner.RunnerTests.test_resume_from_approved_approval_applies_payload_once_and_continues
```

Expected:

- Guardrail demo: 1 test PASS。
- Gate feedback demo: 1 test PASS。
- HITL pause/resume demo: 2 tests PASS。

These tests use MockLLM/deterministic fixtures and no network.

- [x] **Step 2：运行安全与多策略 benchmark smoke**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest `
  tests.test_cli.CliTests.test_repository_security_benchmark_smoke `
  tests.test_cli.CliTests.test_repository_multi_strategy_benchmark_smoke
```

Expected: 2 tests PASS。它们在临时工作区运行仓库 eval cases，不要求真实 LLM。

- [x] **Step 3：运行完整聚焦证据套件**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest `
  tests.test_final_evidence `
  tests.test_runner `
  tests.test_gate `
  tests.test_approvals `
  tests.test_credentials `
  tests.test_credential_store `
  tests.test_web_credentials `
  tests.test_web_runtime `
  tests.test_runtime_config
```

Expected: PASS；跳过项只允许既有平台权限/链接场景。

- [x] **Step 4：运行全量 MockLLM 回归**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest discover -s tests
```

Expected: `OK (skipped=20)`，测试数高于基线 822，因为新增了文档一致性测试。

- [x] **Step 5：回填新鲜测试结果**

将 Step 1–4 的真实 `Ran ... tests in ...` 和 `OK (skipped=...)` 输出逐字记录到：

- `docs/FINAL_EVIDENCE_MATRIX.md` 的“最终版本快照/完整验证”。
- `AGENT_LOG.md` 本阶段末尾。
- `PLAN.md` 本阶段完成摘要。
- 本实施计划“执行状态”。

Do not copy the old 822 count as the docs-stage final count; use the new full-suite output.

- [x] **Step 6：运行编译、JavaScript 与空白检查**

Run:

```powershell
python -m compileall -q src tests
node --check src/specgate/web_static/app.js
git diff --check
```

Expected:

- compileall and node check: no output, exit code 0。
- `git diff --check`: exit code 0；Windows LF→CRLF warning 不是空白错误。

- [x] **Step 7：确认反思正文和生产代码没有变化**

Run:

```powershell
git diff -- REFLECTION.md
git diff --name-only
git status --short --branch
```

Expected:

- `git diff -- REFLECTION.md` 无输出。
- `git diff --name-only` 不包含 `src/specgate/`、workflow、Dockerfile 或 `.gitlab-ci.yml`。
- 状态只包含本计划列出的 Markdown、两张 PNG 和 `tests/test_final_evidence.py`。

- [x] **Step 8：更新 Task 6 状态并复验文档契约**

Mark Task 6 implementation checkboxes complete, then run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_final_evidence
git diff --check
```

Expected: PASS and exit code 0。

## Task 7：最终主线程审查与用户 Git/PR 交付

**Files:**

- Review: all changed documentation, screenshots and `tests/test_final_evidence.py`
- Modify if review finds issues: only files in this plan

- [x] **Step 1：逐项核对设计验收矩阵**

Confirm:

```text
权威证据矩阵                -> docs/FINAL_EVIDENCE_MATRIX.md
截图与 PR/CI 链             -> docs/evidence/*.png + PR #11–#15
当前凭据事实                -> SPEC.md + README.md + final checklist
Web runtime / config        -> SPEC.md + walkthrough + evidence matrix
课程最终章节                -> README install/run/distribution/tree/security/limits
过程与人工决策              -> SPEC_PROCESS.md + AGENT_LOG.md
反思学生所有                -> REFLECTION.md unchanged + fact check guide
确定性文档防回归            -> tests/test_final_evidence.py
无生产行为修改              -> git diff --name-only
```

- [x] **Step 2：使用 requesting-code-review 做主线程审查**

当前用户未授权派发 subagent 时，主线程按 reviewer 模板检查：

- Critical：虚构 PR/CI/截图、错误 commit、泄漏凭据、修改反思观点。
- Important：最终材料仍含当前 `.env fallback`/HMAC/静态 WebUI-only 描述；关键机制无测试映射；命令不可执行。
- Minor：重复内容、链接格式、中文/英文术语不一致。

Fix all Critical/Important findings before continuing. Any fix to a documented contract must update `tests/test_final_evidence.py` first if the test does not already cover it.

- [x] **Step 3：运行最终 verification-before-completion**

Run fresh:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_final_evidence
python -m unittest discover -s tests
python -m compileall -q src tests
node --check src/specgate/web_static/app.js
git diff --check
git diff -- REFLECTION.md
git status --short --branch
```

Expected: all tests PASS, compile/syntax/diff checks exit 0, reflection diff empty, and only planned files changed.

- [ ] **Step 4：由用户暂存与提交**

After the Agent reports the exact final file list, the user runs:

```powershell
git add SPEC.md PLAN.md SPEC_PROCESS.md AGENT_LOG.md README.md `
  docs/FINAL_EVIDENCE_MATRIX.md `
  docs/FINAL_SUBMISSION_CHECKLIST.md `
  docs/PROJECT_WALKTHROUGH.md `
  docs/AI4SE_Lab_9_12_Alignment.md `
  docs/REFLECTION_FACT_CHECK.md `
  docs/evidence/github-actions-web-runtime-and-credentials.png `
  docs/evidence/github-actions-runtime-config.png `
  docs/superpowers/specs/2026-07-15-final-evidence-sync-design.md `
  docs/superpowers/plans/2026-07-15-final-evidence-sync.md `
  tests/test_final_evidence.py
git diff --cached --check
git commit -m "docs: 同步最终交付材料与验证证据"
git push -u origin docs-final-evidence-sync
```

If `docs/DEPLOYMENT.md` was actually changed in Task 4, include it in `git add`; otherwise do not add it merely because the plan mentioned an audit.

- [x] **Step 5：PR 建议**

Title:

```text
docs: 同步最终交付材料与验证证据
```

PR body must include:

- 权威证据矩阵和两张 Actions 截图。
- PR #11–#15 与 commit/merge 映射。
- `.env`/HMAC/WebUI/runtime config 过期描述修正。
- `REFLECTION.md` 未由 Agent 改写，只新增事实核对表。
- 文档一致性测试、机制演示和最终全量测试的真实数量。
- 明确没有生产代码行为变化，自动验收仍只使用 MockLLM/StubLLM。

## 最终交付边界

本分支完成后，课程最终提交仍有一个必须由学生本人完成的动作：根据 `docs/REFLECTION_FACT_CHECK.md` 修改并确认 `REFLECTION.md`。如果学生修改反思，应使用独立的人工文档提交，并如实保留“AI 只辅助润色/结构整理”的边界。
