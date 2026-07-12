# WebUI Run Debug Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose SpecGate run audit/debug data to the WebUI so a completed run can show backend harness evidence, trace events, artifacts, approvals, and raw JSON.

**Architecture:** Add a focused `web_debug.py` module that reads existing SQLite rows and workspace evidence files, then expose it through `GET /api/runs/{run_id}/debug`. The frontend adds an Audit tab that lazily fetches the debug payload for the current run and renders a compact summary plus raw JSON.

**Tech Stack:** Python stdlib, FastAPI, SQLite, static JavaScript, `unittest`.

---

## File Structure

- Create `src/specgate/web_debug.py`: build sanitized debug payloads from existing run/project/artifact/approval rows and workspace evidence files.
- Modify `src/specgate/web_app.py`: add `/api/runs/{run_id}/debug` route.
- Modify `src/specgate/web_static/index.html`: add Audit tab button if not already present.
- Modify `src/specgate/web_static/app.js`: load and render run debug payload when Audit tab is active.
- Modify `src/specgate/web_static/styles.css`: add small styles for audit summaries if needed.
- Create `tests/test_web_debug.py`: unit tests for payload shape, user isolation, trace truncation, evidence parsing, and artifact metadata.
- Modify `tests/test_web_app.py`: endpoint-level coverage for authenticated debug access.
- Modify `tests/test_web_static.py`: static checks for Audit tab and frontend debug functions.

---

### Task 1: Backend Debug Payload Builder

**Files:**
- Create: `src/specgate/web_debug.py`
- Create: `tests/test_web_debug.py`

- [ ] **Step 1: Write failing tests for debug payload basics**

Create `tests/test_web_debug.py` with tests that:

```python
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from specgate.web_auth import create_user
from specgate.web_db import init_db
from specgate.web_debug import build_run_debug
from specgate.web_projects import create_manual_project, project_paths
from specgate.web_runs import create_run, execute_run_once


class WebDebugTests(unittest.TestCase):
    def make_completed_run(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name)
        db_path = base / "web.sqlite3"
        data_root = base / "data"
        init_db(db_path)
        user = create_user(db_path, "alice", "correct-password")
        project = create_manual_project(
            db_path,
            data_root,
            user["id"],
            name="Audit Site",
            spec_text="# Spec\nBuild an HTML page.",
            checklist_text="- Ship index.html",
            index_html=None,
        )
        run = create_run(db_path, project["id"], user["id"], "Build it")
        execute_run_once(db_path, data_root, run["id"])
        return db_path, data_root, user, project, run

    def test_build_run_debug_returns_run_project_artifacts_trace_and_summary(self):
        db_path, data_root, user, project, run = self.make_completed_run()

        payload = build_run_debug(db_path, data_root, user["id"], run["id"])

        self.assertEqual(payload["run"]["id"], run["id"])
        self.assertEqual(payload["project"]["id"], project["id"])
        self.assertEqual(payload["summary"]["status"], "completed")
        self.assertTrue(payload["summary"]["has_artifacts"])
        self.assertGreaterEqual(len(payload["artifacts"]), 2)
        self.assertIn("trace", payload)
        self.assertIn("events", payload["trace"])
        self.assertIn("evidence", payload)
```

- [ ] **Step 2: Run focused test and verify it fails**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_web_debug -v
```

Expected: import failure for `specgate.web_debug`.

- [ ] **Step 3: Implement `build_run_debug` minimally**

Add `src/specgate/web_debug.py` with:

```python
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from specgate.trace import redact
from specgate.web_db import connect_db
from specgate.web_projects import project_paths

DEFAULT_MAX_TRACE_EVENTS = 200
DEFAULT_MAX_EVENT_CHARS = 4000


def build_run_debug(
    db_path: Path,
    data_root: Path,
    user_id: int,
    run_id: int,
    *,
    max_trace_events: int = DEFAULT_MAX_TRACE_EVENTS,
    max_event_chars: int = DEFAULT_MAX_EVENT_CHARS,
) -> dict[str, Any]:
    with connect_db(db_path) as conn:
        run = conn.execute(
            "select * from runs where id = ? and user_id = ?",
            (run_id, user_id),
        ).fetchone()
        if run is None:
            raise ValueError("run not found")
        project = conn.execute(
            "select * from projects where id = ? and user_id = ?",
            (run["project_id"], user_id),
        ).fetchone()
        if project is None:
            raise ValueError("project not found")
        artifacts = conn.execute(
            "select * from artifacts where run_id = ? order by kind, id",
            (run_id,),
        ).fetchall()
        approvals = conn.execute(
            "select * from approvals where run_id = ? order by id",
            (run_id,),
        ).fetchall()

    paths = project_paths(data_root, user_id, project["id"])
    artifact_payloads = [_artifact_dict(row, run_id) for row in artifacts]
    approval_payloads = [_row_dict(row) for row in approvals]
    trace = _read_trace(paths.workspace / "runs" / "latest" / "trace.jsonl", max_trace_events, max_event_chars)
    evidence = {
        "retrieval": _read_json_evidence(paths.workspace / "runs" / "latest" / "retrieval.json"),
        "compression": _read_json_evidence(paths.workspace / "runs" / "latest" / "compression.json"),
        "isolation": _read_json_evidence(paths.workspace / "runs" / "latest" / "isolation.json"),
        "security": _read_json_evidence(paths.workspace / "runs" / "latest" / "security.json"),
    }
    summary = {
        "status": run["status"],
        "trust_level": run["trust_level"],
        "has_artifacts": any(item["exists"] for item in artifact_payloads),
        "artifact_count": len(artifact_payloads),
        "approval_count": len(approval_payloads),
        "trace_event_count": len(trace["events"]),
    }
    return {
        "run": _run_dict(run),
        "project": _project_dict(project),
        "artifacts": artifact_payloads,
        "approvals": approval_payloads,
        "trace": trace,
        "evidence": evidence,
        "summary": summary,
    }
```

Implement helper functions `_row_dict`, `_run_dict`, `_project_dict`, `_artifact_dict`, `_read_trace`, `_truncate_event`, and `_read_json_evidence` in the same file.

- [ ] **Step 4: Run focused tests**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_web_debug -v
```

Expected: tests pass.

- [ ] **Step 5: Add trace truncation and evidence tests**

Extend `tests/test_web_debug.py` with:

```python
    def test_build_run_debug_limits_trace_events_and_event_size(self):
        db_path, data_root, user, project, run = self.make_completed_run()
        paths = project_paths(data_root, user["id"], project["id"])
        trace_path = paths.workspace / "runs" / "latest" / "trace.jsonl"
        trace_path.parent.mkdir(parents=True, exist_ok=True)
        trace_path.write_text(
            "\n".join(json.dumps({"event": i, "payload": "x" * 50}) for i in range(5)),
            encoding="utf-8",
        )

        payload = build_run_debug(
            db_path,
            data_root,
            user["id"],
            run["id"],
            max_trace_events=2,
            max_event_chars=30,
        )

        self.assertTrue(payload["trace"]["truncated"])
        self.assertEqual(len(payload["trace"]["events"]), 2)
        self.assertEqual([event["event"] for event in payload["trace"]["events"]], [3, 4])
        self.assertTrue(payload["trace"]["events"][0]["truncated"])

    def test_build_run_debug_reads_evidence_files(self):
        db_path, data_root, user, project, run = self.make_completed_run()
        paths = project_paths(data_root, user["id"], project["id"])
        evidence_path = paths.workspace / "runs" / "latest" / "retrieval.json"
        evidence_path.parent.mkdir(parents=True, exist_ok=True)
        evidence_path.write_text(json.dumps({"selected_chunks": [{"path": "TASK_SPEC.md"}]}), encoding="utf-8")

        payload = build_run_debug(db_path, data_root, user["id"], run["id"])

        self.assertEqual(payload["evidence"]["retrieval"]["selected_chunks"][0]["path"], "TASK_SPEC.md")
        self.assertIsNone(payload["evidence"]["compression"])
```

- [ ] **Step 6: Add user isolation test**

Add:

```python
    def test_build_run_debug_rejects_other_user(self):
        db_path, data_root, user, _project, run = self.make_completed_run()
        other = create_user(db_path, "bob", "correct-password")

        with self.assertRaises(ValueError):
            build_run_debug(db_path, data_root, other["id"], run["id"])
```

- [ ] **Step 7: Run focused tests again**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_web_debug -v
```

Expected: all web debug tests pass.

---

### Task 2: FastAPI Debug Endpoint

**Files:**
- Modify: `src/specgate/web_app.py`
- Modify: `tests/test_web_app.py`

- [ ] **Step 1: Write failing endpoint test**

Add a test that logs in, creates a project, starts a run, executes it synchronously if needed, and calls:

```python
response = client.get(f"/api/runs/{run_id}/debug")
self.assertEqual(response.status_code, 200)
payload = response.json()
self.assertIn("debug", payload)
self.assertEqual(payload["debug"]["run"]["id"], run_id)
self.assertIn("trace", payload["debug"])
```

- [ ] **Step 2: Run endpoint test and verify it fails**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_web_app -v
```

Expected: 404 for missing route or import failure.

- [ ] **Step 3: Add route**

In `src/specgate/web_app.py`, import:

```python
from specgate.web_debug import build_run_debug
```

Add route near existing run routes:

```python
    @app.get("/api/runs/{run_id}/debug")
    def read_run_debug(run_id: int, user=Depends(current_user)) -> dict[str, Any]:
        try:
            debug = build_run_debug(app.state.db_path, app.state.data_root, int(user["id"]), run_id)
        except ValueError as exc:
            raise _http_error_for_value_error(exc) from exc
        return {"debug": debug}
```

- [ ] **Step 4: Run endpoint tests**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_web_app -v
```

Expected: pass.

---

### Task 3: Frontend Audit Tab

**Files:**
- Modify: `src/specgate/web_static/index.html`
- Modify: `src/specgate/web_static/app.js`
- Modify: `src/specgate/web_static/styles.css`
- Modify: `tests/test_web_static.py`

- [ ] **Step 1: Write failing static tests**

Add assertions that:

```python
self.assertIn('data-tab="audit"', index_html)
self.assertIn("loadRunDebug", app_js)
self.assertIn("renderAuditDetail", app_js)
```

- [ ] **Step 2: Run static tests and verify failure**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_web_static -v
```

Expected: fails until Audit tab and JS functions exist.

- [ ] **Step 3: Add Audit tab button**

In `index.html`, add a tab button next to existing detail tabs:

```html
<button type="button" data-tab="audit">Audit</button>
```

- [ ] **Step 4: Add frontend state and rendering**

In `app.js`:

- Add `runDebug: null` to `state`.
- Clear `state.runDebug` when selecting a new project or starting a new run.
- In `renderDetail`, route `state.activeTab === "audit"` to `renderAuditDetail(content)`.
- Implement:

```javascript
async function loadRunDebug(runId) {
  const payload = await apiJson(`/api/runs/${runId}/debug`);
  state.runDebug = payload.debug;
  return state.runDebug;
}

function renderAuditDetail(content) {
  const card = el("section", { className: "detail-card stack" });
  card.append(el("h2", {}, ["Audit / Debug"]));
  const run = state.currentRun;
  if (!run) {
    card.append(el("p", { className: "muted" }, ["No run is available to inspect."]));
    content.append(card);
    return;
  }
  const summary = el("div", { className: "audit-summary" }, ["Loading audit data..."]);
  const pre = el("pre", { className: "source-view" }, [""]);
  card.append(summary, pre);
  content.append(card);
  loadRunDebug(run.id)
    .then((debug) => {
      summary.replaceChildren(renderAuditSummary(debug));
      pre.textContent = JSON.stringify(debug, null, 2);
    })
    .catch((error) => {
      summary.textContent = `Audit data is not available: ${error.message}`;
    });
}
```

Also implement `renderAuditSummary(debug)` to return a compact `dl` with status, trust, artifact count, approval count, trace count, and evidence keys.

- [ ] **Step 5: Run static tests**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_web_static -v
```

Expected: pass.

---

### Task 4: Verification and Commit

**Files:**
- All modified files

- [ ] **Step 1: Run focused WebUI tests**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_web_debug tests.test_web_app tests.test_web_static tests.test_web_runs -v
```

Expected: pass.

- [ ] **Step 2: Run full test suite**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest discover -s tests -v
```

Expected: pass.

- [ ] **Step 3: Check git diff**

Run:

```powershell
git status --short
git diff --stat
```

Expected: only debug/audit docs, backend, frontend, and tests changed.

- [ ] **Step 4: Commit implementation**

Run:

```powershell
git add src/specgate/web_debug.py src/specgate/web_app.py src/specgate/web_static/index.html src/specgate/web_static/app.js src/specgate/web_static/styles.css tests/test_web_debug.py tests/test_web_app.py tests/test_web_static.py docs/superpowers/plans/2026-07-12-webui-run-debug-audit.md
git commit -m "feat: expose WebUI run debug audit"
```

Expected: commit succeeds.

---

## Self-Review

- Spec coverage: the plan adds the debug API, trace limits, evidence parsing, artifact metadata, frontend Audit tab, and tests.
- Placeholder scan: no TBD/TODO/implement-later placeholders remain.
- Type consistency: `build_run_debug`, `loadRunDebug`, and `renderAuditDetail` names are consistent across tasks.
