# SpecGate v0.3.0 Release Evidence Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make v0.3.0 the fully verified current release across SpecGate's evidence materials while preserving every earlier release as history.

**Architecture:** Extend the existing final-evidence contract before changing documentation. Archive three immutable screenshots, update only current-release sections and append dated audit records, then run the full verification stack before recording observed results.

**Tech Stack:** Python `unittest`, Markdown, PNG integrity validation, GitHub Actions/GHCR public metadata, Docker CLI.

---

### Task 1: Bind The v0.3.0 Evidence Contract

**Files:**
- Modify: `tests/test_final_evidence.py`

- [ ] **Step 1: Add v0.3.0 constants**

Add the three screenshot paths and exact PR, commit, run, Release, image, digest, OCI revision, and OCI version facts.

- [ ] **Step 2: Add the current-release test**

Require exact facts in the current release materials, PNG integrity for all three new assets, v0.2.0/v0.1.x history preservation, and removal of stale v0.2.0-current wording.

- [ ] **Step 3: Verify RED**

Run:

```powershell
python -m unittest -v tests.test_final_evidence.FinalEvidenceTests.test_v030_release_evidence_is_current_and_preserves_history
```

Expected: `FAIL` because the v0.3.0 screenshots and dated documentation sections do not exist yet.

### Task 2: Archive Public Evidence

**Files:**
- Add: `docs/evidence/github-actions-ghcr-v0.3.0-success.png`
- Add: `docs/evidence/github-actions-ghcr-v0.3.0-summary.png`
- Add: `docs/evidence/github-release-v0.3.0.png`

- [ ] **Step 1: Capture the GHCR success page**

Archive the public GHCR #4 run page showing success, tag `v0.3.0`, and the workflow identity.

- [ ] **Step 2: Capture the workflow summary**

Archive the summary page showing the published image and digest.

- [ ] **Step 3: Copy the supplied Release screenshot unchanged**

Use the user's full-page screenshot containing `Latest`, `v0.3.0`, `e3ec022`, image, digest, OCI revision, and source assets.

- [ ] **Step 4: Validate the assets**

Run the focused PNG checks through the v0.3.0 evidence test after documentation is synchronized.

### Task 3: Synchronize Current Release Facts

**Files:**
- Modify: `README.md`
- Modify: `SPEC.md`
- Modify: `PLAN.md`
- Modify: `AGENT_LOG.md`
- Modify: `docs/DEPLOYMENT.md`
- Modify: `docs/FINAL_EVIDENCE_MATRIX.md`
- Modify: `docs/FINAL_SUBMISSION_CHECKLIST.md`
- Modify: `docs/PROJECT_WALKTHROUGH.md`
- Modify: `docs/REFLECTION_FACT_CHECK.md`

- [ ] **Step 1: Update user-facing download and release entries**

Make `0.3.0` the current Docker tag and Release link in README and deployment guidance. Keep the complete v0.2.0 history in the following paragraph.

- [ ] **Step 2: Update course and audit summaries**

Bind PR #32, `main@e3ec022`, CI #77, Pages #43, GHCR #4, run IDs, digest, revision, version, anonymous smoke, and three screenshot paths.

- [ ] **Step 3: Append dated PLAN and AGENT_LOG sections**

Record only completed public facts and the fresh Docker verification. Leave final test durations unset until the commands have run.

- [ ] **Step 4: Verify GREEN**

Run:

```powershell
python -m unittest -v tests.test_final_evidence.FinalEvidenceTests.test_v030_release_evidence_is_current_and_preserves_history
python -m unittest -v tests.test_final_evidence
```

Expected: both commands finish with `OK`.

### Task 4: Complete Verification And Record Results

**Files:**
- Modify after observation: `PLAN.md`
- Modify after observation: `AGENT_LOG.md`
- Modify after observation: `docs/FINAL_EVIDENCE_MATRIX.md`
- Modify after observation: `docs/FINAL_SUBMISSION_CHECKLIST.md`

- [ ] **Step 1: Run deterministic mechanism demos**

```powershell
python -m unittest -v tests.test_runner.RunnerTests.test_guardrail_block_is_recorded tests.test_runner.RunnerTests.test_gate_failure_feedback_changes_next_action tests.test_cli.CliTests.test_cli_pending_approve_resume_applies_queue_and_writes_report
```

- [ ] **Step 2: Compile Python**

```powershell
python -m compileall -q src tests
```

- [ ] **Step 3: Run the complete offline suite**

```powershell
python -m unittest discover -s tests -v
```

- [ ] **Step 4: Record exact fresh outputs**

Write only the observed test counts, durations, skips, and exit codes into the dated v0.3.0 sections.

- [ ] **Step 5: Re-run final verification**

```powershell
python -m unittest -v tests.test_final_evidence
python -m compileall -q src tests
git diff --check
git status --short --branch
git diff --name-only
```

Expected: tests and compilation pass, `git diff --check` is clean, and the diff contains only the planned documentation, evidence assets, and final-evidence test.

### Task 5: User Git Handoff

**Files:**
- Verify only: all changed files

- [ ] **Step 1: Present the exact staged file groups**

Keep evidence contract/assets separate from the final factual-document synchronization when practical.

- [ ] **Step 2: Leave Git mutation to the user**

The user performs `git add`, `git commit`, `git push`, PR creation, merge, and later worktree/branch cleanup.
