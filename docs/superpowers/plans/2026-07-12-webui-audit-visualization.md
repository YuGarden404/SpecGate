# WebUI Audit Visualization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the WebUI Audit tab from a raw JSON debug view into a Chinese, teacher-readable audit panel while preserving the raw JSON evidence.

**Architecture:** Keep the existing backend debug API unchanged. Update only static frontend assets: add small rendering helpers in `app.js`, add compact CSS hooks, and bump static asset versions in `index.html`.

**Tech Stack:** Static HTML/CSS/JavaScript, Python `unittest` static asset checks.

---

## File Structure

- Modify `tests/test_web_static.py`: add static checks for Chinese audit helpers and layout CSS.
- Modify `src/specgate/web_static/app.js`: add Chinese translation, metrics extraction, trace timeline, evidence rendering, and raw JSON labeling.
- Modify `src/specgate/web_static/styles.css`: add compact audit metrics/timeline styles and make detail tabs wrap safely.
- Modify `src/specgate/web_static/index.html`: bump static resource version.

---

### Task 1: Static Tests for Chinese Audit View

**Files:**
- Modify: `tests/test_web_static.py`

- [ ] **Step 1: Add failing static tests**

Add tests that assert:

```python
def test_app_contains_chinese_audit_visualization_helpers(self) -> None:
    app_js = read_static("app.js")
    self.assertIn("运行概览", app_js)
    self.assertIn("关键指标", app_js)
    self.assertIn("执行流程", app_js)
    self.assertIn("原始 JSON", app_js)
    self.assertIn("function renderAuditMetrics", app_js)
    self.assertIn("function renderAuditTimeline", app_js)
    self.assertIn("function translateRunStatus", app_js)
    self.assertIn("function translateTrustLevel", app_js)

def test_styles_include_audit_visualization_hooks(self) -> None:
    css = read_static("styles.css")
    for selector in (".audit-metrics", ".audit-timeline", ".audit-event"):
        self.assertIn(selector, css)
    self.assertNotIn("grid-template-columns: repeat(6, 1fr)", css)
```

- [ ] **Step 2: Run static tests and verify failure**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_web_static -v
```

Expected: failures for missing helper names, Chinese labels, CSS hooks, and fixed tab grid.

---

### Task 2: Implement Chinese Audit Rendering

**Files:**
- Modify: `src/specgate/web_static/app.js`

- [ ] **Step 1: Replace Audit summary rendering**

Update `renderAuditDetail` so it appends:

- `renderAuditOverview(debug)`
- `renderAuditMetrics(debug)`
- `renderAuditTimeline(debug)`
- `renderAuditEvidence(debug)`
- a heading `原始 JSON`
- raw JSON `<pre>`

- [ ] **Step 2: Add status and trust translation helpers**

Implement:

```javascript
function translateRunStatus(status) {
  const values = {
    completed: "已完成",
    running: "运行中",
    queued: "排队中",
    failed: "失败",
    needs_approval: "等待审批",
  };
  return values[status] || status || "未知";
}

function translateTrustLevel(level) {
  const values = {
    trusted: "可信",
    warning: "警告",
    failed: "失败",
  };
  return values[level] || level || "未知";
}
```

- [ ] **Step 3: Add metrics extraction helper**

Implement `latestRunSummary(debug)` by finding the last trace event where `event_type === "run_summary"`, returning `event.payload`.

- [ ] **Step 4: Add `renderAuditMetrics(debug)`**

Extract `metrics` from `latestRunSummary(debug)`. Render compact metric cards for:

- LLM 调用
- 工具调用
- 被阻止动作
- Gate 次数
- Gate 失败
- 审批请求
- RAG 查询
- 压缩输入
- 压缩输出
- 角色运行

- [ ] **Step 5: Add `renderAuditTimeline(debug)`**

Render trace events as a vertical list. Each event should show:

- Chinese event title
- step number if present
- concise detail text

Event mapping:

- `context_built`: `构建上下文`
- `llm_response`: `LLM 返回动作`
- `permission_decision`: `权限判定`
- `tool_result`: `工具执行`
- `gate_result`: `Gate 校验`
- `run_summary`: `运行总结`
- default: `其他事件`

- [ ] **Step 6: Add `renderAuditEvidence(debug)`**

Render four rows:

- `RAG 检索证据`
- `上下文压缩证据`
- `多代理隔离证据`
- `安全评估证据`

Null means `本次未启用`; non-null means `已记录`.

---

### Task 3: Layout Styling and Cache Bust

**Files:**
- Modify: `src/specgate/web_static/styles.css`
- Modify: `src/specgate/web_static/index.html`

- [ ] **Step 1: Make tabs resilient**

Replace fixed six-column detail tabs with a flexible layout:

```css
.detail-tabs {
  display: flex;
  flex-wrap: wrap;
  ...
}

.tab-button {
  flex: 1 1 auto;
  min-width: 5.4rem;
}
```

- [ ] **Step 2: Add audit CSS hooks**

Add:

```css
.audit-metrics { ... }
.audit-metric { ... }
.audit-timeline { ... }
.audit-event { ... }
.audit-event strong { ... }
```

- [ ] **Step 3: Bump static versions**

Update `index.html` from `20260712-3` to `20260712-4` for both CSS and JS.

---

### Task 4: Verification and Commit

**Files:**
- All modified files

- [ ] **Step 1: Run static tests**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_web_static -v
```

Expected: pass.

- [ ] **Step 2: Run WebUI focused tests**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest tests.test_web_debug tests.test_web_app tests.test_web_static tests.test_web_runs -v
```

Expected: pass.

- [ ] **Step 3: Run full tests**

Run:

```powershell
$env:PYTHONPATH="src"
python -m unittest discover -s tests -v
```

Expected: pass.

- [ ] **Step 4: Commit implementation**

Run:

```powershell
git add src/specgate/web_static/app.js src/specgate/web_static/styles.css src/specgate/web_static/index.html tests/test_web_static.py docs/superpowers/plans/2026-07-12-webui-audit-visualization.md
git commit -m "feat: render WebUI audit details in Chinese"
```

Expected: commit succeeds.

---

## Self-Review

- Spec coverage: plan covers Chinese summary, metrics, timeline, evidence, raw JSON, tabs layout, tests, and cache bust.
- Placeholder scan: no TBD/TODO placeholders remain.
- Type consistency: helper names in tests match implementation names.
