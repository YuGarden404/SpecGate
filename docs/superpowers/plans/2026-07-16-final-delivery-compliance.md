# 最终交付合规实施计划

> **供执行 Agent 使用：** 必须使用 `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans`，逐项实施本计划。所有步骤使用复选框（`- [ ]`）跟踪状态。

**目标：** 让 SpecGate 的最终交付材料与 PR #20 后的真实仓库状态、课程硬性条款和可复核证据保持一致。

**实现结构：** 以 `tests/test_final_evidence.py` 作为确定性材料契约入口，每个合规主题先增加失败断言，再最小化修改对应 Markdown 材料。远端 PR、CI 截图和不同类型 Agent 冷启动结果作为人工门禁，只有真实发生后才写入“已完成”；生产代码保持不变。

**技术栈：** Python 3.11+、`unittest`、`tomllib`、Markdown、Git/GitHub、全新 Gemini Web 会话。

---

## 文件职责

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

## 执行环境前提

- 任务 1 至任务 7 必须在本地独立 worktree 中执行，并具备文件系统、shell、Python、Node.js 与 Git 能力。
- Gemini Web 只用于隔离上下文后的计划审查和补丁草案验证，不能被视为已修改文件、已运行测试或已完成提交。
- 为保持冷启动边界，不再向 Gemini Web 上传计划指定范围之外的仓库文件；它所缺少的当前文件上下文本身就是本次验证结果的一部分。
- 实际文件修改、TDD 红绿验证、提交和审查由本地 Subagent 在实现 worktree 中完成。

## 执行前门禁：全新 Gemini Web 冷启动

此门禁必须在任务 1 以外的材料实现开始前完成。它是最终合规阶段的补充验证，不追溯性替代 2026-07-08 的早期计划审查。

- [x] **步骤 1：调用 worktree Skill**

调用 `superpowers:using-git-worktrees`，从包含本计划的 commit 创建独立冷启动 worktree。冷启动 worktree 不导入当前对话、memory 或未提交改动。

- [x] **步骤 2：启动完全独立的 Gemini Web 会话**

Claude Code 因无官方账号且无法连接 Anthropic 服务而退出；OpenCode 官方 Windows x64 二进制在本机无法加载；Gemini CLI 因用户账户没有 Gemini Code Assist 权限而认证失败。用户确认改用全新 Gemini Web 会话，并且只上传以下两个文件：

```text
SPEC.md
docs/superpowers/plans/2026-07-16-final-delivery-compliance.md
```

上传后发送以下指令，不补充口头解释，也不上传其他仓库文件：

```text
这是一次 SpecGate 最终合规阶段的冷启动验证。

你的上下文只允许来自仓库根目录 SPEC.md 与
docs/superpowers/plans/2026-07-16-final-delivery-compliance.md。
不要读取 AGENT_LOG.md、SPEC_PROCESS.md、聊天记录或任何 agent memory。

请尝试执行本计划的任务 2 和任务 3。你当前没有本地 shell 或 worktree，
只能依据已上传的 SPEC 与实施计划输出任务理解和可应用的补丁草案。
不要假装已经修改文件或运行测试；如果缺少任务所需的当前文件内容，必须暂停并明确列出缺失内容，
不能向我索取项目历史口头说明，也不得猜测测试已经通过。

遇到任何不确定之处必须立即暂停并提出具体问题，不得猜测继续。
请在结束时报告：读取了哪些文件、在哪一步暂停、提出的问题、能够给出的补丁草案、
未执行测试的明确说明、你认为 SPEC/PLAN 仍缺少的信息，以及总耗时。
不要执行 git push、创建 PR 或修改远端状态。
```

- [x] **步骤 3：保留未经改写的结果**

用户把 Gemini Web 的问题、最终报告、补丁草案、阻塞说明和耗时原样提供给主线程。主线程不得先行润色或把失败改写为成功。Claude Code、OpenCode 和 Gemini CLI 的环境阻塞也作为 Agent 选择过程如实记录。

- [x] **步骤 4：判断计划是否需要修订**

Gemini Web 在任务 2 的步骤 1 和步骤 3、任务 3 的步骤 1 和步骤 4 暂停，原因是缺少七个目标文件的当前完整内容。它明确列出缺失文件，给出基于计划的骨架补丁，并声明没有修改文件或运行测试；总耗时约 3 分钟。该结果表明计划原先没有明确区分 Web-only 审查环境与本地实现环境，因此本次修订增加“执行环境前提”，保留不再上传额外文件的隔离边界，并将实际实现交给本地 Subagent。

### 任务 1：记录补充冷启动证据

**涉及文件：**
- 新建：`docs/superpowers/audits/2026-07-16-final-compliance-cold-start.md`
- 修改：`tests/test_final_evidence.py`
- 修改：`SPEC_PROCESS.md`
- 修改：`SPEC.md`
- 修改：`PLAN.md`
- 修改：`AGENT_LOG.md`
- 修改：`docs/superpowers/plans/2026-07-16-final-delivery-compliance.md`

- [x] **步骤 1：编写失败的证据契约测试**

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

- [x] **步骤 2：运行测试并确认红灯**

运行：

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_final_evidence.FinalEvidenceTests.test_supplemental_cold_start_records_required_evidence
```

预期：测试失败，因为 `docs/superpowers/audits/2026-07-16-final-compliance-cold-start.md` 尚不存在。

- [x] **步骤 3：根据 Gemini Web 的实际结果编写审计记录**

创建审计文件并使用测试要求的八个标题。每节只写 Gemini Web 原始结果能够支持的事实；没有暂停问题时明确写“本次没有暂停提问”，没有成功产出时记录失败和阻塞点。必须明确 Web 版没有直接修改 worktree 或运行测试，禁止使用推测性补全。

在 `SPEC_PROCESS.md` 的冷启动章节后追加“最终合规阶段补充冷启动”，明确：

```markdown
本记录是最终合规阶段的补充冷启动验证，不替代 2026-07-08 的早期
SPEC/PLAN 可执行性审查，也不追溯性声称 MVP 实现前完成过完整实现试跑。
```

在 `PLAN.md` 与 `AGENT_LOG.md` 追加 agent 类型、会话隔离、任务、问题、产出、测试、修订和人工参与事实。

- [x] **步骤 4：运行聚焦测试并确认绿灯**

运行：

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_final_evidence
```

预期：测试通过。

- [x] **步骤 5：提交冷启动证据**

```powershell
git add -- tests/test_final_evidence.py SPEC_PROCESS.md SPEC.md PLAN.md AGENT_LOG.md docs/superpowers/audits/2026-07-16-final-compliance-cold-start.md docs/superpowers/plans/2026-07-16-final-delivery-compliance.md
git commit -m "docs: record supplemental compliance cold start"
```

### 任务 2：同步当前发布版本与证据链

**涉及文件：**
- 修改：`tests/test_final_evidence.py`
- 修改：`docs/FINAL_EVIDENCE_MATRIX.md`
- 修改：`docs/FINAL_SUBMISSION_CHECKLIST.md`
- 修改：`docs/REFLECTION_FACT_CHECK.md`
- 修改：`PLAN.md`
- 修改：`AGENT_LOG.md`

- [x] **步骤 1：扩展发布链测试并增加当前快照测试**

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

- [x] **步骤 2：运行两项测试并确认红灯**

运行：

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_final_evidence.FinalEvidenceTests.test_release_chain_and_screenshot_links_are_recorded tests.test_final_evidence.FinalEvidenceTests.test_final_snapshot_uses_pr20_baseline_without_stale_branch_claims
```

预期：测试失败，因为缺少 PR #18 至 #20 以及 PR #20 基线。

- [x] **步骤 3：更新权威证据文档**

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

- [x] **步骤 4：运行聚焦证据测试并确认绿灯**

运行：

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_final_evidence
```

预期：测试通过。

- [x] **步骤 5：提交证据链同步结果**

```powershell
git add -- tests/test_final_evidence.py docs/FINAL_EVIDENCE_MATRIX.md docs/FINAL_SUBMISSION_CHECKLIST.md docs/REFLECTION_FACT_CHECK.md PLAN.md AGENT_LOG.md
git commit -m "docs: synchronize final release evidence"
```

### 任务 3：增加完整的直接依赖许可证表

**涉及文件：**
- 修改：`tests/test_final_evidence.py`
- 修改：`README.md`

- [ ] **步骤 1：增加依赖解析导入和失败测试**

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

- [ ] **步骤 2：运行许可证测试并确认红灯**

运行：

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_final_evidence.FinalEvidenceTests.test_readme_lists_every_direct_dependency_license
```

预期：测试失败，因为 README 尚无许可证章节。

- [ ] **步骤 3：核对已安装包的元数据**

运行：

```powershell
python -c "from importlib.metadata import metadata; names=['cryptography','fastapi','httpx','keyring','python-multipart','uvicorn']; [(lambda m: print(n, m.get('License-Expression') or m.get('License'), m.get_all('Project-URL')))(metadata(n)) for n in names]"
```

预期许可证：

```text
cryptography: Apache-2.0 OR BSD-3-Clause
fastapi: MIT
httpx: BSD-3-Clause
keyring: MIT
python-multipart: Apache-2.0
uvicorn: BSD-3-Clause
```

- [ ] **步骤 4：在 README 增加许可证表**

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

补充一句：该表只覆盖直接运行时依赖，完整传递依赖以安装环境中的包元数据为准。

- [ ] **步骤 5：运行聚焦测试并确认绿灯**

运行：

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_final_evidence.FinalEvidenceTests.test_readme_lists_every_direct_dependency_license
```

预期：测试通过。

- [ ] **步骤 6：提交许可证文档**

```powershell
git add -- tests/test_final_evidence.py README.md
git commit -m "docs: document third-party dependency licenses"
```

### 任务 4：如实记录 Open Design 流程偏离

**涉及文件：**
- 修改：`tests/test_final_evidence.py`
- 修改：`SPEC.md`
- 修改：`README.md`
- 修改：`AGENT_LOG.md`

- [ ] **步骤 1：编写失败的 Open Design 契约测试**

```python
def test_spec_records_the_actual_open_design_decision(self):
    spec = read_text("SPEC.md")
    self.assertIn("Open Design", spec)
    self.assertIn("未采用", spec)
    self.assertIn("不追溯性声称", spec)
```

- [ ] **步骤 2：运行测试并确认红灯**

运行：

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_final_evidence.FinalEvidenceTests.test_spec_records_the_actual_open_design_decision
```

预期：测试失败，因为 SPEC 尚未说明 Open Design。

- [ ] **步骤 3：增加明确的偏离决策**

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

- [ ] **步骤 4：运行聚焦测试并确认绿灯**

运行：

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_final_evidence
```

预期：测试通过。

- [ ] **步骤 5：提交 Open Design 决策记录**

```powershell
git add -- tests/test_final_evidence.py SPEC.md README.md AGENT_LOG.md
git commit -m "docs: record Open Design process deviation"
```

### 任务 5：区分静态 Pages、交互式 WebUI 与分发状态

**涉及文件：**
- 修改：`tests/test_final_evidence.py`
- 修改：`docs/FINAL_EVIDENCE_MATRIX.md`
- 修改：`docs/FINAL_SUBMISSION_CHECKLIST.md`
- 修改：`README.md`
- 修改：`SPEC.md`

- [ ] **步骤 1：编写失败的边界测试**

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

- [ ] **步骤 2：运行测试并确认红灯**

运行：

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_final_evidence.FinalEvidenceTests.test_submission_docs_do_not_claim_public_backend_or_registry
```

预期：测试失败，因为当前清单把静态 Pages URL 标记为已完成的公开 WebUI，并把 Dockerfile 标记为已完成的分发。

- [ ] **步骤 3：修正状态模型**

在证据矩阵和提交清单中拆分：

```markdown
| 公开静态评审入口 | 已完成 | GitHub Pages 首页、demo、报告 |
| 本地交互式 WebUI | 已完成 | Docker/本地启动与确定性测试 |
| 公网交互式 Web 后端 | 待完成 | 后续独立部署阶段 |
| Docker 本地与 CI 构建 | 已完成 | Dockerfile 与 CI smoke |
| 公开容器 registry | 待完成 | 后续 GHCR 分发阶段 |
```

README 和 SPEC 保留已有静态/交互式边界，并明确“发布镜像不等于部署服务”。

- [ ] **步骤 4：运行聚焦测试并确认绿灯**

运行：

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_final_evidence
```

预期：测试通过。

- [ ] **步骤 5：提交修正后的交付状态**

```powershell
git add -- tests/test_final_evidence.py docs/FINAL_EVIDENCE_MATRIX.md docs/FINAL_SUBMISSION_CHECKLIST.md README.md SPEC.md
git commit -m "docs: distinguish static review and public deployment"
```

### 任务 6：完成远端 PR 与 CI 证据门禁

**涉及文件：**
- 新建：`docs/evidence/github-actions-pr20-final.png`
- 修改：`tests/test_final_evidence.py`
- 修改：`docs/FINAL_EVIDENCE_MATRIX.md`
- 修改：`docs/FINAL_SUBMISSION_CHECKLIST.md`
- 修改：`AGENT_LOG.md`

- [ ] **步骤 1：人工核对并更新 PR 归属**

用户打开 PR #18、#19、#20，确认每个 PR 描述包含以下真实归属：

```markdown
## 执行归属

- 主开发 Agent：OpenAI Codex，按 Superpowers 流程执行。
- Subagent：本阶段采用 Inline Execution，未派发 subagent；原因记录在 AGENT_LOG.md。
- 人工参与：用户确认范围与设计，执行真实 LLM 手工验证、Git 暂存、提交、push 和 PR 操作。
- 自动测试：使用 Mock/Fake/Stub，不访问真实 Provider；手工真实 LLM 结果单独记录。
```

如某个 PR 的真实情况不同，按对应 `AGENT_LOG.md` 修正文案，不能机械复制错误事实。

- [ ] **步骤 2：截取当前 Actions 证据**

用户在 GitHub Actions 页面确认 PR #20 合并后的 `unit-test`、`docker-build` 和 Pages 均为成功状态，并保存完整截图到：

```text
docs/evidence/github-actions-pr20-final.png
```

截图必须显示仓库、工作流、commit/PR 和成功状态，不包含凭据或账户敏感信息。

- [ ] **步骤 3：把新截图加入证据测试**

在 `SCREENSHOTS` 中增加：

```python
ROOT / "docs" / "evidence" / "github-actions-pr20-final.png",
```

- [ ] **步骤 4：运行截图与证据测试**

运行：

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_final_evidence.FinalEvidenceTests.test_required_evidence_artifacts_exist_and_pngs_are_readable tests.test_final_evidence.FinalEvidenceTests.test_release_chain_and_screenshot_links_are_recorded
```

预期：在 PNG 不存在且矩阵未引用它时测试失败；加入真实截图和链接后测试通过。

- [ ] **步骤 5：只记录已经完成的远端事实**

在证据矩阵、提交清单和 `AGENT_LOG.md` 中记录已核对的 PR 归属与截图。若用户没有完成某项远端更新，该项保持“待完成”，本任务不得宣称绿灯。

- [ ] **步骤 6：提交远端证据**

```powershell
git add -- tests/test_final_evidence.py docs/evidence/github-actions-pr20-final.png docs/FINAL_EVIDENCE_MATRIX.md docs/FINAL_SUBMISSION_CHECKLIST.md AGENT_LOG.md
git commit -m "docs: add current PR and CI attribution evidence"
```

### 任务 7：运行最终验证并冻结证据快照

**涉及文件：**
- 修改：`docs/FINAL_EVIDENCE_MATRIX.md`
- 修改：`docs/FINAL_SUBMISSION_CHECKLIST.md`
- 修改：`PLAN.md`
- 修改：`AGENT_LOG.md`

- [ ] **步骤 1：运行文档契约测试**

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_final_evidence tests.test_workflows
```

预期：测试通过且没有错误。

- [ ] **步骤 2：运行六项确定性机制演示**

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_runner.RunnerTests.test_guardrail_block_is_recorded tests.test_runner.RunnerTests.test_gate_failure_feedback_changes_next_action tests.test_runner.RunnerTests.test_review_action_pauses_before_next_llm_call tests.test_runner.RunnerTests.test_resume_from_approved_approval_applies_payload_once_and_continues tests.test_cli.CliTests.test_repository_security_benchmark_smoke tests.test_cli.CliTests.test_repository_multi_strategy_benchmark_smoke
```

预期：输出 `Ran 6 tests` 和 `OK`。

- [ ] **步骤 3：运行完整测试套件**

```powershell
$env:PYTHONPATH="src"
python -m unittest discover -s tests
```

预期：退出码为 0，并输出 `OK`。记录本次运行的准确测试数量、耗时和跳过数量。

- [ ] **步骤 4：运行语法与空白检查**

```powershell
python -m compileall -q src tests
node --check src/specgate/web_static/app.js
git diff --check
```

预期：所有命令退出码均为 0，且没有错误输出。

- [ ] **步骤 5：运行凭据与历史检查**

```powershell
git check-ignore -v .env
git log --all --oneline -- .env
git grep -n -I -E "(sk-[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{30,})" -- . ":(exclude)tests" ":(exclude)docs/superpowers/plans"
```

预期：`.env` 已被忽略，`.env` 提交历史为空，凭据扫描没有真实密钥命中。任何测试 fixture 或文档命中都必须人工检查并记录，不能自动忽略。

- [ ] **步骤 6：重新检查公开 Pages**

Open and verify:

```text
https://yugarden404.github.io/SpecGate/
https://yugarden404.github.io/SpecGate/demo/
https://yugarden404.github.io/SpecGate/report/
```

预期：三个页面均可加载，并显示预期标题和主标题。

- [ ] **步骤 7：冻结准确的最终结果**

使用步骤 3 的准确输出更新“当前最终结果”字段。只有明确标注为 2026-07-16 审查起点时才保留 908；同时把所有任务的提交哈希补充到 `PLAN.md`，并把按时间排序的结果补充到 `AGENT_LOG.md`。

- [ ] **步骤 8：更新数字后重新运行文档契约测试**

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_final_evidence tests.test_workflows
git diff --check
```

预期：测试通过，且没有空白错误。

- [ ] **步骤 9：提交经过验证的最终快照**

```powershell
git add -- docs/FINAL_EVIDENCE_MATRIX.md docs/FINAL_SUBMISSION_CHECKLIST.md PLAN.md AGENT_LOG.md
git commit -m "docs: freeze verified final compliance snapshot"
```

- [ ] **步骤 10：执行两阶段审查**

先运行规格合规审查，逐项对照设计文档第 2、3、5 至 13 节；再运行文档质量审查，检查事实冲突、模糊状态、失效链接、格式和敏感信息。严重（Critical）或重要（Important）问题必须修复并重新执行相关测试。

- [ ] **步骤 11：确认分支工作区干净**

```powershell
git status --short
git log --oneline --decorate -10
```

预期：工作区干净；最近提交与任务 1 至任务 7以及设计、计划文档对应。
