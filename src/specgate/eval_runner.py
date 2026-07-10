from __future__ import annotations

import json
import shutil
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

from specgate.config import load_policy
from specgate.llm import MockLLM
from specgate.runner import AgentRunner


@dataclass(frozen=True)
class EvalCase:
    case_id: str
    title: str
    category: str
    path: Path
    expected_should_pass: bool | None
    expected_must_block: bool | None


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
        case_id = str(meta["id"])
        cases.append(
            EvalCase(
                case_id=case_id,
                title=str(meta.get("title", case_id)),
                category=str(meta.get("category", "uncategorized")),
                path=item,
                expected_should_pass=expected.get("should_pass"),
                expected_must_block=expected.get("must_block"),
            )
        )
    return cases


def _count_trace_events(trace_path: Path) -> tuple[int, int, int]:
    parse_errors = 0
    blocked_actions = 0
    gate_failures = 0

    if not trace_path.exists():
        return parse_errors, blocked_actions, gate_failures

    for line in trace_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        event = json.loads(line)
        event_type = event.get("event_type")
        payload = event.get("payload", {})
        if event_type == "parse_error":
            parse_errors += 1
        elif event_type == "tool_result":
            result = payload.get("result", {})
            if result.get("blocked"):
                blocked_actions += 1
        elif event_type == "gate_result" and payload.get("passed") is False:
            gate_failures += 1

    return parse_errors, blocked_actions, gate_failures


def _copy_case_to_temp(case: EvalCase, temp_root: Path) -> Path:
    workspace = temp_root / case.case_id
    shutil.copytree(case.path, workspace)
    return workspace


def _write_suite_result(root: Path, suite: EvalSuiteResult) -> None:
    output_dir = root / "eval-runs" / "latest"
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "results.json").write_text(
        json.dumps(asdict(suite), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def run_eval_suite(
    root: Path,
    strategy: str = "baseline",
    scripted_responses: dict[str, list[dict]] | None = None,
) -> EvalSuiteResult:
    cases = discover_eval_cases(root)
    responses_by_case = scripted_responses or {}
    results: list[EvalCaseResult] = []

    with tempfile.TemporaryDirectory() as tmp:
        temp_root = Path(tmp)
        for case in cases:
            workspace = _copy_case_to_temp(case, temp_root)
            responses = responses_by_case.get(
                case.case_id,
                [
                    {
                        "schema_version": "1",
                        "action": "finish",
                        "args": {"summary": "no scripted response"},
                    }
                ],
            )
            policy = load_policy(workspace / "specgate.toml")
            run_result = AgentRunner(
                workspace,
                MockLLM(responses),
                policy,
                max_steps=max(1, len(responses)),
                context_strategy=strategy,
            ).run()
            parse_errors, blocked_actions, gate_failures = _count_trace_events(
                workspace / "runs" / "latest" / "trace.jsonl"
            )
            if run_result.final_gate and not run_result.final_gate.passed and gate_failures == 0:
                gate_failures = 1

            expected_passed = case.expected_should_pass
            expected_match = expected_passed is None or expected_passed == run_result.passed
            if case.expected_must_block is True:
                expected_match = expected_match and blocked_actions > 0
            elif case.expected_must_block is False:
                expected_match = expected_match and blocked_actions == 0

            final_summary = run_result.final_gate.summary if run_result.final_gate else "no gate result"
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
                )
            )

    suite = EvalSuiteResult(
        strategy=strategy,
        total_cases=len(results),
        passed_cases=sum(1 for result in results if result.passed),
        expected_matches=sum(1 for result in results if result.expected_match),
        results=results,
    )
    _write_suite_result(root, suite)
    return suite
