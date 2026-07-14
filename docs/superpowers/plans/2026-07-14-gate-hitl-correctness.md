# Gate 与 HITL 正确性加固实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 Checklist、最终 Gate、人工审批暂停、并发决策和恢复执行形成确定性、可审计、可单测的正确闭环。

**Architecture:** 在现有模块边界上增量加固：新增独立 Checklist 规则模块，Gate 绑定输入摘要，审批 JSON 增加 revision/CAS，Runner 用明确 outcome 表示暂停和完成，Web 只做鉴权与状态映射。保留现有 run storage、workspace_fs 和 SQLite run 生命周期。

**Tech Stack:** Python 3.11、标准库 `html.parser`/`hashlib`/`dataclasses`、FastAPI、SQLite、原有 `workspace_fs` 安全文件接口、`unittest`。

**Git 约束:** Agent 不执行 `git add`、`git commit`、`git push` 或 PR 操作；每个任务完成后由用户自行提交。

---

## 完成状态（2026-07-14）

- [x] Task 1：Checklist 规则解析与评估。
- [x] Task 2：Gate 集成、摘要绑定与领域硬编码清理。
- [x] Task 3：Action schema 与 Runner outcome。
- [x] Task 4：审批队列 revision、锁与 CAS。
- [x] Task 5：Runner 真正暂停、最终 Gate 与可恢复 resume。
- [x] Task 6：Web 默认覆盖审批与发布摘要绑定。
- [x] Task 7：Web 审批 API 与前端 revision。
- [x] Task 8：示例扫描、集成验证、中文文档与回归。
- [ ] 用户执行分批提交、push 与 PR，并回填 commit hash。

---

## 文件职责

- 新建 `src/specgate/checklist_rules.py`：规则数据类型、Markdown 指令解析、简单选择器匹配和规则评估。
- 修改 `src/specgate/gate.py`：安全读取、HTML 特征收集、通用基线、结构化规则和输入摘要。
- 修改 `src/specgate/actions.py`：按 action 类型验证参数 schema。
- 修改 `src/specgate/approvals.py`：队列 schema/revision、锁、CAS 和恢复状态。
- 修改 `src/specgate/runner.py`：outcome、真正暂停、最终 Gate 和可恢复 resume。
- 修改 `src/specgate/web_runs.py`：默认覆盖审批、outcome 映射和发布前摘要校验。
- 修改 `src/specgate/web_approvals.py`：数据库行与 JSON 队列的并发决策协调。
- 修改 `src/specgate/web_app.py`：请求 schema 与 `400/409` 映射。
- 修改 `src/specgate/web_static/app.js`：携带 revision，冲突后刷新。
- 新建 `tests/test_checklist_rules.py`，并扩展对应模块测试。

---

### Task 1: Checklist 规则解析与评估

**Files:**
- Create: `src/specgate/checklist_rules.py`
- Create: `tests/test_checklist_rules.py`

- [ ] **Step 1: 写规则解析 RED 测试**

```python
from specgate.checklist_rules import parse_checklist


def test_parses_selector_and_each_directives():
    checklist = """
- [ ] 至少三条新闻
  <!-- specgate: selector "article.news-card" min=3 -->
- [ ] 每条新闻结构完整
  <!-- specgate: each "article.news-card" has "h2" ".summary" "time" -->
"""
    result = parse_checklist(checklist)
    assert [rule.kind for rule in result.rules] == ["selector", "each"]
    assert result.issues == []


def test_unrecognized_checkbox_is_unsupported():
    result = parse_checklist("- [ ] 页面要看起来高级")
    assert result.issues[0].code == "unsupported_check"
```

- [ ] **Step 2: 运行测试并确认 RED**

Run: `python -m unittest tests.test_checklist_rules -v`

Expected: FAIL，原因是 `specgate.checklist_rules` 尚不存在。

- [ ] **Step 3: 实现最小规则模型和解析器**

```python
@dataclass(frozen=True)
class ChecklistRule:
    kind: str
    label: str
    selector: str | None = None
    minimum: int = 1
    required_selectors: tuple[str, ...] = ()
    text: str | None = None


@dataclass(frozen=True)
class ChecklistParseResult:
    rules: tuple[ChecklistRule, ...]
    issues: tuple[ChecklistRuleIssue, ...]


def parse_checklist(markdown: str) -> ChecklistParseResult:
    """解析复选项、紧随其后的 specgate 指令和无歧义兼容句式。"""
```

解析器必须拒绝未知命令、缺少参数、负数 minimum、额外 token 和未支持选择器，并产生 `invalid_checklist_rule`。

- [ ] **Step 4: 写选择器与规则评估 RED 测试**

```python
def test_evaluates_each_rule_against_html_tree():
    document = parse_html_features(
        '<article class="news-card"><h2>A</h2><p class="summary">B</p><time>C</time></article>'
    )
    rule = ChecklistRule(
        kind="each",
        label="新闻结构",
        selector="article.news-card",
        required_selectors=("h2", ".summary", "time"),
    )
    assert evaluate_rule(rule, document).passed is True
```

- [ ] **Step 5: 实现简单 HTML 特征树和规则评估**

```python
def parse_html_features(content: str) -> HtmlDocument:
    """构建只包含标签、id、class、属性、文本和父子关系的轻量树。"""


def evaluate_rule(rule: ChecklistRule, document: HtmlDocument) -> ChecklistRuleResult:
    """支持 selector/text/each/forbid 四类确定性规则。"""
```

选择器只允许标签、`.class`、`#id`、`tag.class`、`[attr]`、`[attr="value"]`。

- [ ] **Step 6: 运行 Task 1 测试**

Run: `python -m unittest tests.test_checklist_rules -v`

Expected: PASS。

- [ ] **Step 7: 用户提交 Task 1**

建议提交信息：`Add structured checklist rules`

---

### Task 2: Gate 集成、摘要绑定与领域硬编码清理

**Files:**
- Modify: `src/specgate/gate.py`
- Modify: `tests/test_gate.py`

- [ ] **Step 1: 写 Gate 行为 RED 测试**

```python
def test_page_without_search_passes_when_checklist_does_not_require_search():
    result = run_html_gate(html_path, checklist_path)
    self.assertTrue(result.passed)


def test_unsupported_checkbox_fails_closed():
    checklist_path.write_text("- [ ] 页面要看起来高级", encoding="utf-8")
    result = run_html_gate(html_path, checklist_path)
    self.assertFalse(result.passed)
    self.assertIn("unsupported_check", {issue.code for issue in result.issues})


def test_gate_records_input_hashes():
    result = run_html_gate(html_path, checklist_path)
    self.assertEqual(result.artifact_sha256, hashlib.sha256(html_path.read_bytes()).hexdigest())
```

- [ ] **Step 2: 运行 Gate 测试并确认 RED**

Run: `python -m unittest tests.test_gate -v`

Expected: FAIL，当前仍强制 search，且 `GateResult` 没有摘要字段。

- [ ] **Step 3: 集成结构化规则并扩展 GateResult**

```python
@dataclass(frozen=True)
class GateResult:
    passed: bool
    checks: list[GateCheck]
    issues: list[GateIssue]
    summary: str
    artifact_sha256: str | None = None
    checklist_sha256: str | None = None
```

一次安全读取后立即计算摘要；删除通用 `search` requirement；把 `parse_checklist()` 和 `evaluate_rule()` 的结果映射为 `GateCheck/GateIssue`。

- [ ] **Step 4: 增加兼容规则和无外部资源测试**

```python
def test_legacy_must_include_rule_remains_supported():
    checklist_path.write_text("- 必须包含 SpecGate", encoding="utf-8")
    self.assertTrue(run_html_gate(html_path, checklist_path).passed)
```

- [ ] **Step 5: 运行 Gate 与规则测试**

Run: `python -m unittest tests.test_checklist_rules tests.test_gate -v`

Expected: PASS。

- [ ] **Step 6: 用户提交 Task 2**

建议提交信息：`Bind Gate results to structured checklist inputs`

---

### Task 3: Action schema 与 Runner outcome

**Files:**
- Modify: `src/specgate/actions.py`
- Modify: `src/specgate/runner.py`
- Modify: `tests/test_runner.py`
- Modify: `tests/test_tools.py`

- [ ] **Step 1: 写非法 payload RED 测试**

```python
def test_write_file_requires_string_content():
    for args in ({"path": "index.html"}, {"path": "index.html", "content": 3}):
        with self.assertRaisesRegex(ActionParseError, "invalid_action_payload"):
            parse_action(json.dumps({"schema_version": "1", "action": "write_file", "args": args}))
```

- [ ] **Step 2: 确认 RED**

Run: `python -m unittest tests.test_runner.ActionProtocolTests tests.test_tools -v`

Expected: FAIL，当前缺少 content 会被接受并写为空字符串。

- [ ] **Step 3: 在 parse_action 中按 action 验证参数**

```python
def _validate_action_args(action: str, args: dict[str, Any]) -> None:
    if action in {"write_file", "replace_file"}:
        if not isinstance(args.get("path"), str) or not isinstance(args.get("content"), str):
            raise ActionParseError("invalid_action_payload: write action requires string path and content")
```

同时删除 `ToolDispatcher._write_file()` 中 `action.args.get("content", "")` 的空字符串默认值。

- [ ] **Step 4: 写 outcome RED 测试**

```python
def test_run_result_exposes_needs_approval_outcome():
    result = runner.run()
    self.assertEqual(result.outcome, "needs_approval")
    self.assertFalse(result.passed)
```

- [ ] **Step 5: 扩展 RunResult**

```python
VALID_RUN_OUTCOMES = {"completed", "needs_approval", "failed"}

@dataclass(frozen=True)
class RunResult:
    passed: bool
    steps: int
    final_gate: GateResult | None
    outcome: str = "failed"
    pending_approval_id: str | None = None
```

`passed` 只在 outcome 为 completed 且 Gate 通过时为 true。

- [ ] **Step 6: 运行协议与 Runner 聚焦测试**

Run: `python -m unittest tests.test_runner tests.test_tools -v`

Expected: PASS。

- [ ] **Step 7: 用户提交 Task 3**

建议提交信息：`Validate actions and expose run outcomes`

---

### Task 4: 审批队列 revision、锁与 CAS

**Files:**
- Modify: `src/specgate/approvals.py`
- Modify: `src/specgate/workspace_fs.py`（仅复用或提取通用锁原语时）
- Modify: `tests/test_approvals.py`

- [ ] **Step 1: 写 schema 兼容与 CAS RED 测试**

```python
def test_legacy_queue_loads_as_revision_zero():
    queue = ApprovalQueue.from_dict({"approvals": []})
    self.assertEqual(queue.schema_version, "1")
    self.assertEqual(queue.revision, 0)


def test_stale_revision_is_rejected_without_mutation():
    store = ApprovalStore(queue_path)
    store.decide("approval-1", "approved", expected_revision=0, decided_at=NOW)
    with self.assertRaises(ApprovalConflictError):
        store.decide("approval-1", "denied", expected_revision=0, decided_at=NOW)
```

- [ ] **Step 2: 确认 RED**

Run: `python -m unittest tests.test_approvals -v`

Expected: FAIL，当前没有 revision、store 和冲突异常。

- [ ] **Step 3: 实现版本化队列与存储接口**

```python
class ApprovalConflictError(ValueError):
    code = "approval_conflict"


@dataclass
class ApprovalQueue:
    approvals: list[PendingApproval] = field(default_factory=list)
    schema_version: str = "2"
    revision: int = 0


class ApprovalStore:
    def __init__(self, path: Path):
        self.path = path

    def read(self) -> ApprovalQueue:
        return ApprovalQueue.read(self.path)

    def _mutate(self, expected_revision: int, mutation) -> ApprovalQueue:
        with approval_queue_lock(self.path):
            current = ApprovalQueue.read(self.path)
            if current.revision != expected_revision:
                raise ApprovalConflictError("approval queue revision changed")
            changed = mutation(current)
            updated = replace(
                changed,
                schema_version="2",
                revision=current.revision + 1,
            )
            updated.write(self.path)
            return updated

    def decide(
        self,
        approval_id: str,
        status: str,
        expected_revision: int,
        decided_at: str,
        reason: str | None = None,
    ) -> ApprovalQueue:
        def mutation(queue: ApprovalQueue) -> ApprovalQueue:
            if status == "approved":
                return queue.approve(approval_id, decided_at)
            if status == "denied":
                return queue.deny(approval_id, reason or "", decided_at)
            raise ValueError("invalid approval decision")

        return self._mutate(expected_revision, mutation)
```

`append()` 和 `transition()` 使用同一个 `_mutate()` 模板，分别调用队列的追加与合法状态迁移方法。每个修改方法必须在同一个跨进程锁内完成读取、revision 比较、状态验证和安全写入。

- [ ] **Step 4: 写跨进程并发 RED 测试**

启动两个进程使用相同 expected revision 分别 approve 和 deny，断言一个成功、一个 `approval_conflict`，最终 revision 只增加一次。

- [ ] **Step 5: 实现锁内 CAS 并运行测试**

Run: `python -m unittest tests.test_approvals -v`

Expected: PASS，Windows 与 POSIX 均通过；权限受限的真实链接测试可明确 skip。

- [ ] **Step 6: 用户提交 Task 4**

建议提交信息：`Make approval decisions versioned and atomic`

---

### Task 5: Runner 真正暂停、最终 Gate 与可恢复 resume

**Files:**
- Modify: `src/specgate/runner.py`
- Modify: `src/specgate/approvals.py`
- Modify: `tests/test_runner.py`

- [ ] **Step 1: 写真正暂停 RED 测试**

```python
def test_review_action_pauses_before_next_llm_call():
    llm = MockLLM([review_action, forbidden_followup])
    result = runner.run()
    self.assertEqual(result.outcome, "needs_approval")
    self.assertEqual(result.metrics.llm_calls, 1)
    self.assertEqual(result.metrics.tool_calls, 0)
    self.assertEqual(len(llm.contexts), 1)
```

- [ ] **Step 2: 实现审批后立即返回**

审批追加成功后直接构造 `RunResult(outcome="needs_approval", pending_approval_id=approval.id)`，不得 `continue` 循环。

- [ ] **Step 3: 写 finish 最终重跑 RED 测试**

先让中间 Gate 通过，再修改文件并请求 finish，断言 Runner 重新 Gate、反馈失败并调用下一轮 LLM，而不是成功返回。

- [ ] **Step 4: 实现 finish 语义**

```python
if action.action == "finish":
    latest_gate, metrics = self._run_gate_with_feedback(step, metrics, runtime_feedback)
    if not latest_gate.passed:
        continue
    return self._finish_result(
        step,
        latest_gate,
        metrics,
        permission_decisions,
        outcome="completed",
    )
```

最大步数结束时 outcome 固定为 failed。

- [ ] **Step 5: 写 applying 恢复三分支 RED 测试**

覆盖目标为审批前摘要、预期内容摘要、第三方摘要三种情况，期望分别为重试、直接 applied、`failed`；第三种情况必须返回稳定错误码 `approval_target_changed`。

- [ ] **Step 6: 实现 claim 与恢复**

approved resume 先 CAS 为 applying。成功工具结果转 applied；失败转 failed。denied 不执行工具，写拒绝反馈后转 rejected 并继续运行循环。

- [ ] **Step 7: 运行 Runner 与审批测试**

Run: `python -m unittest tests.test_approvals tests.test_runner -v`

Expected: PASS。

- [ ] **Step 8: 用户提交 Task 5**

建议提交信息：`Correct HITL pause and resume semantics`

---

### Task 6: Web 默认覆盖审批与发布摘要绑定

**Files:**
- Modify: `src/specgate/approvals.py`
- Modify: `src/specgate/web_runs.py`
- Modify: `tests/test_web_runs.py`

- [ ] **Step 1: 写实际目标状态风险 RED 测试**

```python
def test_existing_target_requires_review_even_for_write_file():
    (root / "index.html").write_text("old", encoding="utf-8")
    risk = classify_action_risk(write_action, policy, GovernanceConfig(profile="review", review_existing_writes=True))
    self.assertEqual(risk.level, "review")
```

同时断言不存在的 `index.html` 可自动写入。

- [ ] **Step 2: 实现 review_existing_writes**

```python
@dataclass
class GovernanceConfig:
    profile: str = "strict"
    review_existing_writes: bool = False
```

Web mock runner 使用 `profile="review", review_existing_writes=True`。

- [ ] **Step 3: 写发布摘要失效 RED 测试**

Runner 最终 Gate 后替换 `index.html`，断言 Web run 为 failed、错误码 `stale_gate_result`，且不调用 `promote_run_workspace`。

- [ ] **Step 4: 实现发布前摘要验证**

发布 HTML/ZIP 和 promotion 前，使用 `workspace_file_state` 比较 `RunResult.final_gate.artifact_sha256`；不一致时禁止发布。

- [ ] **Step 5: 运行 Web run 聚焦测试**

Run: `python -m unittest tests.test_web_runs tests.test_runner -v`

Expected: PASS。

- [ ] **Step 6: 用户提交 Task 6**

建议提交信息：`Review overwrites and bind published Gate artifacts`

---

### Task 7: Web 审批 API 与前端 revision

**Files:**
- Modify: `src/specgate/web_approvals.py`
- Modify: `src/specgate/web_app.py`
- Modify: `src/specgate/web_static/app.js`
- Modify: `tests/test_web_approvals.py`
- Modify: `tests/test_web_app.py`
- Modify: `tests/test_web_static.py`

- [ ] **Step 1: 写 API RED 测试**

```python
def test_approve_requires_expected_revision(client):
    response = client.post(f"/api/approvals/{approval_id}/approve", json={})
    assert response.status_code == 400


def test_stale_approval_revision_returns_409(client):
    response = client.post(
        f"/api/approvals/{approval_id}/approve",
        json={"expected_revision": 0},
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "approval_conflict"
```

- [ ] **Step 2: 增加请求模型和错误映射**

```python
class ApprovalDecisionRequest(BaseModel):
    expected_revision: int


class DenyRequest(ApprovalDecisionRequest):
    reason: str
```

`ApprovalConflictError` 映射为 HTTP 409；缺少或非法 revision 映射为 400。

- [ ] **Step 3: 协调 DB 行与 JSON 队列更新**

`web_approvals.py` 先通过 ApprovalStore 完成 CAS 决策，再以条件 SQL 更新对应 Web approval 行；若数据库更新失败，返回一致性错误并保留可审计诊断，不静默覆盖 JSON。

- [ ] **Step 4: 前端携带 revision 并处理冲突**

```javascript
await apiJson(`/api/approvals/${approval.id}/approve`, {
  method: "POST",
  body: { expected_revision: approval.queue_revision },
});
```

HTTP 409 时重新 `loadApprovals()`、重新渲染并显示“审批状态已变化，请重新确认”。

- [ ] **Step 5: 运行 Web 审批与静态测试**

Run: `python -m unittest tests.test_web_approvals tests.test_web_app tests.test_web_static -v`

Expected: PASS。

- [ ] **Step 6: 用户提交 Task 7**

建议提交信息：`Expose approval revisions through Web API`

---

### Task 8: 示例迁移、集成验证与回归

**Files:**
- Modify: `examples/eval_cases/*/CHECKLIST.md`（仅无法确定性解析的现有案例）
- Modify: `README.md`
- Modify: `tests/test_web_runs.py`
- Modify: `tests/test_eval_runner.py`（若示例断言受影响）

- [ ] **Step 1: 写完整 Web 流程集成测试**

场景一：已有 `index.html` -> run 返回 needs_approval -> approve(revision) -> resume -> applied -> 最终 Gate -> completed。

场景二：已有 `index.html` -> deny(revision, reason) -> resume -> 原动作未执行 -> Agent 获得拒绝反馈并提出安全替代动作。

- [ ] **Step 2: 为现有示例补充明确 SpecGate 指令**

只迁移会被 `unsupported_check` 拒绝的复选项；保持自然语言标题，并在其下增加机器指令。

- [ ] **Step 3: 更新 README**

记录：

- Checklist 指令语法和选择器范围。
- 未识别条目会阻止 trusted。
- 覆盖已有文件会暂停审批。
- approve/deny/revision 冲突与恢复流程。

- [ ] **Step 4: 运行完整测试**

Run: `$env:PYTHONPATH='src'; python -m unittest discover -s tests`

Expected: 0 failures，0 errors；仅允许已有平台权限类 skip。

- [ ] **Step 5: 运行格式与语法检查**

Run: `python -m compileall -q src tests`

Expected: exit 0。

- [ ] **Step 6: 用户执行最终 Git 与 PR 操作**

建议提交信息：`Complete Gate and HITL correctness hardening`

用户负责检查状态、提交、push 和 PR；Agent 仅提供中文 PR 内容。

---

## 最终评审清单

- [x] 每个新增行为都有先失败后通过的测试证据。
- [x] Checklist 未识别条目不能产生 trusted。
- [x] 创建审批后没有第二次 LLM 调用。
- [x] 两个并发决策最多一个成功。
- [x] applying 中断不会重复覆盖第三方内容。
- [x] finish 无条件使用最终 Gate。
- [x] 发布内容原始字节摘要与 Gate 摘要一致。
- [x] Web 首次创建不中断，覆盖已有文件会暂停。
- [x] 本地全量测试、语法检查与差异检查通过。
- [ ] GitHub Ubuntu CI 通过（等待用户提交并 push 后运行）。
- [x] 设计、计划、README 和行为一致。
