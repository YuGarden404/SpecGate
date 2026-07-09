---
name: specgate-static-html-harness
description: Use when working on a SpecGate static HTML task that has TASK_SPEC.md, CHECKLIST.md, an optional existing index.html, and needs a controlled coding-agent harness flow with context selection, registered file tools, guardrails, gate feedback, trace logs, and a static report.
---

# SpecGate Static HTML Harness

## Purpose

Use this skill to run or review a SpecGate task as a small coding-agent harness, not as an unrestricted coding session.

The target task is a static HTML workspace that usually contains:

- `TASK_SPEC.md`: user-facing page requirements.
- `CHECKLIST.md`: deterministic acceptance checks.
- `index.html`: generated or repaired static HTML artifact.
- `specgate.toml`: allowed tools and file allowlists.

## Workflow

1. Read `TASK_SPEC.md`, `CHECKLIST.md`, `specgate.toml`, and any existing `index.html`.
2. Treat root project docs such as `SPEC.md` and `PLAN.md` as harness design docs, not as the runtime task input.
3. Build context from task-relevant files first. Prefer `TASK_SPEC.md`, `CHECKLIST.md`, `README.md`, and `index.html`; skip `runs/`, `reports/`, `.git/`, caches, and binary files.
4. Use only registered tools from the SpecGate Tool Registry:
   - `read_file`
   - `write_file`
   - `replace_file`
   - `list_files`
   - `finish`
5. Never introduce shell, browser automation, network tools, MCP tools, or arbitrary filesystem access for the MVP path.
6. Before writing, respect `WorkspacePolicy` allowlists and file snapshot protection.
7. After a write, run the static HTML Gate and feed any failure message back into the next action.
8. Stop when the Gate passes or when the configured step budget is exhausted.
9. Preserve traceability: the run should leave trace events and a static report.

## Decision Rules

- If the user asks to generate or repair a static HTML page, operate through `TASK_SPEC.md` and `CHECKLIST.md`.
- If the user asks about project architecture, use root docs such as `SPEC.md`, `PLAN.md`, `SPEC_PROCESS.md`, and `AGENT_LOG.md`.
- If a requested change needs shell, Playwright, browser MCP, or broad file access, mark it outside the current MVP boundary unless the project scope has explicitly changed.
- If a file was externally modified during a run, do not overwrite it; report the safety block.
- If a real LLM provider is requested, keep `mock` as the default and require explicit provider configuration.

## Verification

For normal project verification, run:

```powershell
$env:PYTHONPATH="src"
python -m unittest discover -s tests -v
```

For the built-in demo, run:

```powershell
$env:PYTHONPATH="src"
python -m specgate.cli run-mock-demo examples/knowledge_nav
```

The expected result is:

- unit tests pass;
- `examples/knowledge_nav/index.html` exists;
- `examples/knowledge_nav/runs/latest/trace.jsonl` exists;
- `examples/knowledge_nav/reports/latest/index.html` exists.

## Reporting

When summarizing a SpecGate run, include:

- selected context and skipped runtime artifacts;
- model action count and tool calls;
- blocked guardrail decisions, if any;
- Gate result and repair hints;
- final HTML artifact path;
- static report path or published URL.
