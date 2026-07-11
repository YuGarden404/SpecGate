# Governance Metrics Harness Design

## Background

SpecGate already has the core shape of a small Coding Agent Harness: it builds context, calls a MockLLM or an OpenAI-compatible LLM, parses a strict JSON action, dispatches file tools through a policy layer, runs an HTML Gate, writes trace events, stores minimal memory, and generates a static report.

Recent real-LLM experiments showed that different models can produce very different pages under the same task spec. That is useful evidence, but it is not the product direction. SpecGate should not become a model leaderboard. The next stage should make the harness itself stronger: more observable, more governable, and easier to judge from deterministic MockLLM runs.

This stage deepens Harness Engineering rather than Context Engineering. The goal is to make SpecGate look more like a small Codex-style product: the model proposes actions, but the harness owns permissions, evidence, metrics, feedback, and final auditability.

## Product Goal

Build a deterministic governance and metrics layer for SpecGate so every run can answer four questions:

1. What did the agent try to do?
2. Why was each tool action allowed or blocked?
3. How much work did the run consume?
4. Is the final result trustworthy according to policy, Gate checks, and runtime evidence?

The primary validation path remains MockLLM and unit tests. Real LLM runs are allowed as demos, but they are not required for correctness.

## Research Question

This stage answers a harness-level question:

> Can a small coding-agent harness provide enforceable governance and auditable metrics independently of model quality?

The expected answer is demonstrated by deterministic cases where MockLLM attempts both valid and invalid actions. The harness should produce the same policy decisions, metrics, trace summaries, and report sections regardless of whether a real model would have made the same choices.

## Scope

### Included

- Run-level metrics collected during every `AgentRunner` run.
- A structured permission decision record for every parsed action.
- A minimal policy profile field that names the governance posture used for the run.
- A trust summary that classifies the run as `trusted`, `warning`, or `failed`.
- Static report sections for metrics, permission decisions, and trust summary.
- MockLLM-driven tests for normal generation, Gate repair, blocked path escape, blocked secret write, parse errors, and max-step exhaustion.
- Eval summary fields that can aggregate the new metrics across cases.

### Excluded

- No browser automation or pixel-level visual checks.
- No shell tool.
- No MCP implementation.
- No vector database, embedding model, or reranker.
- No model leaderboard.
- No human approval UI. The first implementation records what would need review but does not pause for interactive approval.
- No dependency on network calls in tests.

## Concepts

### Governance Profile

A governance profile is a named policy posture attached to a run. The first implementation supports these names:

- `strict`: default profile. Only configured read/write paths and registered tools are allowed.
- `demo`: same enforcement as `strict`, but report language is optimized for classroom demonstration.
- `review`: records high-risk blocked actions as review-needed events. It does not allow the action automatically.

The first version does not change low-level policy behavior based on profile. This is intentional: the profile is introduced as an auditable run dimension before adding interactive approval.

### Permission Decision

Every parsed action gets a structured permission decision before or during dispatch. The decision records:

- step number
- action name
- target path if present
- allowed boolean
- blocked boolean
- reason text from policy/tool/snapshot
- profile name
- rule family, one of `action`, `path`, `allowlist`, `snapshot`, `tool`, or `none`

This decision must be traceable even when the action is blocked before file mutation.

### Run Metrics

Run metrics summarize harness behavior:

- `steps`
- `context_chars_max`
- `llm_calls`
- `tool_calls`
- `successful_tool_calls`
- `blocked_actions`
- `parse_errors`
- `gate_runs`
- `gate_failures`
- `finish_actions`
- `max_steps_reached`

Duration is not part of this stage because timing-sensitive tests would make the deterministic MockLLM path less stable.

### Trust Summary

The trust summary is a deterministic classification:

- `trusted`: final Gate passed, no parse errors, no blocked actions, and the run finished by an explicit `finish` action.
- `warning`: final Gate passed, but the run had parse errors or blocked actions.
- `failed`: final Gate failed, the run hit max steps without finish, or no final artifact could be validated.

The summary also includes a short list of reasons, such as `gate_failed`, `blocked_actions_present`, `parse_errors_present`, or `max_steps_reached`.

## Architecture

### New Module: `specgate.metrics`

This module owns pure data structures and deterministic updates:

- `RunMetrics`
- `PermissionDecision`
- `TrustSummary`
- `classify_rule_family(reason: str) -> str`
- `build_trust_summary(passed: bool, metrics: RunMetrics) -> TrustSummary`

The module should not read or write files. That keeps it easy to unit test.

### Runner Integration

`AgentRunner` remains the owner of the loop. It creates one `RunMetrics` object at the start and updates it at these points:

- after context build: update `context_chars_max`
- before or after `llm.complete`: increment `llm_calls`
- on parse failure: increment `parse_errors`
- on tool dispatch: increment `tool_calls`, `successful_tool_calls`, and `blocked_actions`
- on Gate execution: increment `gate_runs` and possibly `gate_failures`
- on finish: increment `finish_actions`
- after loop exhaustion: set `max_steps_reached`

`RunResult` gains:

- `metrics: RunMetrics`
- `permission_decisions: list[PermissionDecision]`
- `trust: TrustSummary`
- `profile: str`

Existing call sites should continue working by using default values where possible, but tests should assert the new fields.

### Policy and Tool Boundary

The existing `WorkspacePolicy` and `ToolDispatcher` already enforce actions. This stage does not weaken those rules.

The implementation should record permission decisions from the existing tool result:

- allowed if `tool_result.ok` is true and `tool_result.blocked` is false
- blocked if `tool_result.blocked` is true
- reason from `tool_result.message`
- path from the parsed action arguments

The decision model is shaped so a future pre-dispatch hook can reuse the same report semantics, but this stage records decisions from the existing dispatch result.

### Trace Events

Trace should gain two event types:

- `permission_decision`
- `run_summary`

`permission_decision` records each decision as structured JSON. `run_summary` records metrics and trust summary once at the end.

All trace data must continue to use the existing redaction function.

### Report

The static report should add three sections:

- `Trust Summary`: status and reasons.
- `Run Metrics`: compact table of numeric metrics.
- `Permission Decisions`: ordered list or table showing action, path, allowed/blocked, and reason.

The report should remain static HTML with no frontend build step.

### Eval Runner

Eval results should expose at least these new fields per case:

- `tool_calls`
- `blocked_actions`
- `parse_errors`
- `gate_failures`
- `trust_status`

The existing console line can stay compact. Detailed values belong in `results.json`.

## Data Flow

```text
AgentRunner
  -> build context
  -> LLM complete
  -> parse action
  -> ToolDispatcher dispatch
  -> create PermissionDecision from tool result
  -> update RunMetrics
  -> run Gate when file changes
  -> finish or exhaust max steps
  -> build TrustSummary
  -> append run_summary trace
  -> return RunResult
  -> generate_report renders trust, metrics, decisions
  -> eval_runner copies selected metrics into results.json
```

## Testing Strategy

All tests use MockLLM or fake LLM clients. No network calls are required.

Unit tests:

- `tests/test_metrics.py`
  - rule family classification for path escape, allowlist failure, snapshot conflict, unknown action, and normal allow.
  - trust classification for trusted, warning, and failed runs.

Runner tests:

- successful run produces trusted summary.
- blocked path escape increments blocked action metrics and records a permission decision.
- parse error increments parse error metrics and produces warning or failed summary depending on final Gate.
- max-step exhaustion sets `max_steps_reached` and produces failed summary.

Report tests:

- generated report contains trust summary.
- generated report contains metric names and values.
- generated report contains permission decision reasons.

Eval tests:

- eval result JSON includes trust status and selected metrics.
- mock eval remains deterministic.

## Acceptance Criteria

- `python -m unittest discover -s tests -v` passes.
- Mock demo still works.
- Mock eval still works with all existing context strategies.
- Report shows trust summary, metrics, and permission decisions.
- A blocked action is visible in trace, metrics, and report.
- No real LLM or network access is required to verify the feature.

## Notes on Current Dirty Worktree

The repository currently contains uncommitted real-LLM eval and DOM contract changes on the active branch. This governance metrics stage should be implemented as a separate conceptual feature and should not depend on real LLM quality. When committing, stage only files that belong to the current task.
