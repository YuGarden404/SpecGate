# Demo Showcase Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve the mock demo artifact so reviewers see a usable static AI4SE knowledge navigator instead of placeholder `Node 0` content.

**Architecture:** Keep the harness unchanged. Only improve the deterministic `MockLLM` demo HTML emitted by `src/specgate/cli.py`, then regenerate the checked-in example artifact and report.

**Tech Stack:** Python standard library, `unittest`, single-file static HTML/CSS/JS.

---

### Task 1: Add Showcase Expectations

**Files:**
- Modify: `tests/test_cli.py`

- [ ] Add assertions that the generated `index.html` contains `AI for Coding 知识图谱`, a search input, `knowledgeDetail`, at least 10 `.node` cards, and the functions `filterNodes`, `showDetail`, and `highlightRelations`.
- [ ] Run `python -m unittest tests.test_cli -v` and confirm the new test fails against the old placeholder HTML.

### Task 2: Improve Mock Demo HTML

**Files:**
- Modify: `src/specgate/cli.py`

- [ ] Replace `_fixed_demo_html()` with a deterministic single-file HTML page.
- [ ] Include knowledge nodes for Spec, Checklist, Action Protocol, MockLLM, Guardrail, Tool Dispatcher, HTML Gate, Feedback Loop, Context Pack, Trace / Report, Credentials, and Docker / CI.
- [ ] Add inline CSS and JS only; do not introduce external assets, npm, React, Vue, or network dependencies.
- [ ] Run `python -m unittest tests.test_cli -v` and confirm it passes.

### Task 3: Regenerate Example Artifact

**Files:**
- Modify: `examples/knowledge_nav/index.html`
- Modify: `examples/knowledge_nav/reports/latest/index.html`
- Modify: `examples/knowledge_nav/runs/latest/trace.jsonl`

- [ ] Run `python -m specgate.cli run-mock-demo examples/knowledge_nav`.
- [ ] Run `python -m unittest discover -s tests -v`.
- [ ] Ask the user to inspect `examples/knowledge_nav/index.html` before committing.
