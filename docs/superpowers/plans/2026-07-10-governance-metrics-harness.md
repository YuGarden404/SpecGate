# Governance Metrics Harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add deterministic governance metrics, permission decisions, and trust summaries to SpecGate runs.

**Architecture:** Keep enforcement in the existing `WorkspacePolicy`, `ToolDispatcher`, snapshot, and Gate layers. Add a pure `specgate.metrics` module for data structures and classification, then have `AgentRunner` collect those values, trace them, expose them in `RunResult`, render them in reports, and aggregate them in eval results.

**Tech Stack:** Python standard library, `dataclasses`, existing `unittest` suite, existing MockLLM and trace/report/eval modules.

---

## File Structure

- Create `src/specgate/metrics.py`: pure dataclasses and deterministic helper functions for run metrics, permission decisions, and trust classification.
- Create `tests/test_metrics.py`: unit tests for rule-family classification and trust summary behavior.
- Modify `src/specgate/runner.py`: collect metrics and permission decisions during the existing agent loop.
- Modify `tests/test_runner.py`: assert trusted, warning, blocked, parse-error, and max-step behavior.
- Modify `src/specgate/report.py`: render trust, metrics, and permission decisions in the static HTML report.
- Modify `tests/test_report.py`: assert report sections and values.
- Modify `src/specgate/eval_runner.py`: copy selected metrics and trust status into `EvalCaseResult` and `results.json`.
- Modify `tests/test_eval_runner.py`: assert eval JSON contains governance metrics.
- Modify `src/specgate/cli.py`: add `--governance-profile` to `run`, `run-mock-demo`, and `eval`.
- Modify `tests/test_cli.py`: assert CLI forwards the governance profile and rejects invalid values.
- Modify `README.md`: document governance metrics as a mock-first harness feature.

## Task 1: Pure Metrics Model

**Files:**
- Create: `src/specgate/metrics.py`
- Test: `tests/test_metrics.py`

- [ ] **Step 1: Write failing tests for metrics helpers**

Create `tests/test_metrics.py`:

```python
import unittest

from specgate.metrics import (
    PermissionDecision,
    RunMetrics,
    build_trust_summary,
    classify_rule_family,
)


class MetricsTests(unittest.TestCase):
    def test_classifies_rule_family_from_reason(self):
        self.assertEqual(classify_rule_family("unknown action: run_command"), "action")
        self.assertEqual(classify_rule_family("path escapes workspace"), "path")
        self.assertEqual(classify_rule_family("write path not allowed: .env"), "allowlist")
        self.assertEqual(classify_rule_family("file changed since run started"), "snapshot")
        self.assertEqual(classify_rule_family("unknown tool: shell"), "tool")
        self.assertEqual(classify_rule_family("finish requested"), "none")

    def test_permission_decision_from_tool_result_shape(self):
        decision = PermissionDecision(
            step=2,
            action="write_file",
            path=".env",
            allowed=False,
            blocked=True,
            reason="write path not allowed: .env",
            profile="strict",
            rule_family="allowlist",
        )

        self.assertEqual(decision.step, 2)
        self.assertFalse(decision.allowed)
        self.assertTrue(decision.blocked)
        self.assertEqual(decision.rule_family, "allowlist")

    def test_trusted_summary_requires_clean_finish_and_passing_gate(self):
        metrics = RunMetrics(
            steps=2,
            llm_calls=2,
            tool_calls=2,
            successful_tool_calls=2,
            finish_actions=1,
        )

        trust = build_trust_summary(True, metrics)

        self.assertEqual(trust.status, "trusted")
        self.assertEqual(trust.reasons, ["clean_finish"])

    def test_warning_summary_when_gate_passes_with_blocked_action(self):
        metrics = RunMetrics(
            steps=3,
            llm_calls=3,
            tool_calls=3,
            successful_tool_calls=2,
            blocked_actions=1,
            finish_actions=1,
        )

        trust = build_trust_summary(True, metrics)

        self.assertEqual(trust.status, "warning")
        self.assertIn("blocked_actions_present", trust.reasons)

    def test_failed_summary_when_gate_fails_or_max_steps_reached(self):
        gate_failed = build_trust_summary(False, RunMetrics(steps=1, max_steps_reached=False))
        exhausted = build_trust_summary(True, RunMetrics(steps=5, max_steps_reached=True))

        self.assertEqual(gate_failed.status, "failed")
        self.assertIn("gate_failed", gate_failed.reasons)
        self.assertEqual(exhausted.status, "failed")
        self.assertIn("max_steps_reached", exhausted.reasons)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the new metrics tests and verify failure**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_metrics -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'specgate.metrics'`.

- [ ] **Step 3: Add the metrics implementation**

Create `src/specgate/metrics.py`:

```python
from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
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

    def to_dict(self) -> dict[str, int | bool]:
        return asdict(self)


@dataclass(frozen=True)
class PermissionDecision:
    step: int
    action: str
    path: str | None
    allowed: bool
    blocked: bool
    reason: str
    profile: str = "strict"
    rule_family: str = "none"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class TrustSummary:
    status: str
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def classify_rule_family(reason: str) -> str:
    normalized = reason.lower()
    if "unknown action" in normalized or "unimplemented action" in normalized:
        return "action"
    if "path escapes workspace" in normalized or "path must be" in normalized or "missing required path" in normalized:
        return "path"
    if "not allowed" in normalized:
        return "allowlist"
    if "changed since run started" in normalized or "snapshot" in normalized:
        return "snapshot"
    if "unknown tool" in normalized or "tool" in normalized:
        return "tool"
    return "none"


def build_trust_summary(passed: bool, metrics: RunMetrics) -> TrustSummary:
    reasons: list[str] = []
    if not passed:
        reasons.append("gate_failed")
    if metrics.max_steps_reached:
        reasons.append("max_steps_reached")
    if metrics.finish_actions == 0:
        reasons.append("missing_finish")
    if metrics.blocked_actions:
        reasons.append("blocked_actions_present")
    if metrics.parse_errors:
        reasons.append("parse_errors_present")

    if not passed or metrics.max_steps_reached or metrics.finish_actions == 0:
        return TrustSummary("failed", reasons)
    if metrics.blocked_actions or metrics.parse_errors:
        return TrustSummary("warning", reasons)
    return TrustSummary("trusted", ["clean_finish"])
```

- [ ] **Step 4: Run metrics tests and verify pass**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_metrics -v
```

Expected: all tests in `tests.test_metrics` pass.

- [ ] **Step 5: Commit Task 1**

```powershell
git add src/specgate/metrics.py tests/test_metrics.py
git commit -m "feat: 新增运行治理指标模型"
```

## Task 2: Runner Metrics and Permission Trace

**Files:**
- Modify: `src/specgate/runner.py`
- Test: `tests/test_runner.py`

- [ ] **Step 1: Add failing runner assertions**

In `tests/test_runner.py`, import JSON:

```python
import json
```

Add these tests inside `RunnerTests`:

```python
    def test_successful_run_records_trusted_metrics(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "TASK_SPEC.md").write_text("# task", encoding="utf-8")
            (root / "CHECKLIST.md").write_text("- must include Task\n", encoding="utf-8")
            fixed = (
                '<!doctype html><html><head><meta name="viewport" content="width=device-width">'
                "<title>Task</title></head><body>Task Search Detail</body></html>"
            )
            llm = MockLLM(
                [
                    {"schema_version": "1", "action": "write_file", "args": {"path": "index.html", "content": fixed}},
                    {"schema_version": "1", "action": "finish", "args": {"summary": "done"}},
                ]
            )
            policy = WorkspacePolicy(
                root,
                {"write_file", "finish"},
                {"TASK_SPEC.md", "CHECKLIST.md", "index.html"},
                {"index.html"},
            )

            result = AgentRunner(root, llm, policy, max_steps=3).run()

            self.assertTrue(result.passed)
            self.assertEqual(result.metrics.llm_calls, 2)
            self.assertEqual(result.metrics.tool_calls, 2)
            self.assertEqual(result.metrics.successful_tool_calls, 2)
            self.assertEqual(result.metrics.gate_runs, 1)
            self.assertEqual(result.metrics.gate_failures, 0)
            self.assertEqual(result.metrics.finish_actions, 1)
            self.assertEqual(result.trust.status, "trusted")
            self.assertEqual(result.profile, "strict")

    def test_blocked_action_records_permission_decision_and_warning_metrics(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "TASK_SPEC.md").write_text("# task", encoding="utf-8")
            (root / "CHECKLIST.md").write_text("", encoding="utf-8")
            llm = MockLLM(
                [
                    {"schema_version": "1", "action": "write_file", "args": {"path": ".env", "content": "SECRET=x"}},
                    {"schema_version": "1", "action": "finish", "args": {"summary": "done"}},
                ]
            )
            policy = WorkspacePolicy(
                root,
                {"write_file", "finish"},
                {"TASK_SPEC.md", "CHECKLIST.md", "index.html"},
                {"index.html"},
            )

            result = AgentRunner(root, llm, policy, max_steps=2, governance_profile="review").run()

            self.assertEqual(result.metrics.blocked_actions, 1)
            self.assertEqual(result.permission_decisions[0].path, ".env")
            self.assertEqual(result.permission_decisions[0].profile, "review")
            self.assertEqual(result.permission_decisions[0].rule_family, "allowlist")
            trace_events = [
                json.loads(line)
                for line in (root / "runs" / "latest" / "trace.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            self.assertTrue(any(event["event_type"] == "permission_decision" for event in trace_events))
            self.assertTrue(any(event["event_type"] == "run_summary" for event in trace_events))

    def test_max_step_exhaustion_marks_failed_trust(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "TASK_SPEC.md").write_text("# task", encoding="utf-8")
            (root / "CHECKLIST.md").write_text("- must include Task\n", encoding="utf-8")
            llm = MockLLM(
                [
                    {"schema_version": "1", "action": "read_file", "args": {"path": "TASK_SPEC.md"}},
                ]
            )
            policy = WorkspacePolicy(
                root,
                {"read_file", "finish"},
                {"TASK_SPEC.md", "CHECKLIST.md", "index.html"},
                {"index.html"},
            )

            result = AgentRunner(root, llm, policy, max_steps=1).run()

            self.assertTrue(result.metrics.max_steps_reached)
            self.assertEqual(result.trust.status, "failed")
            self.assertIn("max_steps_reached", result.trust.reasons)
```

- [ ] **Step 2: Run runner tests and verify failure**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_runner -v
```

Expected: FAIL because `RunResult` has no `metrics`, `trust`, `profile`, or `permission_decisions`, and `AgentRunner` has no `governance_profile` parameter.

- [ ] **Step 3: Update `RunResult` and `AgentRunner.__init__`**

In `src/specgate/runner.py`, add imports:

```python
from specgate.metrics import (
    PermissionDecision,
    RunMetrics,
    TrustSummary,
    build_trust_summary,
    classify_rule_family,
)
```

Replace `RunResult` with:

```python
@dataclass(frozen=True)
class RunResult:
    passed: bool
    steps: int
    final_gate: GateResult | None
    context_chars_max: int = 0
    metrics: RunMetrics | None = None
    permission_decisions: list[PermissionDecision] | None = None
    trust: TrustSummary | None = None
    profile: str = "strict"
```

Add `governance_profile` to `AgentRunner.__init__`:

```python
        governance_profile: str = "strict",
```

and store it:

```python
        self.governance_profile = governance_profile
```

- [ ] **Step 4: Add helper methods in `AgentRunner`**

Inside `AgentRunner`, before `run`, add:

```python
    def _permission_decision(self, step: int, action_name: str, path: object, allowed: bool, blocked: bool, reason: str) -> PermissionDecision:
        return PermissionDecision(
            step=step,
            action=action_name,
            path=path if isinstance(path, str) else None,
            allowed=allowed,
            blocked=blocked,
            reason=reason,
            profile=self.governance_profile,
            rule_family=classify_rule_family(reason),
        )

    def _finish_result(
        self,
        passed: bool,
        steps: int,
        final_gate: GateResult | None,
        context_chars_max: int,
        metrics: RunMetrics,
        permission_decisions: list[PermissionDecision],
    ) -> RunResult:
        metrics.steps = steps
        metrics.context_chars_max = context_chars_max
        trust = build_trust_summary(passed, metrics)
        self.trace.append(
            "run_summary",
            {
                "profile": self.governance_profile,
                "metrics": metrics.to_dict(),
                "trust": trust.to_dict(),
            },
        )
        if final_gate is not None:
            append_memory(self.root, passed, steps, final_gate.summary)
        return RunResult(
            passed=passed,
            steps=steps,
            final_gate=final_gate,
            context_chars_max=context_chars_max,
            metrics=metrics,
            permission_decisions=list(permission_decisions),
            trust=trust,
            profile=self.governance_profile,
        )
```

- [ ] **Step 5: Update `run` to collect metrics**

At the start of `run`, add:

```python
        metrics = RunMetrics()
        permission_decisions: list[PermissionDecision] = []
```

After `context_chars_max` update, add:

```python
            metrics.context_chars_max = context_chars_max
```

Before `raw = self.llm.complete(context)`, add:

```python
            metrics.llm_calls += 1
```

In the parse error block, add:

```python
                metrics.parse_errors += 1
```

After `tool_result = self.dispatcher.dispatch(action)`, add:

```python
            metrics.tool_calls += 1
            if tool_result.ok:
                metrics.successful_tool_calls += 1
            if tool_result.blocked:
                metrics.blocked_actions += 1
            if action.action == "finish":
                metrics.finish_actions += 1

            decision = self._permission_decision(
                step=step,
                action_name=tool_result.action,
                path=action.args.get("path"),
                allowed=tool_result.ok and not tool_result.blocked,
                blocked=tool_result.blocked,
                reason=tool_result.message,
            )
            permission_decisions.append(decision)
            self.trace.append("permission_decision", decision.to_dict())
```

Inside the Gate block, before appending `gate_result`, add:

```python
                metrics.gate_runs += 1
                if not latest_gate.passed:
                    metrics.gate_failures += 1
```

Replace the finish return with:

```python
                return self._finish_result(
                    latest_gate.passed,
                    step,
                    latest_gate,
                    context_chars_max,
                    metrics,
                    permission_decisions,
                )
```

At loop exhaustion, before the final return, add:

```python
        metrics.max_steps_reached = True
        if latest_gate is None:
            latest_gate = run_html_gate(self.root / "index.html", self.root / "CHECKLIST.md")
            metrics.gate_runs += 1
            if not latest_gate.passed:
                metrics.gate_failures += 1
```

Then return:

```python
        return self._finish_result(
            latest_gate.passed,
            self.max_steps,
            latest_gate,
            context_chars_max,
            metrics,
            permission_decisions,
        )
```

- [ ] **Step 6: Run runner tests and full tests**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_runner -v
python -m unittest discover -s tests -v
```

Expected: all tests pass. If old tests access `result.context_chars_max`, they still pass because the field remains.

- [ ] **Step 7: Commit Task 2**

```powershell
git add src/specgate/runner.py tests/test_runner.py
git commit -m "feat: 在主循环记录治理指标与权限决策"
```

## Task 3: Governance Report Sections

**Files:**
- Modify: `src/specgate/report.py`
- Test: `tests/test_report.py`

- [ ] **Step 1: Write failing report test**

In `tests/test_report.py`, add imports:

```python
from specgate.metrics import PermissionDecision, RunMetrics, TrustSummary
```

Add this test:

```python
    def test_report_renders_trust_metrics_and_permission_decisions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gate = GateResult(True, [GateCheck("doctype", True, "ok")], [], "Gate passed")
            metrics = RunMetrics(
                steps=2,
                context_chars_max=1200,
                llm_calls=2,
                tool_calls=2,
                successful_tool_calls=1,
                blocked_actions=1,
                gate_runs=1,
                finish_actions=1,
            )
            decisions = [
                PermissionDecision(
                    step=1,
                    action="write_file",
                    path=".env",
                    allowed=False,
                    blocked=True,
                    reason="write path not allowed: .env",
                    profile="review",
                    rule_family="allowlist",
                )
            ]
            trust = TrustSummary("warning", ["blocked_actions_present"])

            output = generate_report(
                root,
                gate,
                steps=2,
                metrics=metrics,
                permission_decisions=decisions,
                trust=trust,
                profile="review",
            )

            html = output.read_text(encoding="utf-8")
            self.assertIn("Trust Summary", html)
            self.assertIn("warning", html)
            self.assertIn("blocked_actions_present", html)
            self.assertIn("Run Metrics", html)
            self.assertIn("llm_calls", html)
            self.assertIn("2", html)
            self.assertIn("Permission Decisions", html)
            self.assertIn("write path not allowed: .env", html)
            self.assertIn("review", html)
```

- [ ] **Step 2: Run report tests and verify failure**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_report -v
```

Expected: FAIL because `generate_report` does not accept the new keyword arguments.

- [ ] **Step 3: Update report helpers**

In `src/specgate/report.py`, add imports:

```python
from specgate.metrics import PermissionDecision, RunMetrics, TrustSummary
```

Add helper functions:

```python
def _render_trust_summary(trust: TrustSummary | None, profile: str) -> str:
    if trust is None:
        return "<p>No trust summary recorded.</p>"
    reasons = "".join(f"<li>{escape(reason)}</li>" for reason in trust.reasons)
    return (
        f"<p>Status: <strong>{escape(trust.status)}</strong></p>"
        f"<p>Profile: <code>{escape(profile)}</code></p>"
        f"<ul>{reasons}</ul>"
    )


def _render_metrics(metrics: RunMetrics | None) -> str:
    if metrics is None:
        return "<p>No run metrics recorded.</p>"
    rows = "\n".join(
        f"<tr><th>{escape(str(key))}</th><td>{escape(str(value))}</td></tr>"
        for key, value in metrics.to_dict().items()
    )
    return f"<table>{rows}</table>"


def _render_permission_decisions(decisions: list[PermissionDecision] | None) -> str:
    if not decisions:
        return "<p>No permission decisions recorded.</p>"
    rows = "\n".join(
        "<tr>"
        f"<td>{decision.step}</td>"
        f"<td>{escape(decision.action)}</td>"
        f"<td>{escape(decision.path or '')}</td>"
        f"<td>{'yes' if decision.allowed else 'no'}</td>"
        f"<td>{'yes' if decision.blocked else 'no'}</td>"
        f"<td>{escape(decision.rule_family)}</td>"
        f"<td>{escape(decision.reason)}</td>"
        "</tr>"
        for decision in decisions
    )
    return (
        "<table><thead><tr><th>Step</th><th>Action</th><th>Path</th>"
        "<th>Allowed</th><th>Blocked</th><th>Rule</th><th>Reason</th></tr></thead>"
        f"<tbody>{rows}</tbody></table>"
    )
```

- [ ] **Step 4: Update `generate_report` signature and HTML**

Change the function signature:

```python
def generate_report(
    root: Path,
    gate: GateResult,
    steps: int,
    metrics: RunMetrics | None = None,
    permission_decisions: list[PermissionDecision] | None = None,
    trust: TrustSummary | None = None,
    profile: str = "strict",
) -> Path:
```

Before `html = f"""...`, compute:

```python
    trust_html = _render_trust_summary(trust, profile)
    metrics_html = _render_metrics(metrics)
    permission_html = _render_permission_decisions(permission_decisions)
```

Inside the body, after the Gate paragraph, add:

```html
  <h2>Trust Summary</h2>
  {trust_html}
  <h2>Run Metrics</h2>
  {metrics_html}
  <h2>Permission Decisions</h2>
  {permission_html}
```

- [ ] **Step 5: Update report call sites**

Search for call sites:

```powershell
git grep -n "generate_report"
```

Where `run_result` is available, pass:

```python
metrics=run_result.metrics,
permission_decisions=run_result.permission_decisions,
trust=run_result.trust,
profile=run_result.profile,
```

Keep old tests working because all new parameters have defaults.

- [ ] **Step 6: Run report tests and full tests**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_report -v
python -m unittest discover -s tests -v
```

Expected: all tests pass.

- [ ] **Step 7: Commit Task 3**

```powershell
git add src/specgate/report.py tests/test_report.py src/specgate/cli.py
git commit -m "feat: 在运行报告展示信任摘要和治理指标"
```

## Task 4: Eval Governance Fields

**Files:**
- Modify: `src/specgate/eval_runner.py`
- Test: `tests/test_eval_runner.py`

- [ ] **Step 1: Write failing eval test**

In `tests/test_eval_runner.py`, add or extend an eval test with these assertions after calling `run_eval_suite`:

```python
        result = suite.results[0]
        self.assertIsInstance(result.tool_calls, int)
        self.assertIsInstance(result.successful_tool_calls, int)
        self.assertIsInstance(result.gate_runs, int)
        self.assertIn(result.trust_status, {"trusted", "warning", "failed"})

        results_json = root / "eval-runs" / "latest" / "results.json"
        text = results_json.read_text(encoding="utf-8")
        self.assertIn('"trust_status"', text)
        self.assertIn('"tool_calls"', text)
```

- [ ] **Step 2: Run eval tests and verify failure**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_eval_runner -v
```

Expected: FAIL because `EvalCaseResult` does not expose `tool_calls`, `successful_tool_calls`, `gate_runs`, or `trust_status`.

- [ ] **Step 3: Extend `EvalCaseResult`**

In `src/specgate/eval_runner.py`, add fields to `EvalCaseResult`:

```python
    tool_calls: int = 0
    successful_tool_calls: int = 0
    gate_runs: int = 0
    trust_status: str = "failed"
```

- [ ] **Step 4: Populate fields from `run_result.metrics` and `run_result.trust`**

Before appending `EvalCaseResult`, add:

```python
                metrics = run_result.metrics
                trust = run_result.trust
```

In the `EvalCaseResult(...)` call, add:

```python
                        tool_calls=metrics.tool_calls if metrics else 0,
                        successful_tool_calls=metrics.successful_tool_calls if metrics else 0,
                        gate_runs=metrics.gate_runs if metrics else 0,
                        trust_status=trust.status if trust else "failed",
```

- [ ] **Step 5: Prefer runner metrics over trace counting when available**

After `_count_trace_events`, add:

```python
                if run_result.metrics is not None:
                    parse_errors = run_result.metrics.parse_errors
                    blocked_actions = run_result.metrics.blocked_actions
                    gate_failures = run_result.metrics.gate_failures
```

Keep the trace fallback so existing trace-based behavior remains robust.

- [ ] **Step 6: Run eval tests and full tests**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_eval_runner -v
python -m unittest discover -s tests -v
```

Expected: all tests pass.

- [ ] **Step 7: Commit Task 4**

```powershell
git add src/specgate/eval_runner.py tests/test_eval_runner.py
git commit -m "feat: 在评估结果中汇总治理指标"
```

## Task 5: Governance Profile CLI and Documentation

**Files:**
- Modify: `src/specgate/cli.py`
- Modify: `tests/test_cli.py`
- Modify: `README.md`

- [ ] **Step 1: Write failing CLI tests**

In `tests/test_cli.py`, add these tests inside `CliTests`:

```python
    def test_run_mock_demo_records_governance_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "TASK_SPEC.md").write_text("# task\nCreate page", encoding="utf-8")
            (root / "CHECKLIST.md").write_text("- must include Spec\n- must include Gate\n", encoding="utf-8")

            code = run_mock_demo(root, governance_profile="review")

            self.assertEqual(code, 0)
            trace_text = (root / "runs" / "latest" / "trace.jsonl").read_text(encoding="utf-8")
            self.assertIn('"profile": "review"', trace_text)

    def test_cli_rejects_invalid_governance_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SystemExit) as raised:
                main(["run-mock-demo", str(Path(tmp)), "--governance-profile", "unsafe"])

            self.assertEqual(raised.exception.code, 2)
```

If the current CLI tests use subprocess-style argparse failure, assert the same failure style already used elsewhere in the file.

- [ ] **Step 2: Run CLI tests and verify failure**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_cli -v
```

Expected: FAIL because the parser does not know `--governance-profile`.

- [ ] **Step 3: Add profile validation helper**

In `src/specgate/cli.py`, add:

```python
GOVERNANCE_PROFILES = ("strict", "demo", "review")
```

When constructing argparse subcommands for `run`, `run-mock-demo`, and `eval`, add:

```python
    parser.add_argument(
        "--governance-profile",
        choices=GOVERNANCE_PROFILES,
        default="strict",
        help="Governance profile recorded in trace, metrics, and report.",
    )
```

- [ ] **Step 4: Pass profile into runners**

In `run_real_llm`, `run_mock_demo`, and eval path functions, pass:

```python
governance_profile=args.governance_profile
```

For direct function signatures, add:

```python
governance_profile: str = "strict",
```

and pass it to `AgentRunner(...)`:

```python
AgentRunner(
    root,
    llm,
    policy,
    max_steps=max_steps,
    context_strategy=context_strategy,
    governance_profile=governance_profile,
)
```

For `run_eval_suite`, add the same parameter and pass it into each `AgentRunner`.

- [ ] **Step 5: Update README**

Add a short section after the eval or report section:

```markdown
## Governance Metrics

SpecGate records deterministic governance evidence for each run:

- run metrics such as LLM calls, tool calls, blocked actions, parse errors, Gate runs, and max-step exhaustion;
- permission decisions for every parsed action, including the profile, target path, rule family, and reason;
- a trust summary classified as `trusted`, `warning`, or `failed`.

Use the default strict profile for normal runs:

```powershell
$env:PYTHONPATH="src"
python -m specgate.cli run-mock-demo examples/knowledge_nav --governance-profile strict
```

The `review` profile records high-risk blocked actions as review-oriented evidence, but it does not bypass the allowlist or snapshot protections.
```

- [ ] **Step 6: Run CLI tests and full tests**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_cli -v
python -m unittest discover -s tests -v
```

Expected: all tests pass.

- [ ] **Step 7: Commit Task 5**

```powershell
git add src/specgate/cli.py src/specgate/eval_runner.py tests/test_cli.py README.md
git commit -m "feat: 支持治理配置并记录运行可信度"
```

## Final Verification

- [ ] **Run the complete unit test suite**

```powershell
$env:PYTHONPATH="src"
python -m unittest discover -s tests -v
```

Expected: all tests pass.

- [ ] **Run mock demo with governance profile**

```powershell
$env:PYTHONPATH="src"
python -m specgate.cli run-mock-demo examples/knowledge_nav --governance-profile strict
```

Expected: command finishes successfully and `examples/knowledge_nav/reports/latest/index.html` contains `Trust Summary`, `Run Metrics`, and `Permission Decisions`.

- [ ] **Run mock eval**

```powershell
$env:PYTHONPATH="src"
python -m specgate.cli eval examples/eval_cases --context-strategy injection-safe --governance-profile strict
```

Expected: command finishes successfully and `examples/eval_cases/eval-runs/latest/results.json` contains `trust_status`, `tool_calls`, and `gate_runs`.

## Plan Self-Review

- Spec coverage: the plan covers metrics, permission decisions, profile, trust summary, trace, report, eval aggregation, CLI access, and mock-first tests.
- Placeholder scan: no task uses unspecified placeholders; every task names concrete files, functions, commands, and expected outcomes.
- Type consistency: the same `RunMetrics`, `PermissionDecision`, and `TrustSummary` types are used across runner, report, and eval tasks.
