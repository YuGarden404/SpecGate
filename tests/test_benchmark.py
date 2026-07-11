import unittest

from specgate.benchmark import summarize_benchmark
from specgate.eval_runner import EvalCaseResult, EvalSuiteResult


class BenchmarkTests(unittest.TestCase):
    def test_summarize_benchmark_collects_strategy_metrics(self):
        suites = [
            EvalSuiteResult(
                strategy="baseline",
                total_cases=2,
                passed_cases=1,
                expected_matches=1,
                results=[
                    EvalCaseResult("a", "baseline", True, True, True, 1, 0, 0, 0, 1000, "ok", retrieved_chunks=0),
                    EvalCaseResult("b", "baseline", False, True, False, 2, 1, 1, 1, 1200, "fail", retrieved_chunks=0),
                ],
            ),
            EvalSuiteResult(
                strategy="rag-select",
                total_cases=2,
                passed_cases=2,
                expected_matches=2,
                results=[
                    EvalCaseResult("a", "rag-select", True, True, True, 1, 0, 0, 0, 900, "ok", retrieved_chunks=2),
                    EvalCaseResult("b", "rag-select", True, True, True, 2, 0, 0, 0, 1100, "ok", retrieved_chunks=3),
                ],
            ),
        ]

        summary = summarize_benchmark(suites)

        self.assertEqual([item.strategy for item in summary.results], ["baseline", "rag-select"])
        self.assertEqual(summary.results[1].passed_cases, 2)
        self.assertEqual(summary.results[1].avg_retrieved_chunks, 2.5)

    def test_summarize_benchmark_handles_empty_suite_without_division_error(self):
        suite = EvalSuiteResult(strategy="baseline", total_cases=0, passed_cases=0, expected_matches=0, results=[])

        summary = summarize_benchmark([suite])

        self.assertEqual(summary.results[0].avg_context_chars, 0)
        self.assertEqual(summary.results[0].avg_retrieved_chunks, 0)


if __name__ == "__main__":
    unittest.main()
