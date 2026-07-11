# HITL Review Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 SpecGate 增加确定性的 HITL 审批门，让高风险但非硬性违规的 action 进入 pending approval 队列，而不是自动执行。

**Architecture:** 新增纯模块 `specgate.approvals` 负责风险分类和审批队列模型；扩展 config/metrics/runner/report/eval/cli，让审批决策在执行前生效，并进入 trace、report、eval 结果。第一版只支持创建和查看 pending approvals，不做 approve/deny/resume。

**Tech Stack:** Python 标准库、`dataclasses`、`fnmatch`、现有 `unittest`、现有 MockLLM、现有 trace/report/eval 架构。

---

## File Structure

- Create `src/specgate/approvals.py`: HITL 风险分类、pending approval 数据模型、JSON 队列读写。
- Create `tests/test_approvals.py`: 纯单元测试，覆盖 safe/review/blocked 分类和队列序列化。
- Modify `src/specgate/config.py`: 增加 `GovernanceConfig`、`WorkspaceConfig`、`load_workspace_config`，保持 `load_policy` 向后兼容。
- Modify `tests/test_config.py`: 覆盖 governance 配置默认值、BOM TOML、无效 profile fail closed。
- Modify `src/specgate/metrics.py`: 增加 `approval_requests` 和 `pending_approvals` 指标，并把 pending approval 纳入 trust warning。
- Modify `tests/test_metrics.py`: 覆盖 pending approvals 对 trust 的影响。
- Modify `src/specgate/runner.py`: 在 dispatch 前接入风险分类；review profile 下写 pending approval 并跳过 mutation。
- Modify `tests/test_runner.py`: 覆盖 review 队列、不修改文件、strict 阻断、review feedback。
- Modify `src/specgate/report.py`: 增加 `Pending Approvals` 报告区块并转义动态字段。
- Modify `tests/test_report.py`: 覆盖报告展示和 HTML escaping。
- Modify `src/specgate/eval_runner.py`: 把 approval counts 放入 `EvalCaseResult` 和 `results.json`。
- Modify `tests/test_eval_runner.py`: 覆盖 eval 审批统计和保存 workspace。
- Modify `src/specgate/cli.py`: 增加 `approvals list <workspace>`，并让 run/eval 使用 workspace config 中的 governance 配置。
- Modify `tests/test_cli.py`: 覆盖 approvals list、malformed queue、profile 传递。
- Modify `README.md`: 记录 HITL Review Gate 的 mock-first 用法。

## Task 1: 审批模型和风险分类

**Files:**
- Create: `src/specgate/approvals.py`
- Test: `tests/test_approvals.py`

- [ ] **Step 1: 写失败测试**

Create `tests/test_approvals.py`:

```python
import tempfile
import unittest
from pathlib import Path

from specgate.actions import Action
from specgate.approvals import (
    ApprovalQueue,
    GovernanceConfig,
    PendingApproval,
    classify_action_risk,
)
from specgate.policy import WorkspacePolicy


class ApprovalTests(unittest.TestCase):
    def test_allowed_write_to_normal_artifact_is_safe(self):
        policy = WorkspacePolicy(Path("."), {"write_file"}, set(), {"index.html"})
        config = GovernanceConfig(profile="review")
        action = Action("1", "write_file", {"path": "index.html", "content": "ok"})

        risk = classify_action_risk(action, policy, config)

        self.assertEqual(risk.level, "safe")
        self.assertEqual(risk.reason, "safe action")

    def test_protected_replace_requires_review(self):
        policy = WorkspacePolicy(Path("."), {"replace_file"}, set(), {"README.md"})
        config = GovernanceConfig(profile="review", review_actions={"replace_file"}, review_paths={"README.md"})
        action = Action("1", "replace_file", {"path": "README.md", "content": "new"})

        risk = classify_action_risk(action, policy, config)

        self.assertEqual(risk.level, "review")
        self.assertIn("requires human review", risk.reason)

    def test_env_write_is_blocked_even_if_policy_mentions_it(self):
        policy = WorkspacePolicy(Path("."), {"write_file"}, set(), {".env"})
        config = GovernanceConfig(profile="review", blocked_paths={".env"})
        action = Action("1", "write_file", {"path": ".env", "content": "SECRET=1"})

        risk = classify_action_risk(action, policy, config)

        self.assertEqual(risk.level, "blocked")
        self.assertIn("blocked path", risk.reason)

    def test_path_escape_is_blocked(self):
        policy = WorkspacePolicy(Path("."), {"write_file"}, set(), {"index.html"})
        config = GovernanceConfig(profile="review")
        action = Action("1", "write_file", {"path": "../outside.txt", "content": "x"})

        risk = classify_action_risk(action, policy, config)

        self.assertEqual(risk.level, "blocked")
        self.assertIn("path escapes workspace", risk.reason)

    def test_queue_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            queue_path = Path(tmp) / "pending_approvals.json"
            approval = PendingApproval(
                id="approval-step-2",
                step=2,
                action="replace_file",
                path="README.md",
                risk_level="review",
                reason="replace_file on protected path requires human review",
                profile="review",
                arguments_preview={"path": "README.md"},
            )

            queue = ApprovalQueue([approval])
            queue.write(queue_path)
            loaded = ApprovalQueue.read(queue_path)

            self.assertEqual(len(loaded.approvals), 1)
            self.assertEqual(loaded.approvals[0].id, "approval-step-2")
            self.assertEqual(loaded.approvals[0].status, "pending")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_approvals -v
```

Expected: FAIL，原因是 `specgate.approvals` 不存在。

- [ ] **Step 3: 实现审批模块**

Create `src/specgate/approvals.py`:

```python
from __future__ import annotations

import fnmatch
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from specgate.actions import Action
from specgate.policy import WorkspacePolicy, check_action
from specgate.security import redact_text


VALID_GOVERNANCE_PROFILES = ("strict", "demo", "review")


@dataclass(frozen=True)
class GovernanceConfig:
    profile: str = "strict"
    review_actions: set[str] = field(default_factory=set)
    review_paths: set[str] = field(default_factory=set)
    blocked_paths: set[str] = field(default_factory=lambda: {".env"})

    def __post_init__(self) -> None:
        if self.profile not in VALID_GOVERNANCE_PROFILES:
            raise ValueError(f"unknown governance profile: {self.profile}")


@dataclass(frozen=True)
class ActionRisk:
    level: str
    reason: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class PendingApproval:
    id: str
    step: int
    action: str
    path: str | None
    risk_level: str
    reason: str
    profile: str
    arguments_preview: dict[str, Any] = field(default_factory=dict)
    status: str = "pending"
    created_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ApprovalQueue:
    approvals: list[PendingApproval] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"approvals": [approval.to_dict() for approval in self.approvals]}

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def read(cls, path: Path) -> "ApprovalQueue":
        if not path.exists():
            return cls()
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        approvals = [PendingApproval(**item) for item in data.get("approvals", [])]
        return cls(approvals)

    def append(self, approval: PendingApproval) -> "ApprovalQueue":
        return ApprovalQueue([*self.approvals, approval])


def approval_queue_path(root: Path) -> Path:
    return root / "runs" / "latest" / "pending_approvals.json"


def _matches_any(path: str | None, patterns: set[str]) -> bool:
    if path is None:
        return False
    return any(fnmatch.fnmatch(path, pattern) for pattern in patterns)


def preview_args(args: dict[str, Any]) -> dict[str, Any]:
    preview: dict[str, Any] = {}
    for key, value in args.items():
        if isinstance(value, str):
            preview[key] = redact_text(value[:240])
        else:
            preview[key] = value
    return preview


def classify_action_risk(action: Action, policy: WorkspacePolicy, config: GovernanceConfig) -> ActionRisk:
    policy_decision = check_action(action, policy)
    if not policy_decision.allowed:
        return ActionRisk("blocked", policy_decision.reason)

    path_value = action.args.get("path")
    path = path_value if isinstance(path_value, str) else None
    if _matches_any(path, config.blocked_paths):
        return ActionRisk("blocked", f"blocked path requires denial: {path}")

    if action.action in config.review_actions:
        return ActionRisk("review", f"{action.action} requires human review")
    if _matches_any(path, config.review_paths):
        return ActionRisk("review", f"{action.action} on protected path requires human review")

    return ActionRisk("safe", "safe action")
```

- [ ] **Step 4: 运行测试确认通过**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_approvals -v
```

Expected: PASS。

- [ ] **Step 5: 提交**

```powershell
git add src/specgate/approvals.py tests/test_approvals.py
git commit -m "feat: 新增HITL审批模型"
```

## Task 2: 配置解析和指标字段

**Files:**
- Modify: `src/specgate/config.py`
- Modify: `src/specgate/metrics.py`
- Test: `tests/test_config.py`
- Test: `tests/test_metrics.py`

- [ ] **Step 1: 写配置和指标失败测试**

Append to `tests/test_config.py`:

```python
    def test_load_workspace_config_reads_governance_review_rules(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "specgate.toml").write_text(
                """
[policy]
allowed_actions = ["write_file", "replace_file", "finish"]
allowed_read_paths = ["TASK_SPEC.md"]
allowed_write_paths = ["index.html", "README.md"]

[governance]
profile = "review"
review_actions = ["replace_file"]
review_paths = ["README.md", "src/**"]
blocked_paths = [".env"]
""",
                encoding="utf-8",
            )

            from specgate.config import load_workspace_config

            config = load_workspace_config(root / "specgate.toml")

            self.assertEqual(config.governance.profile, "review")
            self.assertIn("replace_file", config.governance.review_actions)
            self.assertIn("README.md", config.governance.review_paths)
            self.assertIn(".env", config.governance.blocked_paths)

    def test_load_workspace_config_rejects_unknown_governance_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "specgate.toml").write_text(
                """
[policy]
allowed_actions = ["finish"]
allowed_read_paths = []
allowed_write_paths = []

[governance]
profile = "unsafe"
""",
                encoding="utf-8",
            )

            from specgate.config import load_workspace_config

            with self.assertRaises(ValueError):
                load_workspace_config(root / "specgate.toml")
```

Append to `tests/test_metrics.py`:

```python
    def test_warning_summary_when_gate_passes_with_pending_approval(self):
        metrics = RunMetrics(steps=2, finish_actions=1, approval_requests=1, pending_approvals=1)

        trust = build_trust_summary(True, metrics)

        self.assertEqual(trust.status, "warning")
        self.assertIn("pending_approvals_present", trust.reasons)
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_config tests.test_metrics -v
```

Expected: FAIL，原因包括 `load_workspace_config` 不存在、`RunMetrics` 不接受 approval 字段。

- [ ] **Step 3: 扩展 config**

Modify `src/specgate/config.py` to this shape:

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tomllib

from specgate.approvals import GovernanceConfig
from specgate.policy import WorkspacePolicy


@dataclass(frozen=True)
class WorkspaceConfig:
    policy: WorkspacePolicy
    governance: GovernanceConfig


def _load_data(config_path: Path) -> dict:
    return tomllib.loads(config_path.read_text(encoding="utf-8-sig"))


def load_workspace_config(config_path: Path) -> WorkspaceConfig:
    data = _load_data(config_path)
    root = config_path.parent
    policy_data = data["policy"]
    governance_data = data.get("governance", {})
    policy = WorkspacePolicy(
        root=root,
        allowed_actions=set(policy_data["allowed_actions"]),
        allowed_read_paths=set(policy_data["allowed_read_paths"]),
        allowed_write_paths=set(policy_data["allowed_write_paths"]),
    )
    governance = GovernanceConfig(
        profile=str(governance_data.get("profile", "strict")),
        review_actions=set(governance_data.get("review_actions", [])),
        review_paths=set(governance_data.get("review_paths", [])),
        blocked_paths=set(governance_data.get("blocked_paths", [".env"])),
    )
    return WorkspaceConfig(policy=policy, governance=governance)


def load_policy(config_path: Path) -> WorkspacePolicy:
    return load_workspace_config(config_path).policy
```

- [ ] **Step 4: 扩展 metrics**

Modify `src/specgate/metrics.py`:

```python
@dataclass(frozen=True)
class RunMetrics:
    steps: int = 0
    context_chars_max: int = 0
    llm_calls: int = 0
    tool_calls: int = 0
    successful_tool_calls: int = 0
    blocked_actions: int = 0
    parse_errors: int = 0
    gate_runs: int = 0
    gate_failures: int = 0
    finish_actions: int = 0
    max_steps_reached: bool = False
    approval_requests: int = 0
    pending_approvals: int = 0
```

In `build_trust_summary`, add this warning rule after blocked/parse warning checks:

```python
    if metrics.pending_approvals:
        reasons.append("pending_approvals_present")
```

- [ ] **Step 5: 运行测试确认通过**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_config tests.test_metrics -v
```

Expected: PASS。

- [ ] **Step 6: 提交**

```powershell
git add src/specgate/config.py src/specgate/metrics.py tests/test_config.py tests/test_metrics.py
git commit -m "feat: 支持HITL治理配置和审批指标"
```

## Task 3: Runner 执行前审批门

**Files:**
- Modify: `src/specgate/runner.py`
- Test: `tests/test_runner.py`

- [ ] **Step 1: 写 runner 失败测试**

Append to `tests/test_runner.py`:

```python
    def test_review_profile_creates_pending_approval_without_mutating_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "TASK_SPEC.md").write_text("# task", encoding="utf-8")
            (root / "CHECKLIST.md").write_text("", encoding="utf-8")
            (root / "README.md").write_text("original", encoding="utf-8")
            llm = MockLLM(
                [
                    {
                        "schema_version": "1",
                        "action": "replace_file",
                        "args": {"path": "README.md", "content": "changed"},
                    },
                    {"schema_version": "1", "action": "finish", "args": {"summary": "done"}},
                ]
            )
            policy = WorkspacePolicy(root, {"replace_file", "finish"}, {"TASK_SPEC.md"}, {"README.md"})

            from specgate.approvals import GovernanceConfig, approval_queue_path

            result = AgentRunner(
                root,
                llm,
                policy,
                max_steps=2,
                governance_profile="review",
                governance_config=GovernanceConfig(
                    profile="review",
                    review_actions={"replace_file"},
                    review_paths={"README.md"},
                ),
            ).run()

            self.assertEqual((root / "README.md").read_text(encoding="utf-8"), "original")
            self.assertTrue(approval_queue_path(root).exists())
            queue_text = approval_queue_path(root).read_text(encoding="utf-8")
            self.assertIn("approval-step-1", queue_text)
            self.assertIsNotNone(result.metrics)
            self.assertEqual(result.metrics.approval_requests, 1)
            self.assertEqual(result.metrics.pending_approvals, 1)
            self.assertIsNotNone(result.trust)
            self.assertEqual(result.trust.status, "warning")

    def test_strict_profile_blocks_review_action_without_creating_approval(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "TASK_SPEC.md").write_text("# task", encoding="utf-8")
            (root / "CHECKLIST.md").write_text("", encoding="utf-8")
            (root / "README.md").write_text("original", encoding="utf-8")
            llm = MockLLM(
                [
                    {
                        "schema_version": "1",
                        "action": "replace_file",
                        "args": {"path": "README.md", "content": "changed"},
                    }
                ]
            )
            policy = WorkspacePolicy(root, {"replace_file"}, {"TASK_SPEC.md"}, {"README.md"})

            from specgate.approvals import GovernanceConfig, approval_queue_path

            result = AgentRunner(
                root,
                llm,
                policy,
                max_steps=1,
                governance_profile="strict",
                governance_config=GovernanceConfig(
                    profile="strict",
                    review_actions={"replace_file"},
                    review_paths={"README.md"},
                ),
            ).run()

            self.assertEqual((root / "README.md").read_text(encoding="utf-8"), "original")
            self.assertFalse(approval_queue_path(root).exists())
            self.assertIsNotNone(result.metrics)
            self.assertEqual(result.metrics.blocked_actions, 1)
```

- [ ] **Step 2: 运行 runner 测试确认失败**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_runner -v
```

Expected: FAIL，原因是 `AgentRunner` 还不接受 `governance_config`，也不会写 approval queue。

- [ ] **Step 3: 修改 runner 构造函数和导入**

Modify imports in `src/specgate/runner.py`:

```python
from specgate.approvals import (
    ApprovalQueue,
    GovernanceConfig,
    PendingApproval,
    approval_queue_path,
    classify_action_risk,
    preview_args,
)
```

Modify `AgentRunner.__init__` signature:

```python
        governance_profile: str = "strict",
        governance_config: GovernanceConfig | None = None,
```

Inside `__init__`:

```python
        self.governance_config = governance_config or GovernanceConfig(profile=governance_profile)
        queue_path = approval_queue_path(root)
        if queue_path.exists():
            queue_path.unlink()
```

- [ ] **Step 4: 在 dispatch 前插入 review gate**

In `AgentRunner.run`, after `action = parse_action(raw)` and before `tool_result = self.dispatcher.dispatch(action)`, insert:

```python
            risk = classify_action_risk(action, self.policy, self.governance_config)
            if risk.level == "review":
                action_path = action.args.get("path")
                approval = PendingApproval(
                    id=f"approval-step-{step}",
                    step=step,
                    action=action.action,
                    path=action_path if isinstance(action_path, str) else None,
                    risk_level="review",
                    reason=risk.reason,
                    profile=self.governance_profile,
                    arguments_preview=preview_args(action.args),
                )
                if self.governance_profile == "review":
                    queue_path = approval_queue_path(self.root)
                    queue = ApprovalQueue.read(queue_path).append(approval)
                    queue.write(queue_path)
                    metrics = replace(
                        metrics,
                        approval_requests=metrics.approval_requests + 1,
                        pending_approvals=metrics.pending_approvals + 1,
                    )
                    event = {"step": step, "type": "approval_requested", "approval": approval.to_dict()}
                    runtime_feedback.append(event)
                    self.trace.append("approval_requested", event)
                    continue
                metrics = replace(metrics, blocked_actions=metrics.blocked_actions + 1)
                runtime_feedback.append(
                    {"step": step, "type": "tool_result", "action": action.action, "ok": False, "blocked": True, "message": risk.reason}
                )
                self.trace.append(
                    "permission_decision",
                    {
                        "step": step,
                        "action": action.action,
                        "path": action.args.get("path"),
                        "allowed": False,
                        "blocked": True,
                        "reason": risk.reason,
                        "profile": self.governance_profile,
                        "rule_family": "review",
                    },
                )
                continue
            if risk.level == "blocked":
                metrics = replace(metrics, blocked_actions=metrics.blocked_actions + 1)
                runtime_feedback.append(
                    {"step": step, "type": "tool_result", "action": action.action, "ok": False, "blocked": True, "message": risk.reason}
                )
                self.trace.append(
                    "permission_decision",
                    {
                        "step": step,
                        "action": action.action,
                        "path": action.args.get("path"),
                        "allowed": False,
                        "blocked": True,
                        "reason": risk.reason,
                        "profile": self.governance_profile,
                        "rule_family": classify_rule_family(risk.reason),
                    },
                )
                continue
```

Keep the existing safe dispatch block unchanged after this inserted review-gate block. Do not move the existing `tool_result = self.dispatcher.dispatch(action)` line above risk classification.

- [ ] **Step 5: 运行 runner 测试确认通过**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_runner -v
```

Expected: PASS。

- [ ] **Step 6: 提交**

```powershell
git add src/specgate/runner.py tests/test_runner.py
git commit -m "feat: 在Runner中执行HITL审批门"
```

## Task 4: 报告、trace 证据和 eval 汇总

**Files:**
- Modify: `src/specgate/report.py`
- Modify: `src/specgate/eval_runner.py`
- Test: `tests/test_report.py`
- Test: `tests/test_eval_runner.py`

- [ ] **Step 1: 写 report 失败测试**

Append to `tests/test_report.py`:

```python
    def test_generate_report_includes_pending_approvals(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "CHECKLIST.md").write_text("", encoding="utf-8")
            from specgate.approvals import ApprovalQueue, PendingApproval, approval_queue_path

            ApprovalQueue(
                [
                    PendingApproval(
                        id="approval-step-1",
                        step=1,
                        action="replace_file",
                        path="README.md",
                        risk_level="review",
                        reason="<script>alert(1)</script>",
                        profile="review",
                    )
                ]
            ).write(approval_queue_path(root))

            gate = GateResult(True, "passed", [], [])
            report_path = generate_report(root, gate, 1, profile="review")
            html = report_path.read_text(encoding="utf-8")

            self.assertIn("Pending Approvals", html)
            self.assertIn("approval-step-1", html)
            self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)
```

- [ ] **Step 2: 写 eval 失败测试**

Append to `tests/test_eval_runner.py`:

```python
    def test_eval_result_includes_pending_approval_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            case = root / "review-case"
            case.mkdir()
            (case / "TASK_SPEC.md").write_text("# task", encoding="utf-8")
            (case / "CHECKLIST.md").write_text("", encoding="utf-8")
            (case / "README.md").write_text("original", encoding="utf-8")
            (case / "index.html").write_text("<html><body>draft</body></html>", encoding="utf-8")
            (case / "specgate.toml").write_text(
                """
[policy]
allowed_actions = ["replace_file", "finish"]
allowed_read_paths = ["TASK_SPEC.md"]
allowed_write_paths = ["README.md"]

[governance]
profile = "review"
review_actions = ["replace_file"]
review_paths = ["README.md"]
""",
                encoding="utf-8",
            )
            (case / "case.json").write_text(
                json.dumps(
                    {
                        "id": "review-case",
                        "title": "Review case",
                        "category": "governance",
                        "expected": {"should_pass": False, "must_block": False},
                        "mock_responses": [
                            {
                                "schema_version": "1",
                                "action": "replace_file",
                                "args": {"path": "README.md", "content": "changed"},
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            suite = run_eval_suite(root, governance_profile="review", save_workspaces=True)

            self.assertEqual(suite.results[0].approval_requests, 1)
            self.assertEqual(suite.results[0].pending_approvals, 1)
            results_json = (root / "eval-runs" / "latest" / "results.json").read_text(encoding="utf-8")
            self.assertIn('"pending_approvals": 1', results_json)
```

- [ ] **Step 3: 运行 report/eval 测试确认失败**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_report tests.test_eval_runner -v
```

Expected: FAIL，原因是 report/eval 还没有 approval 字段。

- [ ] **Step 4: 修改 report**

In `src/specgate/report.py`, import:

```python
from specgate.approvals import ApprovalQueue, approval_queue_path
```

Add helper:

```python
def _render_pending_approvals(root: Path) -> str:
    queue = ApprovalQueue.read(approval_queue_path(root))
    if not queue.approvals:
        return "<h2>Pending Approvals</h2><p>No pending approvals.</p>"
    rows = "\n".join(
        "<tr>"
        f"<td>{escape(approval.id)}</td>"
        f"<td>{escape(approval.status)}</td>"
        f"<td>{escape(approval.action)}</td>"
        f"<td>{escape(approval.path or '')}</td>"
        f"<td>{escape(approval.reason)}</td>"
        "</tr>"
        for approval in queue.approvals
    )
    return (
        "<h2>Pending Approvals</h2>"
        "<table><thead><tr><th>ID</th><th>Status</th><th>Action</th><th>Path</th><th>Reason</th></tr></thead>"
        f"<tbody>{rows}</tbody></table>"
    )
```

In `generate_report`, compute and render:

```python
    pending_approvals = _render_pending_approvals(root)
```

Place `{pending_approvals}` after `{decisions_summary}`.

- [ ] **Step 5: 修改 eval result**

In `src/specgate/eval_runner.py`, add fields to `EvalCaseResult`:

```python
    approval_requests: int = 0
    pending_approvals: int = 0
```

When `metrics is not None`, set:

```python
                    approval_requests = metrics.approval_requests
                    pending_approvals = metrics.pending_approvals
```

Initialize both to `0` before the metrics branch, and pass them into `EvalCaseResult(...)`.

Also change eval workspace config loading from policy-only to workspace config:

```python
from specgate.config import load_workspace_config
```

Inside `run_eval_suite`, replace:

```python
                policy = load_policy(workspace / "specgate.toml")
                run_result = AgentRunner(
                    workspace,
                    llm,
                    policy,
                    max_steps=case_max_steps,
                    context_strategy=strategy,
                    governance_profile=governance_profile,
                ).run()
```

with:

```python
                workspace_config = load_workspace_config(workspace / "specgate.toml")
                profile = governance_profile or workspace_config.governance.profile
                run_result = AgentRunner(
                    workspace,
                    llm,
                    workspace_config.policy,
                    max_steps=case_max_steps,
                    context_strategy=strategy,
                    governance_profile=profile,
                    governance_config=workspace_config.governance,
                ).run()
```

- [ ] **Step 6: 运行测试确认通过**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_report tests.test_eval_runner -v
```

Expected: PASS。

- [ ] **Step 7: 提交**

```powershell
git add src/specgate/report.py src/specgate/eval_runner.py tests/test_report.py tests/test_eval_runner.py
git commit -m "feat: 展示和汇总HITL审批证据"
```

## Task 5: CLI approvals list 和配置接线

**Files:**
- Modify: `src/specgate/cli.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: 写 CLI 失败测试**

Append to `tests/test_cli.py`:

```python
    def test_approvals_list_reports_empty_queue(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                exit_code = cli.main(["approvals", "list", tmp])

            self.assertEqual(exit_code, 0)
            self.assertIn("no pending approvals", output.getvalue())

    def test_approvals_list_prints_pending_queue(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            from specgate.approvals import ApprovalQueue, PendingApproval, approval_queue_path

            ApprovalQueue(
                [
                    PendingApproval(
                        id="approval-step-1",
                        step=1,
                        action="replace_file",
                        path="README.md",
                        risk_level="review",
                        reason="requires human review",
                        profile="review",
                    )
                ]
            ).write(approval_queue_path(root))

            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                exit_code = cli.main(["approvals", "list", tmp])

            self.assertEqual(exit_code, 0)
            self.assertIn("approval-step-1", output.getvalue())
            self.assertIn("README.md", output.getvalue())
```

- [ ] **Step 2: 运行 CLI 测试确认失败**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_cli -v
```

Expected: FAIL，原因是 `approvals` 子命令不存在。

- [ ] **Step 3: 让 CLI 使用 workspace config**

In `src/specgate/cli.py`, import:

```python
from specgate.approvals import ApprovalQueue, approval_queue_path
from specgate.config import WorkspaceConfig, load_policy, load_workspace_config
```

Modify `_load_demo_policy` only if keeping compatibility. Add helper:

```python
def _load_workspace_settings(root: Path):
    config_path = root / "specgate.toml"
    if config_path.exists():
        return load_workspace_config(config_path)
    policy = _default_demo_policy(root)
    from specgate.approvals import GovernanceConfig

    return WorkspaceConfig(policy=policy, governance=GovernanceConfig())
```

Then in `run_mock_demo`, `run_real_llm`, and eval path, pass both:

```python
    settings = _load_workspace_settings(root)
    result = AgentRunner(
        root,
        llm,
        settings.policy,
        max_steps=5,
        governance_profile=governance_profile,
        governance_config=settings.governance,
    ).run()
```

Do not make additional eval changes in this task; eval config loading is handled explicitly in Task 4.

- [ ] **Step 4: 增加 approvals list 子命令**

In `main`, add parser:

```python
    approvals = sub.add_parser("approvals")
    approvals_sub = approvals.add_subparsers(dest="approvals_command", required=True)
    approvals_list = approvals_sub.add_parser("list")
    approvals_list.add_argument("workspace")
```

Add command handling:

```python
    if args.command == "approvals":
        if args.approvals_command == "list":
            queue = ApprovalQueue.read(approval_queue_path(Path(args.workspace)))
            if not queue.approvals:
                print("no pending approvals")
                return 0
            print("ID\tSTATUS\tACTION\tPATH\tREASON")
            for approval in queue.approvals:
                print(
                    f"{approval.id}\t{approval.status}\t{approval.action}\t"
                    f"{approval.path or ''}\t{approval.reason}"
                )
            return 0
```

- [ ] **Step 5: 运行 CLI 测试确认通过**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_cli -v
```

Expected: PASS。

- [ ] **Step 6: 提交**

```powershell
git add src/specgate/cli.py tests/test_cli.py
git commit -m "feat: 增加HITL审批列表命令"
```

## Task 6: 端到端验证、文档和最终检查

**Files:**
- Modify: `README.md`

- [ ] **Step 1: 更新 README**

Add a short section near governance/eval documentation:

````markdown
### HITL Review Gate

SpecGate supports a `review` governance profile for high-risk actions. A review-required action is not executed automatically. Instead, the run writes `runs/latest/pending_approvals.json`, records an `approval_requested` trace event, and shows the pending approval in the static report.

Run with review profile:

```powershell
$env:PYTHONPATH="src"
python -m specgate.cli run-mock-demo examples/knowledge_nav --governance-profile review
```

List pending approvals:

```powershell
$env:PYTHONPATH="src"
python -m specgate.cli approvals list examples/knowledge_nav
```

The first version only creates and lists pending approvals. Approval, denial, and resume are intentionally separate follow-up features.
````

- [ ] **Step 2: 运行完整测试**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest discover -s tests -v
```

Expected: all tests PASS。

- [ ] **Step 3: 运行 mock eval 验证**

Run:

```powershell
$env:PYTHONPATH="src"
python -m specgate.cli eval examples/eval_cases --context-strategy injection-safe --governance-profile review --save-workspaces
```

Expected: command finishes without traceback. The exact passed/expected count may depend on eval case expectations, but `examples/eval_cases/eval-runs/latest/results.json` should include `approval_requests` and `pending_approvals`.

- [ ] **Step 4: 检查不要提交生成物**

Run:

```powershell
git status --short
```

Expected: source/docs/test files may be modified; `examples/eval_cases/eval-runs/` remains untracked and must not be staged.

- [ ] **Step 5: 提交 README 和最终整理**

```powershell
git add README.md
git commit -m "docs: 记录HITL审批门用法"
```

- [ ] **Step 6: 最终验证**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest discover -s tests -v
git status --short
```

Expected: tests PASS；只有 `examples/eval_cases/eval-runs/` 这类生成物未跟踪，或工作区干净。

## Plan Self-Review

- Spec coverage: plan 覆盖风险分类、pending approval 队列、runner 执行前阻断、trace/report/eval/CLI 展示、MockLLM 测试和无网络验证。
- Placeholder scan: 没有未完成占位标记；每个任务都有具体文件、测试、实现要点、验证命令和提交命令。
- Type consistency: `GovernanceConfig`、`PendingApproval`、`ApprovalQueue`、`RunMetrics.approval_requests`、`RunMetrics.pending_approvals` 在各任务中命名一致。
- Scope check: 不包含 approve、deny、resume、WebUI 或 shell 工具。
