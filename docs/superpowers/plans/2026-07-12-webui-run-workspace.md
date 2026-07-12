# WebUI Run Workspace Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade the WebUI Status tab into a run workspace that summarizes status, strategy, metrics, trace flow, artifacts, and approvals from existing debug data.

**Architecture:** Keep the backend unchanged. The frontend loads `/api/runs/{id}/debug` for the current run, reuses existing Audit helpers where possible, and renders a compact Status workspace. Static `unittest` coverage checks function presence, Chinese labels, style hooks, and asset cache versioning.

**Tech Stack:** Python `unittest`, static HTML/CSS/JavaScript, existing FastAPI debug API.

---

## File Structure

- Modify `tests/test_web_static.py`: add static tests for run workspace functions, labels, style hooks, and version bump.
- Modify `src/specgate/web_static/app.js`: replace the simple Status tab with debug-backed run workspace rendering.
- Modify `src/specgate/web_static/styles.css`: add layout hooks for workspace, flow, artifact, and approval cards.
- Modify `src/specgate/web_static/index.html`: bump static asset version from `20260712-5` to `20260712-6`.

---

### Task 1: Static Tests for Run Workspace

**Files:**
- Modify: `tests/test_web_static.py`

- [ ] **Step 1: Add failing tests**

Append these tests to `WebStaticTests`:

```python
    def test_app_contains_status_run_workspace_helpers(self) -> None:
        app_js = read_static("app.js")
        for function_name in (
            "renderRunWorkspace",
            "renderRunWorkspaceMetrics",
            "renderRunWorkspaceFlow",
            "renderRunWorkspaceArtifacts",
            "renderRunWorkspaceApprovals",
            "formatBytes",
        ):
            with self.subTest(function_name=function_name):
                self.assertIn(f"function {function_name}", app_js)
        for text in ("运行工作台", "执行流程", "产物", "前往审批", "暂无产物"):
            with self.subTest(text=text):
                self.assertIn(text, app_js)

    def test_styles_include_run_workspace_hooks(self) -> None:
        css = read_static("styles.css")
        for selector in (
            ".run-workspace",
            ".run-workspace-grid",
            ".run-flow",
            ".run-flow-item",
            ".artifact-list",
            ".artifact-item",
        ):
            with self.subTest(selector=selector):
                self.assertIn(selector, css)
```

- [ ] **Step 2: Run tests and verify red**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_web_static -v
```

Expected: the new tests fail because the helper functions, Chinese labels, and CSS hooks do not exist yet.

---

### Task 2: Implement Status Run Workspace

**Files:**
- Modify: `src/specgate/web_static/app.js`

- [ ] **Step 1: Replace `renderStatusDetail` with debug-backed rendering**

Change `renderStatusDetail(content)` so it:

```javascript
function renderStatusDetail(content) {
  const card = el("section", { className: "detail-card stack" });
  card.append(el("h2", {}, ["运行工作台"]));
  const run = state.currentRun;
  if (!state.selectedProject) {
    card.append(el("p", { className: "muted" }, ["请先创建或选择项目。"]));
    content.append(card);
    return;
  }
  if (!run) {
    card.append(el("p", { className: "muted" }, ["当前项目还没有运行。"]));
    card.append(renderBasicRunRows(null));
    content.append(card);
    return;
  }

  const body = el("div", { className: "run-workspace" }, ["正在加载运行证据..."]);
  card.append(body);
  content.append(card);

  const existing = state.runDebug && state.runDebug.run && state.runDebug.run.id === run.id;
  const loader = existing ? Promise.resolve(state.runDebug) : loadRunDebug(run.id);
  loader
    .then((debug) => {
      body.replaceChildren(renderRunWorkspace(debug));
    })
    .catch((error) => {
      body.replaceChildren(
        renderBasicRunRows(run),
        el("p", { className: "message-line error" }, [`运行证据暂不可用：${error.message}`]),
      );
    });
}
```

- [ ] **Step 2: Add `renderBasicRunRows` helper**

Add after `renderStatusDetail`:

```javascript
function renderBasicRunRows(run) {
  const rows = [
    ["Project", state.selectedProject ? state.selectedProject.name : "None"],
    ["Run", run ? `#${run.id}` : "No active run"],
    ["Status", run ? run.status : state.selectedProject?.last_run_status || "Idle"],
    ["Trust", run ? run.trust_level || "pending" : "n/a"],
    ["Error", run ? run.error_message || "None" : "None"],
    ["Created", run ? run.created_at || "n/a" : "n/a"],
    ["Started", run ? run.started_at || "n/a" : "n/a"],
    ["Finished", run ? run.finished_at || "n/a" : "n/a"],
  ];
  const dl = el("dl", { className: "detail-grid" });
  for (const [label, value] of rows) {
    dl.append(el("dt", {}, [label]), el("dd", {}, [value]));
  }
  return dl;
}
```

- [ ] **Step 3: Add workspace render helpers**

Add these helpers after `renderBasicRunRows`:

```javascript
function renderRunWorkspace(debug) {
  const wrapper = el("div", { className: "run-workspace stack" });
  wrapper.append(renderBasicRunRows(debug.run || state.currentRun));
  wrapper.append(renderRunWorkspaceMetrics(debug));
  wrapper.append(renderRunWorkspaceFlow(debug));
  wrapper.append(renderRunWorkspaceArtifacts(debug));
  wrapper.append(renderRunWorkspaceApprovals(debug));
  return wrapper;
}

function renderRunWorkspaceMetrics(debug) {
  const strategy = auditRunStrategy(debug);
  const summary = latestRunSummary(debug);
  const metrics = summary.metrics || {};
  const items = [
    ["治理策略", strategy.governanceProfile],
    ["上下文策略", strategy.contextStrategy],
    ["运行模式", strategy.llmMode],
    ["LLM 调用", metrics.llm_calls ?? 0],
    ["工具调用", metrics.tool_calls ?? 0],
    ["Gate 次数", metrics.gate_runs ?? 0],
    ["阻止动作", metrics.blocked_actions ?? 0],
    ["审批请求", metrics.approval_requests ?? 0],
    ["RAG 查询", metrics.retrieval_queries ?? 0],
    ["最大上下文", metrics.context_chars_max ?? 0],
  ];
  const section = el("section", { className: "run-workspace-section" });
  section.append(el("h3", {}, ["策略与指标"]));
  const grid = el("div", { className: "run-workspace-grid" });
  for (const [label, value] of items) {
    grid.append(el("div", { className: "audit-metric" }, [el("span", {}, [label]), el("strong", {}, [value])]));
  }
  section.append(grid);
  return section;
}

function renderRunWorkspaceFlow(debug) {
  const section = el("section", { className: "run-workspace-section" });
  section.append(el("h3", {}, ["执行流程"]));
  const events = ((debug.trace && debug.trace.events) || []).slice(0, 6);
  if (!events.length) {
    section.append(el("p", { className: "muted" }, ["本次运行还没有流程事件。"]));
    return section;
  }
  const list = el("ol", { className: "run-flow" });
  for (const event of events) {
    const payload = event.payload || {};
    const step = payload.step ? `Step ${payload.step}` : event.event_type || "event";
    list.append(
      el("li", { className: "run-flow-item" }, [
        el("strong", {}, [translateTraceEvent(event.event_type)]),
        el("small", {}, [step]),
        el("p", {}, [describeTraceEvent(event)]),
      ]),
    );
  }
  section.append(list);
  const trace = debug.trace || {};
  if (trace.truncated || (trace.total_events || 0) > events.length) {
    section.append(el("p", { className: "muted" }, ["更多流程细节请查看 Audit。"]));
  }
  return section;
}

function renderRunWorkspaceArtifacts(debug) {
  const section = el("section", { className: "run-workspace-section" });
  section.append(el("h3", {}, ["产物"]));
  const artifacts = debug.artifacts || [];
  if (!artifacts.length) {
    section.append(el("p", { className: "muted" }, ["暂无产物。"]));
    return section;
  }
  const list = el("div", { className: "artifact-list" });
  for (const artifact of artifacts) {
    const item = el("div", { className: "artifact-item" });
    item.append(el("strong", {}, [artifact.kind || "artifact"]));
    item.append(el("span", { className: artifact.exists ? "pill" : "pill danger" }, [artifact.exists ? "已生成" : "缺失"]));
    item.append(el("small", {}, [formatBytes(artifact.size_bytes || 0)]));
    if (artifact.exists && artifact.download_url) {
      item.append(
        el(
          "a",
          { href: artifact.download_url, download: artifact.kind === "zip" ? "result.zip" : "index.html" },
          ["下载"],
        ),
      );
    }
    list.append(item);
  }
  section.append(list);
  return section;
}

function renderRunWorkspaceApprovals(debug) {
  const section = el("section", { className: "run-workspace-section" });
  section.append(el("h3", {}, ["审批"]));
  const approvals = debug.approvals || [];
  const run = debug.run || state.currentRun || {};
  if (!approvals.length && run.status !== "needs_approval") {
    section.append(el("p", { className: "muted" }, ["无待处理审批。"]));
    return section;
  }
  section.append(el("p", {}, [`审批数量：${approvals.length}`]));
  const button = el("button", { type: "button", className: "secondary" }, ["前往审批"]);
  button.addEventListener("click", () => {
    state.activeTab = "approvals";
    renderDetail();
  });
  section.append(button);
  return section;
}

function formatBytes(value) {
  const size = Number(value || 0);
  if (size >= 1024 * 1024) {
    return `${(size / (1024 * 1024)).toFixed(1)} MB`;
  }
  if (size >= 1024) {
    return `${(size / 1024).toFixed(1)} KB`;
  }
  return `${size} B`;
}
```

- [ ] **Step 4: Run static tests**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_web_static -v
```

Expected: helper/label tests pass, CSS hook test still fails until Task 3.

---

### Task 3: Add Run Workspace CSS and Bump Asset Version

**Files:**
- Modify: `src/specgate/web_static/styles.css`
- Modify: `src/specgate/web_static/index.html`

- [ ] **Step 1: Add CSS hooks**

Append these styles near the existing audit styles:

```css
.run-workspace {
  display: grid;
  gap: 1rem;
}

.run-workspace-section {
  display: grid;
  gap: 0.75rem;
}

.run-workspace-section h3 {
  margin: 0;
  font-size: 1rem;
}

.run-workspace-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
  gap: 0.6rem;
}

.run-flow {
  display: grid;
  gap: 0.65rem;
  margin: 0;
  padding-left: 1.2rem;
}

.run-flow-item {
  border-left: 2px solid var(--accent);
  padding-left: 0.75rem;
}

.run-flow-item strong,
.run-flow-item small,
.run-flow-item p {
  display: block;
}

.run-flow-item small {
  color: var(--muted);
}

.run-flow-item p {
  margin: 0.25rem 0 0;
}

.artifact-list {
  display: grid;
  gap: 0.55rem;
}

.artifact-item {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto auto auto;
  align-items: center;
  gap: 0.5rem;
  border: 1px solid var(--line);
  border-radius: 7px;
  padding: 0.65rem;
  background: var(--panel);
}
```

- [ ] **Step 2: Bump static version**

In `src/specgate/web_static/index.html`, change both:

```html
20260712-5
```

to:

```html
20260712-6
```

- [ ] **Step 3: Run static tests and verify green**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_web_static -v
```

Expected: all static tests pass.

---

### Task 4: Verification and Commit

**Files:**
- All modified files

- [ ] **Step 1: Run WebUI focused tests**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_web_static tests.test_web_app tests.test_web_debug tests.test_web_runs tests.test_web_approvals -v
```

Expected: pass.

- [ ] **Step 2: Run full test suite**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest discover -s tests -v
```

Expected: pass.

- [ ] **Step 3: Review diff**

Run:

```powershell
git status --short
git diff --stat
```

Expected: only WebUI static files, tests, and this plan are modified.

- [ ] **Step 4: Commit implementation**

Run:

```powershell
git add docs/superpowers/plans/2026-07-12-webui-run-workspace.md tests/test_web_static.py src/specgate/web_static/app.js src/specgate/web_static/styles.css src/specgate/web_static/index.html
git commit -m "feat: render WebUI run workspace"
```

Expected: commit succeeds.

---

## Self-Review

- Spec coverage: Tasks cover Status run workspace, strategy/metrics, trace flow, artifacts, approvals, CSS hooks, asset versioning, and verification.
- Placeholder scan: no unresolved placeholder markers remain.
- Type consistency: function names match between tests and implementation steps.
