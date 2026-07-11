from __future__ import annotations

from dataclasses import asdict, dataclass

from specgate.eval_runner import EvalCaseResult, EvalSuiteResult


@dataclass(frozen=True)
class BenchmarkStrategyResult:
    strategy: str
    total_cases: int
    passed_cases: int
    expected_matches: int
    avg_context_chars: float
    avg_retrieved_chunks: float
    blocked_actions: int
    approval_requests: int
    parse_errors: int
    gate_runs: int
    security: dict


@dataclass(frozen=True)
class BenchmarkResult:
    results: list[BenchmarkStrategyResult]

    def to_dict(self) -> dict[str, list[dict]]:
        return {"results": [asdict(item) for item in self.results]}


def _average(total: int, count: int) -> float:
    if count == 0:
        return 0
    return total / count


def _list_value(value: object) -> list[object]:
    if not isinstance(value, list):
        return []
    return list(value)


def _summarize_security(results: list[EvalCaseResult]) -> dict:
    security_cases = [item for item in results if item.suite == "security"]
    expected_matches = 0
    blocked_actions = 0
    must_not_create_violations = 0
    must_not_leak_violations = 0
    failed_security_expectations: list[dict[str, object]] = []

    for item in security_cases:
        blocked_actions += item.blocked_actions
        payload = item.security if isinstance(item.security, dict) else {}
        must_not_create_violations += len(_list_value(payload.get("must_not_create_violations")))
        must_not_leak_violations += len(_list_value(payload.get("must_not_leak_violations")))
        if item.expected_match is True:
            expected_matches += 1
        if payload.get("passed") is False:
            failed_security_expectations.append(
                {"case_id": item.case_id, "failures": _list_value(payload.get("failures"))}
            )

    return {
        "cases": len(security_cases),
        "expected_matches": expected_matches,
        "blocked_actions": blocked_actions,
        "must_not_create_violations": must_not_create_violations,
        "must_not_leak_violations": must_not_leak_violations,
        "failed_security_expectations": failed_security_expectations,
    }


def summarize_benchmark(suites: list[EvalSuiteResult]) -> BenchmarkResult:
    results: list[BenchmarkStrategyResult] = []
    for suite in suites:
        count = len(suite.results)
        results.append(
            BenchmarkStrategyResult(
                strategy=suite.strategy,
                total_cases=suite.total_cases,
                passed_cases=suite.passed_cases,
                expected_matches=suite.expected_matches,
                avg_context_chars=_average(sum(item.context_chars_max for item in suite.results), count),
                avg_retrieved_chunks=_average(sum(item.retrieved_chunks for item in suite.results), count),
                blocked_actions=sum(item.blocked_actions for item in suite.results),
                approval_requests=sum(item.approval_requests for item in suite.results),
                parse_errors=sum(item.parse_errors for item in suite.results),
                gate_runs=sum(item.gate_runs for item in suite.results),
                security=_summarize_security(suite.results),
            )
        )
    return BenchmarkResult(results)
