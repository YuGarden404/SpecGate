# HITL Review Gate Design

## Background

SpecGate already has the core pieces of a small Coding Agent Harness: an agent loop, strict JSON actions, a policy layer, file tools, Gate feedback, trace output, eval cases, real-LLM compatibility, and a governance metrics layer.

The latest governance metrics work makes runs auditable after the fact. It records what the agent tried to do, whether tool calls succeeded or were blocked, and whether the final result is trusted, warning, or failed. The next step should make governance active before execution, not only visible after execution.

This stage adds a Human-in-the-loop (HITL) Review Gate. The harness classifies actions by risk. Safe actions can execute automatically. Blocked actions are denied. Review actions are paused and written to a pending approval queue instead of being executed.

This keeps SpecGate focused on Harness Engineering rather than model benchmarking. The LLM proposes actions, but the harness owns the final decision about whether an action may mutate the workspace.

## Product Goal

Build a deterministic review gate for SpecGate so a run can answer:

1. Which actions were safe enough to execute automatically?
2. Which actions were blocked by hard policy?
3. Which actions required human review and were therefore not executed?
4. What evidence should a human reviewer inspect before approving or denying the action?

The first implementation is intentionally non-interactive inside the agent loop. It records pending approvals and stops the risky action from executing. A later stage can add resume-after-approval.

## Research Question

This stage answers a harness-level question:

> Can a small coding-agent harness enforce reversible vs irreversible action boundaries deterministically, independent of model quality?

The expected answer is demonstrated with MockLLM tests. A mock model can request safe writes, blocked writes, and review-required actions. The harness should produce stable approval decisions without depending on a real model's judgement.

## Scope

### Included

- A deterministic action risk classifier.
- A `review` governance profile that turns review-classified actions into pending approvals.
- A structured pending approval data model.
- A persisted approval queue under the run artifact directory.
- Trace events for approval requests.
- Report sections that show pending approvals and review-required actions.
- CLI command to list pending approvals for a workspace.
- MockLLM-driven tests for safe, blocked, and review-required actions.
- Eval/result fields that expose pending approval counts.

### Excluded

- No interactive terminal prompt inside the agent loop.
- No automatic resume after approval in this stage.
- No shell execution tool.
- No browser UI for approval.
- No external database.
- No network dependency in tests.
- No weakening of existing path allowlists, snapshot checks, or secret redaction.

## Concepts

### Risk Level

Every parsed action is classified into one of three levels:

- `safe`: the action can execute automatically if it also passes existing policy checks.
- `review`: the action should not execute automatically in the `review` profile. It is persisted as a pending approval.
- `blocked`: the action is denied regardless of profile.

The risk level is separate from the existing policy allowlist. A path can be allowed by policy but still require review because the action is irreversible or targets a protected file.

### Governance Profile

Existing profiles remain:

- `strict`: hard policy enforcement. Review-classified actions are blocked.
- `demo`: same enforcement as `strict`, with classroom-friendly reporting.
- `review`: review-classified actions produce pending approvals and do not execute.

The important behavior change is in `review`: the harness distinguishes "needs a human" from "hard denied".

### Pending Approval

A pending approval is a durable record of a requested action that the harness refused to execute automatically. It includes:

- `id`: stable deterministic identifier for this run and step.
- `step`: agent loop step number.
- `action`: action name.
- `path`: target path when present.
- `risk_level`: normally `review`.
- `reason`: human-readable review reason.
- `profile`: governance profile that produced the decision.
- `arguments_preview`: redacted action arguments.
- `status`: initially `pending`.
- `created_at`: ISO timestamp if available; tests may use deterministic construction without asserting exact wall time.

The first implementation only creates and lists pending approvals. It does not approve, deny, or resume them.

### Review Rules

Initial deterministic rules:

- `write_file` to an ordinary allowed task artifact is `safe`.
- `replace_file` is `review` when the target already exists and matches a configured review path.
- `delete_file` is `review` if the action exists in the registry later; if unsupported today, it remains blocked as an unknown action.
- Any action targeting `.env`, paths outside the workspace, or disallowed policy paths is `blocked`.
- Any unknown action is `blocked`.

The first version should support configurable review paths and review actions through `specgate.toml`.

Example:

```toml
[governance]
profile = "review"
review_actions = ["replace_file"]
review_paths = ["README.md", "src/**"]
blocked_paths = [".env", "../*"]
```

If no governance config is present, the existing default behavior should remain conservative.

## Architecture

### New Module: `specgate.approvals`

This module owns review gate data structures and pure classification helpers:

- `RiskLevel`
- `ApprovalStatus`
- `ActionRisk`
- `PendingApproval`
- `ApprovalQueue`
- `classify_action_risk(action, policy, governance_config) -> ActionRisk`

The module should keep file IO small and explicit. Pure classification must be unit-testable without touching the filesystem.

### Config Integration

The existing config loader should parse optional governance fields:

- `profile`
- `review_actions`
- `review_paths`
- `blocked_paths`

Missing fields should default to empty lists plus the existing default profile. Invalid profile names should fail closed, following the current CLI behavior.

### Runner Integration

`AgentRunner` remains the owner of the agent loop. The runner should insert a review decision point after action parsing and before mutation:

```text
parse action
  -> existing policy preconditions
  -> classify risk
  -> if blocked: record blocked decision and feedback
  -> if review under review profile: persist pending approval, record feedback, skip dispatch
  -> if safe: dispatch tool normally
```

The model should receive feedback when an action is routed to review, similar to existing blocked-tool feedback. That allows a following step to choose a safer action.

### Approval Queue Storage

Pending approvals should be stored in:

```text
runs/latest/pending_approvals.json
```

The JSON shape should be stable and human-readable:

```json
{
  "approvals": [
    {
      "id": "approval-step-2",
      "step": 2,
      "action": "replace_file",
      "path": "README.md",
      "risk_level": "review",
      "reason": "replace_file on protected path requires human review",
      "profile": "review",
      "status": "pending",
      "arguments_preview": {"path": "README.md"}
    }
  ]
}
```

The queue belongs to a run artifact, not long-term memory. It should be reset for each run, just like the latest trace.

### Trace and Metrics

Trace gains an `approval_requested` event with the pending approval payload. Existing `permission_decision` and `run_summary` events should continue to exist.

Metrics should gain:

- `approval_requests`
- `pending_approvals`

Trust summary should classify a run with pending approvals as `warning` when the final Gate passes and `failed` when the run cannot complete because the requested action was required for success.

### CLI

Add a small command group:

```powershell
python -m specgate.cli approvals list <workspace>
```

The command reads `runs/latest/pending_approvals.json` and prints a compact table:

```text
ID              STATUS    ACTION        PATH       REASON
approval-step-2 pending   replace_file  README.md  replace_file on protected path requires human review
```

If no queue exists, it should print a clear "no pending approvals" message and exit successfully.

Approval and denial commands are intentionally excluded from this stage because they imply resume semantics. They should be designed after the pending queue is stable.

### Report

The static report should add a `Pending Approvals` section showing:

- count
- id
- status
- action
- path
- reason

Dynamic fields must be HTML-escaped, following the governance report escaping fix already added in the previous branch.

### Eval Runner

Eval results should include:

- `approval_requests`
- `pending_approvals`
- `trust_status`

The console summary can stay compact. Detailed approval data belongs in `results.json` and case workspaces when `--save-workspaces` is used.

## Data Flow

```text
LLM output
  -> parse JSON action
  -> policy and registry checks
  -> risk classifier
  -> governance profile decision
  -> safe: dispatch tool
  -> review: write pending approval and skip mutation
  -> blocked: deny and skip mutation
  -> feedback into next context
  -> Gate/report/trace/eval summaries
```

## Error Handling

- Malformed approval queue JSON should produce a readable CLI error without traceback.
- Unknown governance profile should fail closed during config/CLI parsing.
- Unsupported approval commands should not be added prematurely.
- Review-required actions must never partially mutate the target file.
- Secrets in action arguments must pass through existing redaction before trace/report storage.
- If queue persistence fails, the risky action must remain unexecuted and the run should be marked failed or warning with a clear reason.

## Testing Strategy

All core tests use MockLLM or direct unit inputs. No real LLM or network call is required.

Unit tests:

- `tests/test_approvals.py`
  - classifies ordinary allowed write as `safe`.
  - classifies protected replace as `review`.
  - classifies `.env` or path escape as `blocked`.
  - serializes and loads `PendingApproval` records.

Runner tests:

- review profile records pending approval and does not mutate protected file.
- strict profile blocks the same action instead of creating approval.
- safe write still executes and can pass Gate.
- review feedback reaches the next context.

CLI tests:

- `approvals list` prints no pending approvals when queue is missing.
- `approvals list` prints pending approval rows when queue exists.
- malformed queue produces a clean error.

Report tests:

- report includes `Pending Approvals`.
- report escapes dynamic approval fields.

Eval tests:

- eval result includes approval counts.
- saved workspace includes `runs/latest/pending_approvals.json` for review cases.

## Acceptance Criteria

- A MockLLM run can deterministically produce a pending approval without mutating the protected target.
- A blocked action remains blocked and is not mislabeled as review.
- A safe action still follows the existing dispatch path.
- `runs/latest/pending_approvals.json` is written for review-required actions.
- `python -m specgate.cli approvals list <workspace>` can display pending approvals.
- Trace, report, metrics, and eval outputs include approval evidence.
- The full unit test suite passes without network access.

## Follow-up Work

After this stage, a separate design should cover:

- `approvals approve`
- `approvals deny`
- resume-after-approval
- signed approval records
- WebUI approval view
- session replay or checkpoint restore

Those features are intentionally outside this spec so the current branch stays focused on deterministic review gating.

## Spec Self-Review

- Placeholder scan: no unfinished placeholder markers remain.
- Consistency check: the design treats pending approval as non-executing evidence, not as approval/resume.
- Scope check: the stage is limited to queue creation, listing, trace/report/eval evidence, and deterministic tests.
- Ambiguity check: `review` is distinct from `blocked`; neither path mutates the workspace.
