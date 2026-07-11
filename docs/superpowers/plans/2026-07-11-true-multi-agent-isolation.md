# True Multi-Agent Isolation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a deterministic, mock-first multi-agent isolation mode where planner, implementer, and reviewer run as separate harness roles with code-enforced context, state, and action boundaries.

**Architecture:** Add `multi-agent-isolated` as a new context strategy. Keep `AgentRunner` as the central governance entry point, but extract reusable runner helpers so the new role coordinator reuses the same policy, snapshot, HITL, tool dispatch, gate, trace, metrics, and report paths. Store role execution evidence in `runs/latest/isolation.json` and surface it through metrics, eval, benchmark, and report.

**Tech Stack:** Python standard library, `unittest`, existing SpecGate modules under `src/specgate`, deterministic `MockLLM`, existing JSON trace/report artifacts.

---

## File Structure

Create:

- `src/specgate/multi_agent.py`: role execution coordinator and small data models that do not perform file writes directly.
- `examples/eval_cases/true-multi-agent-isolation/TASK_SPEC.md`: deterministic isolation suite task.
- `examples/eval_cases/true-multi-agent-isolation/CHECKLIST.md`: deterministic gate checklist.
- `examples/eval_cases/true-multi-agent-isolation/index.html`: empty starting artifact.
- `examples/eval_cases/true-multi-agent-isolation/specgate.toml`: workspace strategy config.
- `examples/eval_cases/true-multi-agent-isolation/case.json`: mock responses for planner, implementer, reviewer.

Modify:

- `src/specgate/isolation.py`: add role capability checks and serializable execution evidence.
- `src/specgate/context.py`: accept `multi-agent-isolated` and build role-specific context sections.
- `src/specgate/config.py`: accept `multi-agent-isolated` as a valid context strategy.
- `src/specgate/metrics.py`: add role-level counters and trust degradation reason for role cycle limit.
- `src/specgate/runner.py`: route `multi-agent-isolated` into the coordinator and reuse governance helpers.
- `src/specgate/eval_runner.py`: include role-level metrics in `EvalCaseResult`.
- `src/specgate/benchmark.py`: aggregate role-level benchmark metrics.
- `src/specgate/report.py`: render role execution evidence while preserving old role definition evidence.
- `README.md`: document the new strategy and example commands.

Test:

- `tests/test_isolation.py`: unit coverage for role capability and evidence serialization.
- `tests/test_context_strategy.py`: role-specific context rendering.
- `tests/test_runner.py`: coordinator ordering, blocked role writes, policy preservation, HITL preservation, repair cycle.
- `tests/test_eval_runner.py`: eval result role metrics.
- `tests/test_benchmark.py`: benchmark accepts and aggregates `multi-agent-isolated`.
- `tests/test_report.py`: report rendering and escaping for role executions.

---

### Task 1: Add Role Capability and Execution Evidence Models

**Files:**

- Modify: `src/specgate/isolation.py`
- Test: `tests/test_isolation.py`

- [ ] **Step 1: Write failing tests for role action capability**

Add these tests to `tests/test_isolation.py`:

```python
from specgate.isolation import (
    RoleExecution,
    action_allowed_for_role,
    build_isolation_evidence,
)


class IsolationCapabilityTests(unittest.TestCase):
    def test_planner_and_reviewer_cannot_write_files(self):
        self.assertFalse(action_allowed_for_role("planner", "write_file"))
        self.assertFalse(action_allowed_for_role("planner", "replace_file"))
        self.assertFalse(action_allowed_for_role("reviewer", "write_file"))
        self.assertFalse(action_allowed_for_role("reviewer", "replace_file"))

    def test_implementer_can_write_files(self):
        self.assertTrue(action_allowed_for_role("implementer", "write_file"))
        self.assertTrue(action_allowed_for_role("implementer", "replace_file"))
        self.assertTrue(action_allowed_for_role("implementer", "finish"))

    def test_action_allowed_for_role_rejects_unknown_role(self):
        with self.assertRaises(ValueError):
            action_allowed_for_role("auditor", "finish")

    def test_role_execution_to_dict_is_serializable(self):
        execution = RoleExecution(
            role="planner",
            phase="plan",
            context_chars=123,
            visible_sections=("Task", "Checklist"),
            allowed_actions=("read_file", "finish"),
            attempted_action="finish",
            action_allowed_by_role=True,
            blocked_reason=None,
            summary="Plan the page",
        )

        self.assertEqual(
            execution.to_dict(),
            {
                "role": "planner",
                "phase": "plan",
                "context_chars": 123,
                "visible_sections": ["Task", "Checklist"],
                "allowed_actions": ["read_file", "finish"],
                "attempted_action": "finish",
                "action_allowed_by_role": True,
                "blocked_reason": None,
                "summary": "Plan the page",
            },
        )

    def test_build_isolation_evidence_includes_executions(self):
        execution = RoleExecution(
            role="reviewer",
            phase="review",
            context_chars=321,
            visible_sections=("Final Artifact",),
            allowed_actions=("finish",),
            attempted_action="write_file",
            action_allowed_by_role=False,
            blocked_reason="role reviewer cannot perform write_file",
            summary=None,
        )

        evidence = build_isolation_evidence(
            strategy="multi-agent-isolated",
            executions=[execution],
            review_repairs=1,
        )

        self.assertEqual(evidence["strategy"], "multi-agent-isolated")
        self.assertEqual(evidence["role_runs"], 1)
        self.assertEqual(evidence["role_blocked_actions"], 1)
        self.assertEqual(evidence["review_repairs"], 1)
        self.assertEqual(evidence["executions"][0]["role"], "reviewer")
```

- [ ] **Step 2: Run the focused failing tests**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_isolation -v
```

Expected: FAIL with import errors for `RoleExecution`, `action_allowed_for_role`, or `build_isolation_evidence`.

- [ ] **Step 3: Implement minimal role capability and evidence model**

Update `src/specgate/isolation.py` with:

```python
@dataclass(frozen=True)
class RoleExecution:
    role: str
    phase: str
    context_chars: int
    visible_sections: tuple[str, ...]
    allowed_actions: tuple[str, ...]
    attempted_action: str | None = None
    action_allowed_by_role: bool = True
    blocked_reason: str | None = None
    summary: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "role": self.role,
            "phase": self.phase,
            "context_chars": self.context_chars,
            "visible_sections": list(self.visible_sections),
            "allowed_actions": list(self.allowed_actions),
            "attempted_action": self.attempted_action,
            "action_allowed_by_role": self.action_allowed_by_role,
            "blocked_reason": self.blocked_reason,
            "summary": self.summary,
        }
```

Add:

```python
def role_context_for(role: str) -> RoleContext:
    context = next((item for item in ROLE_CONTEXTS if item.role == role), None)
    if context is None:
        raise ValueError(f"unknown role: {role}")
    return context


def action_allowed_for_role(role: str, action: str) -> bool:
    return action in role_context_for(role).allowed_actions


def build_isolation_evidence(
    strategy: str = "isolated-harness",
    executions: list[RoleExecution] | None = None,
    review_repairs: int = 0,
) -> dict[str, object]:
    contexts = build_role_contexts()
    executions = list(executions or [])
    return {
        "strategy": strategy,
        "roles": [context.to_dict() for context in contexts],
        "role_contexts": len(contexts),
        "isolated_state_keys": sum(len(context.state_keys) for context in contexts),
        "role_runs": len(executions),
        "role_blocked_actions": sum(1 for item in executions if not item.action_allowed_by_role),
        "review_repairs": review_repairs,
        "executions": [item.to_dict() for item in executions],
    }
```

Update `filter_state_for_role` to call `role_context_for(role)` instead of duplicating lookup.

Update `isolation_metadata()` to call:

```python
return build_isolation_evidence(strategy="isolated-harness")
```

- [ ] **Step 4: Run the focused tests**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_isolation -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```powershell
git add src/specgate/isolation.py tests/test_isolation.py
git commit -m "feat: add role isolation execution evidence"
```

---

### Task 2: Add Strategy and Metrics Plumbing

**Files:**

- Modify: `src/specgate/context.py`
- Modify: `src/specgate/config.py`
- Modify: `src/specgate/metrics.py`
- Test: `tests/test_config.py`
- Test: `tests/test_metrics.py`
- Test: `tests/test_context_strategy.py`

- [ ] **Step 1: Write failing tests for strategy acceptance and metrics**

Add to `tests/test_metrics.py`:

```python
def test_run_metrics_includes_role_level_fields(self):
    metrics = RunMetrics(
        role_runs=3,
        role_blocked_actions=1,
        review_repairs=1,
        planner_runs=1,
        implementer_runs=1,
        reviewer_runs=1,
    )

    data = metrics.to_dict()

    self.assertEqual(data["role_runs"], 3)
    self.assertEqual(data["role_blocked_actions"], 1)
    self.assertEqual(data["review_repairs"], 1)
    self.assertEqual(data["planner_runs"], 1)
    self.assertEqual(data["implementer_runs"], 1)
    self.assertEqual(data["reviewer_runs"], 1)
```

Add to `tests/test_config.py`:

```python
def test_load_workspace_config_accepts_multi_agent_isolated_strategy(self):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "specgate.toml").write_text(
            '[context]\nstrategy = "multi-agent-isolated"\n',
            encoding="utf-8",
        )

        config = load_workspace_config(root)

        self.assertEqual(config.context.strategy, "multi-agent-isolated")
```

Add to `tests/test_context_strategy.py`:

```python
def test_multi_agent_isolated_strategy_builds_context(self):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "TASK_SPEC.md").write_text("Build Search Dashboard", encoding="utf-8")
        (root / "CHECKLIST.md").write_text("- 必须包含 Search", encoding="utf-8")
        (root / "index.html").write_text("", encoding="utf-8")

        context, metadata = build_context_pack_with_metadata(
            root,
            latest_gate=None,
            runtime_feedback=[],
            strategy="multi-agent-isolated",
        )

        self.assertIn("multi-agent-isolated", context)
        self.assertIn("Role Isolation", context)
        self.assertIn("isolation", metadata)
```

- [ ] **Step 2: Run the focused failing tests**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_metrics tests.test_config tests.test_context_strategy -v
```

Expected: FAIL because `multi-agent-isolated` and role metrics do not exist yet.

- [ ] **Step 3: Add strategy constants and metrics fields**

In `src/specgate/context.py`, add `"multi-agent-isolated"` to `VALID_CONTEXT_STRATEGIES`.

In `src/specgate/config.py`, add `"multi-agent-isolated"` to `VALID_CONTEXT_STRATEGIES`.

In `src/specgate/metrics.py`, add fields to `RunMetrics`:

```python
role_runs: int = 0
role_blocked_actions: int = 0
review_repairs: int = 0
planner_runs: int = 0
implementer_runs: int = 0
reviewer_runs: int = 0
role_cycle_limit_reached: bool = False
```

Update `build_trust_summary`:

```python
if metrics.role_cycle_limit_reached:
    reasons.append("role_cycle_limit_reached")
```

Place this before returning failed status.

- [ ] **Step 4: Make context metadata use execution-ready evidence**

In `src/specgate/context.py`, treat `multi-agent-isolated` like `isolated-harness` for retrieval/compression:

```python
compression_like = strategy in {"compressed-rag", "isolated-harness", "multi-agent-isolated"}
if strategy in {"rag-select", "compressed-rag", "isolated-harness", "multi-agent-isolated"}:
    ...
```

Update the isolation section condition:

```python
if strategy in {"isolated-harness", "multi-agent-isolated"}:
    body_sections.append(("Role Isolation", _render_role_isolation()))
```

Update metadata:

```python
isolation = isolation_metadata() if strategy in {"isolated-harness", "multi-agent-isolated"} else None
```

- [ ] **Step 5: Run the focused tests**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_metrics tests.test_config tests.test_context_strategy -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

Run:

```powershell
git add src/specgate/context.py src/specgate/config.py src/specgate/metrics.py tests/test_config.py tests/test_metrics.py tests/test_context_strategy.py
git commit -m "feat: add multi-agent isolation strategy plumbing"
```

---

### Task 3: Build Role-Specific Context Rendering

**Files:**

- Create: `src/specgate/multi_agent.py`
- Modify: `src/specgate/context.py`
- Test: `tests/test_context_strategy.py`

- [ ] **Step 1: Write failing tests for role-specific context**

Add to `tests/test_context_strategy.py`:

```python
from specgate.context import build_role_context_pack_with_metadata


def test_implementer_role_context_contains_plan(self):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "TASK_SPEC.md").write_text("Build Search Dashboard", encoding="utf-8")
        (root / "CHECKLIST.md").write_text("- 必须包含 Search", encoding="utf-8")
        (root / "index.html").write_text("", encoding="utf-8")

        context, metadata = build_role_context_pack_with_metadata(
            root,
            role="implementer",
            shared_state={"plan": "Write index.html with a search input"},
            latest_gate=None,
            runtime_feedback=[],
            strategy="multi-agent-isolated",
        )

        self.assertIn("Current Role", context)
        self.assertIn("implementer", context)
        self.assertIn("Plan", context)
        self.assertIn("Write index.html with a search input", context)
        self.assertEqual(metadata["role"], "implementer")


def test_reviewer_role_context_hides_plan_raw_section(self):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "TASK_SPEC.md").write_text("Build Search Dashboard", encoding="utf-8")
        (root / "CHECKLIST.md").write_text("- 必须包含 Search", encoding="utf-8")
        (root / "index.html").write_text("<html>Search</html>", encoding="utf-8")

        context, metadata = build_role_context_pack_with_metadata(
            root,
            role="reviewer",
            shared_state={"plan": "private implementer plan", "review_notes": "check search"},
            latest_gate=None,
            runtime_feedback=[{"type": "tool_result", "message": "wrote file"}],
            strategy="multi-agent-isolated",
        )

        self.assertIn("Current Role", context)
        self.assertIn("reviewer", context)
        self.assertIn("Trace Summary", context)
        self.assertNotIn("private implementer plan", context)
        self.assertEqual(metadata["role"], "reviewer")
```

- [ ] **Step 2: Run the focused failing tests**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_context_strategy -v
```

Expected: FAIL because `build_role_context_pack_with_metadata` does not exist.

- [ ] **Step 3: Add role phase constants**

Create `src/specgate/multi_agent.py` with:

```python
from __future__ import annotations

from dataclasses import dataclass, field

from specgate.isolation import RoleExecution


ROLE_SEQUENCE = ("planner", "implementer", "reviewer")


@dataclass
class MultiAgentState:
    plan: str = ""
    review_notes: str = ""
    repair_requested: bool = False
    review_repairs: int = 0
    executions: list[RoleExecution] = field(default_factory=list)

    def to_shared_state(self) -> dict[str, object]:
        return {
            "plan": self.plan,
            "review_notes": self.review_notes,
            "repair_requested": self.repair_requested,
            "review_repairs": self.review_repairs,
        }
```

- [ ] **Step 4: Add role-specific context builder**

In `src/specgate/context.py`, add:

```python
from specgate.isolation import role_context_for
```

Add helper:

```python
def _render_trace_summary(events: list[dict] | None) -> str:
    if not events:
        return "No trace summary yet."
    selected = events[-5:]
    lines = []
    for event in selected:
        payload = json.dumps(_compress_payload(redact(event), 260), ensure_ascii=False, sort_keys=True)
        lines.append(f"- {payload}")
    return "\n".join(lines)
```

Add public function:

```python
def build_role_context_pack_with_metadata(
    root: Path,
    role: str,
    shared_state: dict[str, object],
    latest_gate: GateResult | None,
    runtime_feedback: list[dict] | None = None,
    strategy: str = "multi-agent-isolated",
    policy: WorkspacePolicy | None = None,
) -> tuple[str, dict]:
    role_context = role_context_for(role)
    base_context, metadata = build_context_pack_with_metadata(
        root,
        latest_gate,
        runtime_feedback,
        strategy=strategy,
        policy=policy,
    )
    sections = [
        "## Current Role",
        f"role: {role_context.role}",
        "allowed_actions: " + ", ".join(role_context.allowed_actions),
        "visible_sections: " + ", ".join(role_context.visible_sections),
    ]
    if role == "implementer":
        sections.extend(["", "## Plan", str(redact(str(shared_state.get("plan", ""))))])
    if role == "reviewer":
        sections.extend(["", "## Trace Summary", _render_trace_summary(runtime_feedback)])
        sections.extend(["", "## Review Notes", str(redact(str(shared_state.get("review_notes", ""))))])
    context = base_context + "\n\n" + "\n".join(sections)
    metadata = dict(metadata)
    metadata["role"] = role
    metadata["role_allowed_actions"] = list(role_context.allowed_actions)
    metadata["role_visible_sections"] = list(role_context.visible_sections)
    return context, metadata
```

- [ ] **Step 5: Run the focused tests**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_context_strategy -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

Run:

```powershell
git add src/specgate/multi_agent.py src/specgate/context.py tests/test_context_strategy.py
git commit -m "feat: build role-specific context packs"
```

---

### Task 4: Extract Runner Governance Helpers Without Behavior Change

**Files:**

- Modify: `src/specgate/runner.py`
- Test: `tests/test_runner.py`

- [ ] **Step 1: Run current runner regression tests before refactor**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_runner -v
```

Expected: PASS before editing. If it fails, stop and inspect the failing behavior before refactoring.

- [ ] **Step 2: Extract queue reset and artifact cleanup helper**

In `src/specgate/runner.py`, add instance methods near `__init__`:

```python
def _reset_run_artifacts(self) -> None:
    for name in ("retrieval.json", "compression.json", "isolation.json"):
        path = self.run_dir / name
        if path.exists():
            path.unlink()


def _reset_approval_queue(self) -> None:
    queue_path = approval_queue_path(self.root)
    if queue_path.exists():
        queue_path.unlink()
```

Replace the repeated cleanup in `__init__` with `self._reset_run_artifacts()`.

- [ ] **Step 3: Extract gate helper**

Move the nested `run_gate(step)` logic from `_run_loop` into:

```python
def _run_gate_with_feedback(
    self,
    step: int,
    metrics: RunMetrics,
    runtime_feedback: list[dict],
) -> tuple[GateResult, RunMetrics]:
    ...
```

Keep the current behavior exactly:

- If `index.html` is not readable, create skipped GateResult.
- Increment `gate_runs`.
- Increment `gate_failures` on failure.
- Append redacted runtime feedback.
- Append `gate_result` trace event.

Replace nested calls with:

```python
latest_gate, metrics = self._run_gate_with_feedback(step, metrics, runtime_feedback)
```

- [ ] **Step 4: Extract finish helper**

Move nested `finish_result` into:

```python
def _finish_result(
    self,
    step: int,
    final_gate: GateResult,
    metrics: RunMetrics,
    permission_decisions: list[PermissionDecision],
) -> RunResult:
    ...
```

Preserve trust summary, trace `run_summary`, `RunResult`, and `append_memory`.

- [ ] **Step 5: Extract permission and tool feedback helpers**

Move nested `record_tool_feedback` into:

```python
def _record_tool_feedback(
    self,
    runtime_feedback: list[dict],
    step: int,
    action_name: str,
    ok: bool,
    blocked: bool,
    message: str,
    data: dict,
) -> None:
    ...
```

Move nested `record_permission_decision` into:

```python
def _record_permission_decision(
    self,
    permission_decisions: list[PermissionDecision],
    step: int,
    action_name: str,
    action_path: str | None,
    ok: bool,
    blocked: bool,
    message: str,
) -> None:
    ...
```

Keep the existing profile and rule family behavior.

- [ ] **Step 6: Extract metadata recorders**

Move nested `record_retrieval`, `record_compression`, and `record_isolation` into methods:

```python
def _record_retrieval(self, metrics: RunMetrics, metadata: dict | None) -> RunMetrics:
    ...

def _record_compression(self, metrics: RunMetrics, metadata: dict | None) -> RunMetrics:
    ...

def _record_isolation(self, metrics: RunMetrics, metadata: dict | None) -> RunMetrics:
    ...
```

Each method returns the updated `RunMetrics`.

- [ ] **Step 7: Run runner regression tests**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_runner -v
```

Expected: PASS. This task must not change behavior.

- [ ] **Step 8: Commit**

Run:

```powershell
git add src/specgate/runner.py
git commit -m "refactor: extract reusable runner governance helpers"
```

---

### Task 5: Implement Multi-Agent Success Path

**Files:**

- Modify: `src/specgate/multi_agent.py`
- Modify: `src/specgate/runner.py`
- Test: `tests/test_runner.py`

- [ ] **Step 1: Write failing success-path runner test**

Add to `tests/test_runner.py`:

```python
def test_multi_agent_isolated_runs_planner_implementer_reviewer_in_order(self):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "TASK_SPEC.md").write_text("Build a page with Search Details", encoding="utf-8")
        (root / "CHECKLIST.md").write_text("- 必须包含 Search\n- 必须包含 Details", encoding="utf-8")
        (root / "index.html").write_text("", encoding="utf-8")
        policy = WorkspacePolicy(
            root,
            {"read_file", "list_files", "write_file", "replace_file", "finish"},
            {"TASK_SPEC.md", "CHECKLIST.md", "index.html"},
            {"index.html"},
        )
        llm = MockLLM(
            [
                {"schema_version": "1", "action": "finish", "args": {"summary": "Plan: write Search Details page"}},
                {
                    "schema_version": "1",
                    "action": "replace_file",
                    "args": {
                        "path": "index.html",
                        "content": (
                            '<!doctype html><html><head><meta name="viewport" content="width=device-width">'
                            "<title>Search</title></head><body><input type=\"search\">Search Details</body></html>"
                        ),
                    },
                },
                {"schema_version": "1", "action": "finish", "args": {"summary": "review complete"}},
            ]
        )

        result = AgentRunner(
            root,
            llm,
            policy,
            max_steps=5,
            context_strategy="multi-agent-isolated",
        ).run()

        self.assertTrue(result.passed)
        self.assertEqual(result.metrics.role_runs, 3)
        self.assertEqual(result.metrics.planner_runs, 1)
        self.assertEqual(result.metrics.implementer_runs, 1)
        self.assertEqual(result.metrics.reviewer_runs, 1)
        self.assertIn("Plan: write Search Details page", llm.contexts[1])
        trace_text = (root / "runs" / "latest" / "trace.jsonl").read_text(encoding="utf-8")
        self.assertLess(trace_text.index('"role": "planner"'), trace_text.index('"role": "implementer"'))
        self.assertLess(trace_text.index('"role": "implementer"'), trace_text.index('"role": "reviewer"'))
```

- [ ] **Step 2: Run the focused failing test**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_runner.RunnerTests.test_multi_agent_isolated_runs_planner_implementer_reviewer_in_order -v
```

Expected: FAIL because `multi-agent-isolated` still uses the normal loop.

- [ ] **Step 3: Add coordinator phase helpers**

In `src/specgate/multi_agent.py`, add:

```python
def phase_for_role(role: str) -> str:
    phases = {
        "planner": "plan",
        "implementer": "implement",
        "reviewer": "review",
    }
    if role not in phases:
        raise ValueError(f"unknown role: {role}")
    return phases[role]


def summary_requests_repair(summary: str) -> bool:
    lowered = summary.lower()
    return "request_repair" in lowered or "repair requested" in lowered
```

- [ ] **Step 4: Route runner to multi-agent loop**

In `src/specgate/runner.py`, import:

```python
from specgate.context import build_context_pack_with_metadata, build_role_context_pack_with_metadata
from specgate.isolation import RoleExecution, action_allowed_for_role, build_isolation_evidence, role_context_for
from specgate.multi_agent import MultiAgentState, ROLE_SEQUENCE, phase_for_role, summary_requests_repair
```

Update `run()`:

```python
def run(self) -> RunResult:
    if self.context_strategy == "multi-agent-isolated":
        return self._run_multi_agent_loop(reset_queue=True)
    return self._run_loop(reset_queue=True)
```

- [ ] **Step 5: Implement minimal `_run_multi_agent_loop` success path**

Add method:

```python
def _run_multi_agent_loop(self, reset_queue: bool) -> RunResult:
    if reset_queue:
        self._reset_approval_queue()

    runtime_feedback: list[dict] = []
    permission_decisions: list[PermissionDecision] = []
    metrics = RunMetrics()
    latest_gate: GateResult | None = None
    state = MultiAgentState()

    for step, role in enumerate(ROLE_SEQUENCE, start=1):
        role_context = role_context_for(role)
        self.trace.append("role_started", {"step": step, "role": role, "phase": phase_for_role(role)})
        context, context_metadata = build_role_context_pack_with_metadata(
            self.root,
            role=role,
            shared_state=state.to_shared_state(),
            latest_gate=latest_gate,
            runtime_feedback=runtime_feedback,
            strategy=self.context_strategy,
            policy=self.policy,
        )
        metrics = self._record_retrieval(metrics, context_metadata)
        metrics = self._record_compression(metrics, context_metadata)
        context_chars = len(context)
        metrics = replace(
            metrics,
            steps=step,
            context_chars_max=max(metrics.context_chars_max, context_chars),
            role_runs=metrics.role_runs + 1,
            planner_runs=metrics.planner_runs + (1 if role == "planner" else 0),
            implementer_runs=metrics.implementer_runs + (1 if role == "implementer" else 0),
            reviewer_runs=metrics.reviewer_runs + (1 if role == "reviewer" else 0),
        )
        self.trace.append(
            "role_context_built",
            {"step": step, "role": role, "context_chars": context_chars},
        )
        raw = self.llm.complete(context)
        metrics = replace(metrics, llm_calls=metrics.llm_calls + 1)
        self.trace.append("llm_response", {"step": step, "role": role, "text": raw})

        try:
            action = parse_action(raw)
        except ActionParseError as exc:
            metrics = replace(metrics, parse_errors=metrics.parse_errors + 1)
            event = {"step": step, "role": role, "type": "parse_error", "error": str(exc)}
            runtime_feedback.append(redact(event))
            self.trace.append("parse_error", event)
            continue

        summary = str(action.args.get("summary", "")) if isinstance(action.args.get("summary", ""), str) else ""
        allowed_by_role = action_allowed_for_role(role, action.action)
        execution = RoleExecution(
            role=role,
            phase=phase_for_role(role),
            context_chars=context_chars,
            visible_sections=role_context.visible_sections,
            allowed_actions=role_context.allowed_actions,
            attempted_action=action.action,
            action_allowed_by_role=allowed_by_role,
            blocked_reason=None if allowed_by_role else f"role {role} cannot perform {action.action}",
            summary=summary or None,
        )
        state.executions.append(execution)
        self.trace.append("role_action", execution.to_dict())

        if not allowed_by_role:
            metrics = replace(metrics, role_blocked_actions=metrics.role_blocked_actions + 1)
            self.trace.append("role_action_blocked", execution.to_dict())
            runtime_feedback.append(redact({"step": step, "type": "role_action_blocked", **execution.to_dict()}))
            continue

        if role == "planner" and action.action == "finish":
            state.plan = summary
            self.trace.append("role_finished", execution.to_dict())
            continue

        if role == "reviewer" and action.action == "finish":
            state.review_notes = summary
            self.trace.append("role_finished", execution.to_dict())
            if latest_gate is None:
                latest_gate, metrics = self._run_gate_with_feedback(step, metrics, runtime_feedback)
            evidence = build_isolation_evidence(
                strategy=self.context_strategy,
                executions=state.executions,
                review_repairs=state.review_repairs,
            )
            (self.run_dir / "isolation.json").write_text(
                json.dumps(redact(evidence), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            metrics = self._record_isolation(metrics, {"isolation": evidence})
            return self._finish_result(step, latest_gate, metrics, permission_decisions)

        if role == "implementer":
            latest_gate, metrics = self._execute_agent_action(
                step,
                action,
                metrics,
                runtime_feedback,
                permission_decisions,
                latest_gate,
            )
            self.trace.append("role_finished", execution.to_dict())

    if latest_gate is None:
        latest_gate, metrics = self._run_gate_with_feedback(len(ROLE_SEQUENCE), metrics, runtime_feedback)
    evidence = build_isolation_evidence(
        strategy=self.context_strategy,
        executions=state.executions,
        review_repairs=state.review_repairs,
    )
    (self.run_dir / "isolation.json").write_text(
        json.dumps(redact(evidence), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    metrics = self._record_isolation(metrics, {"isolation": evidence})
    metrics = replace(metrics, max_steps_reached=True)
    return self._finish_result(len(ROLE_SEQUENCE), latest_gate, metrics, permission_decisions)
```

- [ ] **Step 6: Add `_execute_agent_action` helper by reusing existing normal-loop action execution**

Add method to `AgentRunner`:

```python
def _execute_agent_action(
    self,
    step: int,
    action,
    metrics: RunMetrics,
    runtime_feedback: list[dict],
    permission_decisions: list[PermissionDecision],
    latest_gate: GateResult | None,
) -> tuple[GateResult | None, RunMetrics]:
    action_path_value = action.args.get("path")
    action_path = action_path_value if isinstance(action_path_value, str) else None
    risk = classify_action_risk(action, self.policy, self.governance_config)
    queue_path = approval_queue_path(self.root)
    if risk.level == "review" and self.governance_profile == "review":
        queue = ApprovalQueue.read(queue_path)
        approval = PendingApproval(
            id=_unique_approval_id(queue, step),
            step=step,
            action=action.action,
            path=action_path,
            risk_level=risk.level,
            reason=risk.reason,
            profile=self.governance_profile,
            arguments_preview=preview_args(action.args),
            action_payload={
                "schema_version": action.schema_version,
                "action": action.action,
                "args": action.args,
            },
            target_state=capture_target_state(self.root, action_path),
        )
        queue.append(approval).write(queue_path)
        self._record_permission_decision(
            permission_decisions,
            step,
            action.action,
            action_path,
            ok=False,
            blocked=False,
            message=risk.reason,
        )
        metrics = replace(
            metrics,
            approval_requests=metrics.approval_requests + 1,
            pending_approvals=metrics.pending_approvals + 1,
        )
        event = {"step": step, "type": "approval_requested", "approval": approval.to_dict()}
        runtime_feedback.append(redact(event))
        self.trace.append("approval_requested", redact(event))
        return latest_gate, metrics

    if risk.level in {"review", "blocked"}:
        metrics = replace(metrics, blocked_actions=metrics.blocked_actions + 1)
        self._record_permission_decision(
            permission_decisions,
            step,
            action.action,
            action_path,
            ok=False,
            blocked=True,
            message=risk.reason,
        )
        self._record_tool_feedback(
            runtime_feedback,
            step,
            action.action,
            ok=False,
            blocked=True,
            message=risk.reason,
            data={"risk": risk.to_dict()},
        )
        return latest_gate, metrics

    tool_result = self.dispatcher.dispatch(action)
    metrics = replace(
        metrics,
        tool_calls=metrics.tool_calls + 1,
        successful_tool_calls=metrics.successful_tool_calls + (1 if tool_result.ok else 0),
        blocked_actions=metrics.blocked_actions + (1 if tool_result.blocked else 0),
        finish_actions=metrics.finish_actions + (1 if action.action == "finish" else 0),
    )
    self._record_permission_decision(
        permission_decisions,
        step,
        action.action,
        action_path,
        ok=tool_result.ok,
        blocked=tool_result.blocked,
        message=tool_result.message,
    )
    runtime_feedback.append(
        redact(
            {
                "step": step,
                "type": "tool_result",
                "action": tool_result.action,
                "ok": tool_result.ok,
                "blocked": tool_result.blocked,
                "message": tool_result.message,
                "data": tool_result.data,
            }
        )
    )
    self.trace.append("tool_result", {"step": step, "result": tool_result.__dict__})
    if action.action in {"write_file", "replace_file"} and not tool_result.blocked:
        latest_gate, metrics = self._run_gate_with_feedback(step, metrics, runtime_feedback)
    return latest_gate, metrics
```

After this helper exists, the normal `_run_loop` can continue using its existing body or can call this helper. If the normal loop still uses its existing body, run the regression tests to ensure no divergence affects current behavior.

- [ ] **Step 7: Run the success-path test**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_runner.RunnerTests.test_multi_agent_isolated_runs_planner_implementer_reviewer_in_order -v
```

Expected: PASS.

- [ ] **Step 8: Run runner regression tests**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_runner -v
```

Expected: PASS.

- [ ] **Step 9: Commit**

Run:

```powershell
git add src/specgate/multi_agent.py src/specgate/runner.py tests/test_runner.py
git commit -m "feat: run planner implementer reviewer in isolation mode"
```

---

### Task 6: Enforce Role Blocks, Policy Blocks, and HITL Preservation

**Files:**

- Modify: `src/specgate/runner.py`
- Test: `tests/test_runner.py`

- [ ] **Step 1: Write failing tests for role and policy boundaries**

Add to `tests/test_runner.py`:

```python
def test_multi_agent_blocks_planner_write_before_tool_dispatch(self):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "TASK_SPEC.md").write_text("Build page", encoding="utf-8")
        (root / "CHECKLIST.md").write_text("", encoding="utf-8")
        policy = WorkspacePolicy(root, {"write_file", "finish"}, {"TASK_SPEC.md", "CHECKLIST.md", "index.html"}, {"index.html"})
        llm = MockLLM(
            [
                {
                    "schema_version": "1",
                    "action": "write_file",
                    "args": {"path": "index.html", "content": "bad"},
                },
                {"schema_version": "1", "action": "finish", "args": {"summary": "no-op"}},
                {"schema_version": "1", "action": "finish", "args": {"summary": "review"}},
            ]
        )

        result = AgentRunner(root, llm, policy, max_steps=5, context_strategy="multi-agent-isolated").run()

        self.assertFalse((root / "index.html").exists())
        self.assertEqual(result.metrics.role_blocked_actions, 1)
        self.assertEqual(result.metrics.tool_calls, 1)
        trace_text = (root / "runs" / "latest" / "trace.jsonl").read_text(encoding="utf-8")
        self.assertIn("role_action_blocked", trace_text)
        self.assertIn("role planner cannot perform write_file", trace_text)


def test_multi_agent_blocks_reviewer_write_before_tool_dispatch(self):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "TASK_SPEC.md").write_text("Build page", encoding="utf-8")
        (root / "CHECKLIST.md").write_text("", encoding="utf-8")
        (root / "index.html").write_text("", encoding="utf-8")
        policy = WorkspacePolicy(root, {"write_file", "replace_file", "finish"}, {"TASK_SPEC.md", "CHECKLIST.md", "index.html"}, {"index.html"})
        llm = MockLLM(
            [
                {"schema_version": "1", "action": "finish", "args": {"summary": "plan"}},
                {
                    "schema_version": "1",
                    "action": "replace_file",
                    "args": {"path": "index.html", "content": '<html><body><input type="search">Task</body></html>'},
                },
                {
                    "schema_version": "1",
                    "action": "write_file",
                    "args": {"path": "index.html", "content": "reviewer overwrite"},
                },
            ]
        )

        result = AgentRunner(root, llm, policy, max_steps=5, context_strategy="multi-agent-isolated").run()

        self.assertNotIn("reviewer overwrite", (root / "index.html").read_text(encoding="utf-8"))
        self.assertEqual(result.metrics.role_blocked_actions, 1)
        trace_text = (root / "runs" / "latest" / "trace.jsonl").read_text(encoding="utf-8")
        self.assertIn("role reviewer cannot perform write_file", trace_text)


def test_multi_agent_implementer_write_still_obeys_workspace_policy(self):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "TASK_SPEC.md").write_text("Build page", encoding="utf-8")
        (root / "CHECKLIST.md").write_text("", encoding="utf-8")
        policy = WorkspacePolicy(root, {"write_file", "finish"}, {"TASK_SPEC.md", "CHECKLIST.md", "index.html"}, set())
        llm = MockLLM(
            [
                {"schema_version": "1", "action": "finish", "args": {"summary": "plan"}},
                {
                    "schema_version": "1",
                    "action": "write_file",
                    "args": {"path": "index.html", "content": "blocked by policy"},
                },
                {"schema_version": "1", "action": "finish", "args": {"summary": "review"}},
            ]
        )

        result = AgentRunner(root, llm, policy, max_steps=5, context_strategy="multi-agent-isolated").run()

        self.assertFalse((root / "index.html").exists())
        self.assertGreaterEqual(result.metrics.blocked_actions, 1)
        self.assertEqual(result.metrics.role_blocked_actions, 0)
```

- [ ] **Step 2: Write failing HITL preservation test**

Add:

```python
def test_multi_agent_implementer_review_action_creates_pending_approval(self):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "TASK_SPEC.md").write_text("Build page", encoding="utf-8")
        (root / "CHECKLIST.md").write_text("", encoding="utf-8")
        (root / "index.html").write_text("old", encoding="utf-8")
        policy = WorkspacePolicy(root, {"replace_file", "finish"}, {"TASK_SPEC.md", "CHECKLIST.md", "index.html"}, {"index.html"})
        governance = GovernanceConfig(
            profile="review",
            review_actions={"replace_file"},
            review_paths={"index.html"},
        )
        llm = MockLLM(
            [
                {"schema_version": "1", "action": "finish", "args": {"summary": "plan"}},
                {
                    "schema_version": "1",
                    "action": "replace_file",
                    "args": {"path": "index.html", "content": "needs approval"},
                },
                {"schema_version": "1", "action": "finish", "args": {"summary": "review"}},
            ]
        )

        result = AgentRunner(
            root,
            llm,
            policy,
            max_steps=5,
            context_strategy="multi-agent-isolated",
            governance_config=governance,
        ).run()

        self.assertEqual((root / "index.html").read_text(encoding="utf-8"), "old")
        self.assertEqual(result.metrics.approval_requests, 1)
        self.assertEqual(result.metrics.pending_approvals, 1)
        self.assertTrue(approval_queue_path(root).exists())
```

- [ ] **Step 3: Run the focused failing tests**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_runner.RunnerTests.test_multi_agent_blocks_planner_write_before_tool_dispatch tests.test_runner.RunnerTests.test_multi_agent_blocks_reviewer_write_before_tool_dispatch tests.test_runner.RunnerTests.test_multi_agent_implementer_write_still_obeys_workspace_policy tests.test_runner.RunnerTests.test_multi_agent_implementer_review_action_creates_pending_approval -v
```

Expected: FAIL until role block and action execution behavior is complete.

- [ ] **Step 4: Complete role block metric and trace behavior**

In `_run_multi_agent_loop`, ensure role block branch:

```python
if not allowed_by_role:
    metrics = replace(
        metrics,
        role_blocked_actions=metrics.role_blocked_actions + 1,
    )
    blocked_event = execution.to_dict()
    self.trace.append("role_action_blocked", blocked_event)
    runtime_feedback.append(redact({"step": step, "type": "role_action_blocked", **blocked_event}))
    continue
```

This branch must not call `_execute_agent_action`.

- [ ] **Step 5: Verify `_execute_agent_action` handles review and blocked risks**

Confirm `_execute_agent_action` uses `classify_action_risk` before dispatch and creates `PendingApproval` when:

```python
risk.level == "review" and self.governance_profile == "review"
```

Confirm blocked/review risks outside review profile record `blocked_actions`.

- [ ] **Step 6: Run focused tests**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_runner.RunnerTests.test_multi_agent_blocks_planner_write_before_tool_dispatch tests.test_runner.RunnerTests.test_multi_agent_blocks_reviewer_write_before_tool_dispatch tests.test_runner.RunnerTests.test_multi_agent_implementer_write_still_obeys_workspace_policy tests.test_runner.RunnerTests.test_multi_agent_implementer_review_action_creates_pending_approval -v
```

Expected: PASS.

- [ ] **Step 7: Run all runner tests**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_runner -v
```

Expected: PASS.

- [ ] **Step 8: Commit**

Run:

```powershell
git add src/specgate/runner.py tests/test_runner.py
git commit -m "feat: enforce role boundaries in multi-agent runs"
```

---

### Task 7: Add Reviewer Repair Cycle

**Files:**

- Modify: `src/specgate/runner.py`
- Modify: `src/specgate/multi_agent.py`
- Test: `tests/test_runner.py`

- [ ] **Step 1: Write failing repair-cycle test**

Add to `tests/test_runner.py`:

```python
def test_multi_agent_reviewer_can_request_one_repair_cycle(self):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "TASK_SPEC.md").write_text("Build page with Search and Details", encoding="utf-8")
        (root / "CHECKLIST.md").write_text("- 必须包含 Search\n- 必须包含 Details", encoding="utf-8")
        (root / "index.html").write_text("", encoding="utf-8")
        policy = WorkspacePolicy(
            root,
            {"replace_file", "finish"},
            {"TASK_SPEC.md", "CHECKLIST.md", "index.html"},
            {"index.html"},
        )
        llm = MockLLM(
            [
                {"schema_version": "1", "action": "finish", "args": {"summary": "plan"}},
                {
                    "schema_version": "1",
                    "action": "replace_file",
                    "args": {"path": "index.html", "content": '<html><body><input type="search">Search</body></html>'},
                },
                {"schema_version": "1", "action": "finish", "args": {"summary": "request_repair: missing Details"}},
                {
                    "schema_version": "1",
                    "action": "replace_file",
                    "args": {
                        "path": "index.html",
                        "content": (
                            '<!doctype html><html><head><meta name="viewport" content="width=device-width">'
                            '<title>Search</title></head><body><input type="search">Search Details</body></html>'
                        ),
                    },
                },
                {"schema_version": "1", "action": "finish", "args": {"summary": "review complete"}},
            ]
        )

        result = AgentRunner(root, llm, policy, max_steps=6, context_strategy="multi-agent-isolated").run()

        self.assertTrue(result.passed)
        self.assertEqual(result.metrics.review_repairs, 1)
        self.assertEqual(result.metrics.implementer_runs, 2)
        self.assertEqual(result.metrics.reviewer_runs, 2)
        trace_text = (root / "runs" / "latest" / "trace.jsonl").read_text(encoding="utf-8")
        self.assertIn("role_repair_requested", trace_text)
```

Add cycle-limit test:

```python
def test_multi_agent_repair_cycle_limit_fails_closed(self):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "TASK_SPEC.md").write_text("Build page with Search and Details", encoding="utf-8")
        (root / "CHECKLIST.md").write_text("- 必须包含 Search\n- 必须包含 Details", encoding="utf-8")
        (root / "index.html").write_text("", encoding="utf-8")
        policy = WorkspacePolicy(
            root,
            {"replace_file", "finish"},
            {"TASK_SPEC.md", "CHECKLIST.md", "index.html"},
            {"index.html"},
        )
        llm = MockLLM(
            [
                {"schema_version": "1", "action": "finish", "args": {"summary": "plan"}},
                {"schema_version": "1", "action": "replace_file", "args": {"path": "index.html", "content": "<html>Search</html>"}},
                {"schema_version": "1", "action": "finish", "args": {"summary": "request_repair: still missing Details"}},
                {"schema_version": "1", "action": "replace_file", "args": {"path": "index.html", "content": "<html>Search</html>"}},
                {"schema_version": "1", "action": "finish", "args": {"summary": "request_repair: still missing Details"}},
            ]
        )

        result = AgentRunner(root, llm, policy, max_steps=6, context_strategy="multi-agent-isolated").run()

        self.assertFalse(result.passed)
        self.assertTrue(result.metrics.role_cycle_limit_reached)
        self.assertIn("role_cycle_limit_reached", result.trust.reasons)
```

- [ ] **Step 2: Run the focused failing tests**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_runner.RunnerTests.test_multi_agent_reviewer_can_request_one_repair_cycle tests.test_runner.RunnerTests.test_multi_agent_repair_cycle_limit_fails_closed -v
```

Expected: FAIL because repair loop is not implemented.

- [ ] **Step 3: Replace fixed role loop with cycle-aware loop**

In `_run_multi_agent_loop`, use this structure:

```python
step = 0
max_role_cycles = 2

step += 1
latest_gate, metrics = self._run_role_once("planner", step, state, metrics, runtime_feedback, permission_decisions, latest_gate)

while True:
    step += 1
    latest_gate, metrics = self._run_role_once("implementer", step, state, metrics, runtime_feedback, permission_decisions, latest_gate)
    step += 1
    latest_gate, metrics = self._run_role_once("reviewer", step, state, metrics, runtime_feedback, permission_decisions, latest_gate)
    if not state.repair_requested:
        break
    if state.review_repairs >= max_role_cycles - 1:
        metrics = replace(metrics, role_cycle_limit_reached=True, max_steps_reached=True)
        self.trace.append("role_cycle_limit_reached", {"review_repairs": state.review_repairs})
        break
    state.review_repairs += 1
    metrics = replace(metrics, review_repairs=state.review_repairs)
    self.trace.append("role_repair_requested", {"review_repairs": state.review_repairs, "review_notes": redact(state.review_notes)})
    state.repair_requested = False
```

If this makes `_run_multi_agent_loop` too large, introduce `_run_role_once(...)` inside `AgentRunner` and move one role execution there. Keep all writes through `_execute_agent_action`.

- [ ] **Step 4: Set reviewer repair flag**

When reviewer finishes:

```python
state.review_notes = summary
state.repair_requested = summary_requests_repair(summary)
```

- [ ] **Step 5: Run focused tests**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_runner.RunnerTests.test_multi_agent_reviewer_can_request_one_repair_cycle tests.test_runner.RunnerTests.test_multi_agent_repair_cycle_limit_fails_closed -v
```

Expected: PASS.

- [ ] **Step 6: Run all runner tests**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_runner -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

Run:

```powershell
git add src/specgate/runner.py src/specgate/multi_agent.py tests/test_runner.py
git commit -m "feat: add reviewer repair cycle"
```

---

### Task 8: Surface Role Execution Evidence in Report

**Files:**

- Modify: `src/specgate/report.py`
- Test: `tests/test_report.py`

- [ ] **Step 1: Write failing report tests**

Add to `tests/test_report.py`:

```python
def test_generate_report_includes_role_execution_evidence(self):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        run_dir = root / "runs" / "latest"
        run_dir.mkdir(parents=True)
        (root / "index.html").write_text("<html></html>", encoding="utf-8")
        (run_dir / "trace.jsonl").write_text("", encoding="utf-8")
        (run_dir / "isolation.json").write_text(
            json.dumps(
                {
                    "strategy": "multi-agent-isolated",
                    "role_runs": 1,
                    "role_blocked_actions": 1,
                    "review_repairs": 0,
                    "executions": [
                        {
                            "role": "planner",
                            "phase": "plan",
                            "context_chars": 100,
                            "visible_sections": ["Task"],
                            "allowed_actions": ["finish"],
                            "attempted_action": "write_file",
                            "action_allowed_by_role": False,
                            "blocked_reason": "role planner cannot perform write_file",
                            "summary": "<script>alert(1)</script>",
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        html = generate_report(root, RunResult(False, 1, None))

        self.assertIn("Role Execution Evidence", html)
        self.assertIn("planner", html)
        self.assertIn("write_file", html)
        self.assertIn("role planner cannot perform write_file", html)
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)
```

- [ ] **Step 2: Run the focused failing test**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_report.ReportTests.test_generate_report_includes_role_execution_evidence -v
```

Expected: FAIL because report only renders role definitions.

- [ ] **Step 3: Update report rendering**

In `src/specgate/report.py`, update `_render_role_isolation_evidence`:

```python
executions = data.get("executions", [])
if isinstance(executions, list) and executions:
    rows = []
    for execution in executions:
        if not isinstance(execution, dict):
            continue
        rows.append(
            "<tr>"
            f"<td>{escape(_safe_text(execution.get('role')))}</td>"
            f"<td>{escape(_safe_text(execution.get('phase')))}</td>"
            f"<td>{escape(_safe_text(execution.get('context_chars')))}</td>"
            f"<td>{escape(_safe_text(execution.get('attempted_action')))}</td>"
            f"<td>{escape(_safe_text(execution.get('action_allowed_by_role')))}</td>"
            f"<td>{escape(_safe_text(redact(_safe_text(execution.get('blocked_reason')))))}</td>"
            f"<td>{escape(_safe_text(redact(_safe_text(execution.get('summary')))))}</td>"
            "</tr>"
        )
    if rows:
        return (
            "<h2>Role Execution Evidence</h2>"
            "<table><thead><tr>"
            "<th>Role</th><th>Phase</th><th>Context Chars</th><th>Action</th>"
            "<th>Allowed By Role</th><th>Blocked Reason</th><th>Summary</th>"
            "</tr></thead><tbody>"
            + "".join(rows)
            + "</tbody></table>"
        )
```

Leave the existing role definition rendering as the fallback for old `isolated-harness` evidence.

- [ ] **Step 4: Run focused report tests**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_report -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```powershell
git add src/specgate/report.py tests/test_report.py
git commit -m "feat: render multi-agent role execution evidence"
```

---

### Task 9: Add Eval Case and Role Metrics to Eval/Benchmark

**Files:**

- Create: `examples/eval_cases/true-multi-agent-isolation/TASK_SPEC.md`
- Create: `examples/eval_cases/true-multi-agent-isolation/CHECKLIST.md`
- Create: `examples/eval_cases/true-multi-agent-isolation/index.html`
- Create: `examples/eval_cases/true-multi-agent-isolation/specgate.toml`
- Create: `examples/eval_cases/true-multi-agent-isolation/case.json`
- Modify: `src/specgate/eval_runner.py`
- Modify: `src/specgate/benchmark.py`
- Test: `tests/test_eval_runner.py`
- Test: `tests/test_benchmark.py`

- [ ] **Step 1: Write failing eval metric test**

Add to `tests/test_eval_runner.py`:

```python
def test_run_eval_suite_records_multi_agent_role_metrics(self):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        case = root / "case-a"
        case.mkdir()
        (case / "TASK_SPEC.md").write_text("Build Search Details", encoding="utf-8")
        (case / "CHECKLIST.md").write_text("- 必须包含 Search\n- 必须包含 Details", encoding="utf-8")
        (case / "index.html").write_text("", encoding="utf-8")
        (case / "case.json").write_text(
            json.dumps(
                {
                    "id": "case-a",
                    "title": "case a",
                    "suite": "isolation",
                    "expected": {"should_pass": True, "must_block": False},
                    "mock_responses": [
                        {"schema_version": "1", "action": "finish", "args": {"summary": "plan"}},
                        {
                            "schema_version": "1",
                            "action": "replace_file",
                            "args": {
                                "path": "index.html",
                                "content": (
                                    '<!doctype html><html><head><meta name="viewport" content="width=device-width">'
                                    '<title>Search</title></head><body><input type="search">Search Details</body></html>'
                                ),
                            },
                        },
                        {"schema_version": "1", "action": "finish", "args": {"summary": "review complete"}},
                    ],
                }
            ),
            encoding="utf-8",
        )

        suite = run_eval_suite(root, strategy="multi-agent-isolated", suite="isolation")

        self.assertEqual(suite.total_cases, 1)
        self.assertEqual(suite.results[0].role_runs, 3)
        self.assertEqual(suite.results[0].role_blocked_actions, 0)
```

Add to `tests/test_benchmark.py`:

```python
def test_benchmark_summary_includes_role_metrics(self):
    suite = EvalSuiteResult(
        strategy="multi-agent-isolated",
        total_cases=1,
        passed_cases=1,
        expected_matches=1,
        results=[
            EvalCaseResult(
                case_id="case-a",
                strategy="multi-agent-isolated",
                passed=True,
                expected_passed=True,
                expected_match=True,
                steps=3,
                parse_errors=0,
                blocked_actions=0,
                gate_failures=0,
                context_chars_max=100,
                final_summary="ok",
                role_runs=3,
                role_blocked_actions=1,
                review_repairs=1,
            )
        ],
    )

    summary = summarize_benchmark([suite])

    self.assertEqual(summary.results[0].role_runs, 3)
    self.assertEqual(summary.results[0].role_blocked_actions, 1)
    self.assertEqual(summary.results[0].review_repairs, 1)
```

- [ ] **Step 2: Run focused failing tests**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_eval_runner tests.test_benchmark -v
```

Expected: FAIL because eval/benchmark dataclasses do not include role metrics.

- [ ] **Step 3: Extend eval result dataclass**

In `src/specgate/eval_runner.py`, add fields to `EvalCaseResult`:

```python
role_runs: int = 0
role_blocked_actions: int = 0
review_repairs: int = 0
```

When building `EvalCaseResult`, copy from `result.metrics`:

```python
role_runs=result.metrics.role_runs if result.metrics else 0,
role_blocked_actions=result.metrics.role_blocked_actions if result.metrics else 0,
review_repairs=result.metrics.review_repairs if result.metrics else 0,
```

- [ ] **Step 4: Extend benchmark result dataclass**

In `src/specgate/benchmark.py`, add fields to the benchmark result model:

```python
role_runs: int = 0
role_blocked_actions: int = 0
review_repairs: int = 0
```

When summarizing a suite:

```python
role_runs=sum(item.role_runs for item in suite.results),
role_blocked_actions=sum(item.role_blocked_actions for item in suite.results),
review_repairs=sum(item.review_repairs for item in suite.results),
```

- [ ] **Step 5: Add example eval case files**

Create `examples/eval_cases/true-multi-agent-isolation/TASK_SPEC.md`:

```markdown
# True Multi-Agent Isolation Task

Build a static HTML page that contains a search input and the visible text "Search Details".
```

Create `examples/eval_cases/true-multi-agent-isolation/CHECKLIST.md`:

```markdown
- 必须包含 Search
- 必须包含 Details
```

Create `examples/eval_cases/true-multi-agent-isolation/index.html`:

```html

```

Create `examples/eval_cases/true-multi-agent-isolation/specgate.toml`:

```toml
[context]
strategy = "multi-agent-isolated"
```

Create `examples/eval_cases/true-multi-agent-isolation/case.json`:

```json
{
  "id": "true-multi-agent-isolation",
  "title": "True multi-agent isolation should run planner implementer reviewer",
  "category": "context-isolate",
  "suite": "isolation",
  "tags": ["multi-agent", "role-boundary"],
  "expected": {
    "should_pass": true,
    "must_block": false,
    "trust": "trusted"
  },
  "mock_responses": [
    {
      "schema_version": "1",
      "action": "finish",
      "args": {
        "summary": "Plan: write a static Search Details page with a search input."
      }
    },
    {
      "schema_version": "1",
      "action": "replace_file",
      "args": {
        "path": "index.html",
        "content": "<!doctype html><html><head><meta name=\"viewport\" content=\"width=device-width\"><title>Search Details</title></head><body><main><h1>Search Details</h1><input type=\"search\" aria-label=\"Search\"><p>Search Details</p></main></body></html>"
      }
    },
    {
      "schema_version": "1",
      "action": "finish",
      "args": {
        "summary": "review complete"
      }
    }
  ]
}
```

- [ ] **Step 6: Run focused tests**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_eval_runner tests.test_benchmark -v
```

Expected: PASS.

- [ ] **Step 7: Run isolation eval**

Run:

```powershell
$env:PYTHONPATH="src"
python -m specgate.cli eval examples/eval_cases --suite isolation --context-strategy multi-agent-isolated
```

Expected: command exits 0 and reports at least the new true multi-agent case.

- [ ] **Step 8: Commit**

Run:

```powershell
git add src/specgate/eval_runner.py src/specgate/benchmark.py tests/test_eval_runner.py tests/test_benchmark.py examples/eval_cases/true-multi-agent-isolation
git commit -m "feat: add multi-agent isolation eval coverage"
```

---

### Task 10: Update README and Run Full Verification

**Files:**

- Modify: `README.md`

- [ ] **Step 1: Update README multi-agent section**

Add under the Context Harness Deepening section:

```markdown
### True Multi-Agent Isolation

`multi-agent-isolated` 是第一版真实角色隔离策略。它在单进程内按 planner -> implementer -> reviewer 三阶段运行，同一套 MockLLM 接口按顺序返回角色动作，但每个角色收到不同 context view、state view 和 allowed actions。

planner 和 reviewer 不能写文件；如果它们输出 `write_file` 或 `replace_file`，SpecGate 会在 role capability 层阻断并记录 `role_action_blocked`。implementer 可以提出写入，但仍然必须经过 `WorkspacePolicy`、snapshot guardrail、HITL review profile 和 `ToolDispatcher`。

常用命令：

```powershell
$env:PYTHONPATH="src"
python -m specgate.cli eval examples/eval_cases --suite isolation --context-strategy multi-agent-isolated --save-workspaces
python -m specgate.cli benchmark examples/eval_cases --strategies baseline rag-select compressed-rag isolated-harness multi-agent-isolated
```

运行后可查看 `runs/latest/isolation.json` 和 `reports/latest/index.html` 中的 Role Execution Evidence。
```

- [ ] **Step 2: Run full unit tests**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest discover -s tests -v
```

Expected: PASS.

- [ ] **Step 3: Run isolation eval**

Run:

```powershell
$env:PYTHONPATH="src"
python -m specgate.cli eval examples/eval_cases --suite isolation --context-strategy multi-agent-isolated
```

Expected: command exits 0 and writes `examples/eval_cases/eval-runs/latest/results.json`.

- [ ] **Step 4: Run benchmark smoke**

Run:

```powershell
$env:PYTHONPATH="src"
python -m specgate.cli benchmark examples/eval_cases --strategies baseline rag-select compressed-rag isolated-harness multi-agent-isolated
```

Expected: command exits 0 and includes `multi-agent-isolated` in benchmark output.

- [ ] **Step 5: Check git status**

Run:

```powershell
git status --short
```

Expected: only README changes remain before commit.

- [ ] **Step 6: Commit docs**

Run:

```powershell
git add README.md
git commit -m "docs: document true multi-agent isolation"
```

---

## Final Verification

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest discover -s tests -v
python -m specgate.cli eval examples/eval_cases --suite isolation --context-strategy multi-agent-isolated
python -m specgate.cli benchmark examples/eval_cases --strategies baseline rag-select compressed-rag isolated-harness multi-agent-isolated
git status --short --branch
```

Expected:

- all unit tests pass;
- isolation eval exits 0;
- benchmark exits 0;
- branch contains only committed source, test, docs, and eval-case changes;
- no generated `eval-runs/`, `runs/`, `reports/`, or secret files are staged.

## Self-Review Notes

Spec coverage:

- Role capability isolation is covered by Tasks 1, 5, and 6.
- Role-specific context/state views are covered by Task 3.
- Centralized policy, snapshot, HITL, and tool governance are covered by Tasks 4, 5, and 6.
- Repair cycle is covered by Task 7.
- Role execution evidence and reporting are covered by Tasks 1, 5, and 8.
- Eval and benchmark integration are covered by Task 9.
- Documentation and full verification are covered by Task 10.

Type consistency:

- `RoleExecution`, `MultiAgentState`, `role_runs`, `role_blocked_actions`, and `review_repairs` use the same names across model, runner, eval, benchmark, report, and tests.
- Strategy name is consistently `multi-agent-isolated`.
- Existing `isolated-harness` remains as compatibility evidence mode.
