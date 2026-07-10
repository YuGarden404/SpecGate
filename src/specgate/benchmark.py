from __future__ import annotations

from dataclasses import asdict, dataclass

from specgate.eval_runner import EvalSuiteResult


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


@dataclass(frozen=True)
class BenchmarkResult:
    results: list[BenchmarkStrategyResult]

    def to_dict(self) -> dict[str, list[dict]]:
        return {"results": [asdict(item) for item in self.results]}


def _average(total: int, count: int) -> float:
    if count == 0:
        return 0
    return total / count


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
            )
        )
    return BenchmarkResult(results)
