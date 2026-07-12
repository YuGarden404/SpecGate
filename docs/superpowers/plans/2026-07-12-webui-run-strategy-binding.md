# WebUI Run Strategy Binding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make WebUI run execution use the current user's saved governance and context settings instead of hard-coded `review + injection-safe`.

**Architecture:** Keep the WebUI mock-first execution path. `web_runs.py` reads `user_settings` before constructing `AgentRunner`, passes the selected `GovernanceConfig` and context strategy into the runner, and the existing trace/debug pipeline proves the applied strategy. The frontend derives displayed strategy values from trace/debug data without adding new backend fields.

**Tech Stack:** Python stdlib, SQLite, existing SpecGate runner/config modules, static JavaScript, `unittest`.

---

## File Structure

- Modify `src/specgate/web_runs.py`: load user settings for run/resume and pass them to `_run_mock_agent` / `_run_resume_agent`.
- Modify `src/specgate/web_static/app.js`: show governance/context strategy and MockLLM mode in Audit overview.
- Modify `src/specgate/web_static/index.html`: bump static asset version.
- Modify `tests/test_web_runs.py`: add TDD coverage for settings-driven run strategy.
- Modify `tests/test_web_static.py`: add static checks for strategy display helpers.

---

### Task 1: Backend Run Strategy Binding

**Files:**
- Modify: `tests/test_web_runs.py`
- Modify: `src/specgate/web_runs.py`

- [ ] **Step 1: Write failing test for settings-driven run strategy**

Add to `tests/test_web_runs.py`:

```python
from specgate.web_settings import update_settings

    def test_execute_run_once_uses_user_governance_and_context_settings(self):
        db_path, data_root, user, project = self.make_context()
        update_settings(
            db_path,
            user["id"],
            governance_profile="strict",
            context_strategy="rag-select",
        )
        run = create_run(db_path, project["id"], user["id"], "Build the result")

        execute_run_once(db_path, data_root, run["id"])

        paths = project_paths(data_root, user["id"], project["id"])
        trace_text = (paths.workspace / "runs" / "latest" / "trace.jsonl").read_text(encoding="utf-8")
        self.assertIn('"strategy": "rag-select"', trace_text)
        self.assertIn('"profile": "strict"', trace_text)
```

- [ ] **Step 2: Run test and verify failure**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_web_runs -v
```

Expected: new test fails because trace still contains `injection-safe` and `review`.

- [ ] **Step 3: Implement settings loading**

In `src/specgate/web_runs.py`:

- Import `get_settings`.
- In `execute_run_once`, call `settings = get_settings(db_path, int(run["user_id"]))`.
- Change `_run_mock_agent(paths)` to `_run_mock_agent(paths, settings)`.
- In `resume_run_once`, call settings for `user_id` and pass to `_run_resume_agent(paths, settings)`.
- Change `_run_mock_agent` and `_run_resume_agent` signatures.
- Build:

```python
governance = GovernanceConfig(profile=settings["governance_profile"])
...
context=ContextConfig(strategy=settings["context_strategy"])
```

- [ ] **Step 4: Run backend tests**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_web_runs -v
```

Expected: all web run tests pass.

---

### Task 2: Audit Strategy Display

**Files:**
- Modify: `tests/test_web_static.py`
- Modify: `src/specgate/web_static/app.js`
- Modify: `src/specgate/web_static/index.html`

- [ ] **Step 1: Write failing static test**

Add to `tests/test_web_static.py`:

```python
    def test_app_contains_audit_strategy_display(self) -> None:
        app_js = read_static("app.js")
        self.assertIn("治理策略", app_js)
        self.assertIn("上下文策略", app_js)
        self.assertIn("运行模式", app_js)
        self.assertIn("function auditRunStrategy", app_js)
```

- [ ] **Step 2: Run static test and verify failure**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_web_static -v
```

Expected: fails until helper and labels exist.

- [ ] **Step 3: Implement frontend helper**

In `src/specgate/web_static/app.js`, add:

```javascript
function auditRunStrategy(debug) {
  const events = (debug.trace && debug.trace.events) || [];
  let contextStrategy = "未知";
  let governanceProfile = "未知";
  for (const event of events) {
    if (event.event_type === "context_built" && event.payload && event.payload.strategy) {
      contextStrategy = event.payload.strategy;
    }
    if (event.event_type === "run_summary" && event.payload && event.payload.profile) {
      governanceProfile = event.payload.profile;
    }
  }
  return { governanceProfile, contextStrategy, llmMode: "MockLLM" };
}
```

In `renderAuditOverview`, include rows:

- `治理策略`
- `上下文策略`
- `运行模式`

- [ ] **Step 4: Bump static asset version**

Update `index.html` static version from `20260712-4` to `20260712-5`.

- [ ] **Step 5: Run static tests**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_web_static -v
```

Expected: pass.

---

### Task 3: Verification and Commit

**Files:**
- All modified files

- [ ] **Step 1: Run focused tests**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_web_runs tests.test_web_debug tests.test_web_app tests.test_web_static -v
```

Expected: pass.

- [ ] **Step 2: Run full tests**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest discover -s tests -v
```

Expected: pass.

- [ ] **Step 3: Commit implementation**

Run:

```powershell
git add src/specgate/web_runs.py src/specgate/web_static/app.js src/specgate/web_static/index.html tests/test_web_runs.py tests/test_web_static.py docs/superpowers/plans/2026-07-12-webui-run-strategy-binding.md
git commit -m "feat: bind WebUI runs to saved strategy"
```

Expected: commit succeeds.

---

## Self-Review

- Spec coverage: plan binds settings into backend runs, exposes strategy through existing trace/debug evidence, updates Audit display, and verifies behavior with tests.
- Placeholder scan: no TBD/TODO placeholders remain.
- Type consistency: `auditRunStrategy`, `governanceProfile`, and `contextStrategy` are used consistently.
