from __future__ import annotations

import json
import shutil
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

from specgate.config import load_policy
from specgate.llm import LLMClient, MockLLM
from specgate.runner import AgentRunner


@dataclass(frozen=True)
class EvalCase:
    case_id: str
    title: str
    category: str
    path: Path
    expected_should_pass: bool | None
    expected_must_block: bool | None
    real_expected_should_pass: bool | None = None
    real_expected_must_block: bool | None = None
    mock_responses: list[dict] | None = None


@dataclass(frozen=True)
class EvalCaseResult:
    case_id: str
    strategy: str
    passed: bool
    expected_passed: bool | None
    expected_match: bool
    steps: int
    parse_errors: int
    blocked_actions: int
    gate_failures: int
    context_chars_max: int
    final_summary: str
    workspace_path: str | None = None
    tool_calls: int = 0
    successful_tool_calls: int = 0
    gate_runs: int = 0
    trust_status: str = "failed"


@dataclass(frozen=True)
class EvalSuiteResult:
    strategy: str
    total_cases: int
    passed_cases: int
    expected_matches: int
    results: list[EvalCaseResult]


def discover_eval_cases(root: Path) -> list[EvalCase]:
    if not root.exists():
        return []

    cases: list[EvalCase] = []
    for item in sorted(root.iterdir(), key=lambda path: path.name):
        if not item.is_dir():
            continue
        meta_path = item / "case.json"
        if not meta_path.exists():
            continue

        meta = json.loads(meta_path.read_text(encoding="utf-8-sig"))
        expected = meta.get("expected") or {}
        real_expected = meta.get("real_expected") or {}
        case_id = str(meta["id"])
        cases.append(
            EvalCase(
                case_id=case_id,
                title=str(meta.get("title", case_id)),
                category=str(meta.get("category", "uncategorized")),
                path=item,
                expected_should_pass=expected.get("should_pass"),
                expected_must_block=expected.get("must_block"),
                real_expected_should_pass=real_expected.get("should_pass"),
                real_expected_must_block=real_expected.get("must_block"),
                mock_responses=meta.get("mock_responses"),
            )
        )
    return cases


def _count_trace_events(trace_path: Path) -> tuple[int, int, int, int, int, int]:
    parse_errors = 0
    blocked_actions = 0
    gate_failures = 0
    tool_calls = 0
    successful_tool_calls = 0
    gate_runs = 0

    if not trace_path.exists():
        return parse_errors, blocked_actions, gate_failures, tool_calls, successful_tool_calls, gate_runs

    for line in trace_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        event = json.loads(line)
        event_type = event.get("event_type")
        payload = event.get("payload", {})
        if event_type == "parse_error":
            parse_errors += 1
        elif event_type == "tool_result":
            tool_calls += 1
            result = payload.get("result", {})
            if result.get("ok"):
                successful_tool_calls += 1
            if result.get("blocked"):
                blocked_actions += 1
        elif event_type == "gate_result":
            gate_runs += 1
            if payload.get("passed") is False:
                gate_failures += 1

    return parse_errors, blocked_actions, gate_failures, tool_calls, successful_tool_calls, gate_runs


def _copy_case_to_temp(case: EvalCase, temp_root: Path) -> Path:
    workspace = temp_root / case.case_id
    shutil.copytree(case.path, workspace)
    return workspace


def _output_dir(root: Path) -> Path:
    return root / "eval-runs" / "latest"


def _write_suite_result(root: Path, suite: EvalSuiteResult) -> None:
    output_dir = _output_dir(root)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "results.json").write_text(
        json.dumps(asdict(suite), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def run_eval_suite(
    root: Path,
    strategy: str = "baseline",
    scripted_responses: dict[str, list[dict]] | None = None,
    llm_factory: Callable[[EvalCase], LLMClient] | None = None,
    max_steps: int | None = None,
    save_workspaces: bool = False,
) -> EvalSuiteResult:
    cases = discover_eval_cases(root)
    results: list[EvalCaseResult] = []
    output_dir = _output_dir(root)
    saved_workspaces_dir = output_dir / "workspaces"
    pending_workspaces_dir = output_dir / "workspaces.pending"
    if save_workspaces:
        output_dir.mkdir(parents=True, exist_ok=True)
        if pending_workspaces_dir.exists():
            shutil.rmtree(pending_workspaces_dir)

    try:
        with tempfile.TemporaryDirectory() as tmp:
            temp_root = Path(tmp)
            for case in cases:
                workspace = _copy_case_to_temp(case, temp_root)
                if llm_factory is not None:
                    llm = llm_factory(case)
                    case_max_steps = max_steps or 5
                else:
                    if scripted_responses is not None and case.case_id in scripted_responses:
                        responses = scripted_responses[case.case_id]
                    elif case.mock_responses is not None:
                        responses = case.mock_responses
                    else:
                        responses = [
                            {
                                "schema_version": "1",
                                "action": "finish",
                                "args": {"summary": "no scripted response"},
                            }
                        ]
                    llm = MockLLM(responses)
                    case_max_steps = max_steps or max(1, len(responses))
                policy = load_policy(workspace / "specgate.toml")
                run_result = AgentRunner(
                    workspace,
                    llm,
                    policy,
                    max_steps=case_max_steps,
                    context_strategy=strategy,
                ).run()
                (
                    parse_errors,
                    blocked_actions,
                    gate_failures,
                    tool_calls,
                    successful_tool_calls,
                    gate_runs,
                ) = _count_trace_events(
                    workspace / "runs" / "latest" / "trace.jsonl"
                )
                metrics = run_result.metrics
                trust = run_result.trust
                if metrics is not None:
                    parse_errors = metrics.parse_errors
                    blocked_actions = metrics.blocked_actions
                    gate_failures = metrics.gate_failures
                    tool_calls = metrics.tool_calls
                    successful_tool_calls = metrics.successful_tool_calls
                    gate_runs = metrics.gate_runs
                elif run_result.final_gate and not run_result.final_gate.passed and gate_failures == 0:
                    gate_failures = 1
                    gate_runs = max(gate_runs, 1)
                trust_status = trust.status if trust is not None else "failed"

                use_real_expected = llm_factory is not None and (
                    case.real_expected_should_pass is not None or case.real_expected_must_block is not None
                )
                expected_passed = case.real_expected_should_pass if use_real_expected else case.expected_should_pass
                expected_match = expected_passed is None or expected_passed == run_result.passed
                expected_must_block = case.real_expected_must_block if use_real_expected else case.expected_must_block
                if expected_must_block is True:
                    expected_match = expected_match and blocked_actions > 0
                elif expected_must_block is False:
                    expected_match = expected_match and blocked_actions == 0

                final_summary = run_result.final_gate.summary if run_result.final_gate else "no gate result"
                workspace_path = None
                if save_workspaces:
                    saved_workspace = pending_workspaces_dir / case.case_id
                    saved_workspace.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copytree(workspace, saved_workspace)
                    final_workspace = saved_workspaces_dir / case.case_id
                    workspace_path = str(final_workspace.relative_to(root)).replace("\\", "/")
                results.append(
                    EvalCaseResult(
                        case_id=case.case_id,
                        strategy=strategy,
                        passed=run_result.passed,
                        expected_passed=expected_passed,
                        expected_match=expected_match,
                        steps=run_result.steps,
                        parse_errors=parse_errors,
                        blocked_actions=blocked_actions,
                        gate_failures=gate_failures,
                        context_chars_max=run_result.context_chars_max,
                        final_summary=final_summary,
                        workspace_path=workspace_path,
                        tool_calls=tool_calls,
                        successful_tool_calls=successful_tool_calls,
                        gate_runs=gate_runs,
                        trust_status=trust_status,
                    )
                )
    except Exception:
        if save_workspaces and pending_workspaces_dir.exists():
            shutil.rmtree(pending_workspaces_dir)
        raise

    if save_workspaces:
        if saved_workspaces_dir.exists():
            shutil.rmtree(saved_workspaces_dir)
        if pending_workspaces_dir.exists():
            shutil.copytree(pending_workspaces_dir, saved_workspaces_dir)
            shutil.rmtree(pending_workspaces_dir)

    suite = EvalSuiteResult(
        strategy=strategy,
        total_cases=len(results),
        passed_cases=sum(1 for result in results if result.passed),
        expected_matches=sum(1 for result in results if result.expected_match),
        results=results,
    )
    _write_suite_result(root, suite)
    return suite
