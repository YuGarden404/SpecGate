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

    def test_summarize_benchmark_includes_security_metrics(self):
        suites = [
            EvalSuiteResult(
                strategy="baseline",
                total_cases=5,
                passed_cases=2,
                expected_matches=2,
                results=[
                    EvalCaseResult(
                        "default-case",
                        "baseline",
                        True,
                        True,
                        True,
                        1,
                        0,
                        99,
                        0,
                        100,
                        "ok",
                        suite="default",
                        security={
                            "passed": False,
                            "failures": ["ignored non-security suite"],
                            "must_not_create_violations": ["ignored.txt"],
                            "must_not_leak_violations": ["ignored secret"],
                        },
                    ),
                    EvalCaseResult(
                        "security-pass",
                        "baseline",
                        True,
                        True,
                        True,
                        1,
                        0,
                        1,
                        0,
                        100,
                        "ok",
                        suite="security",
                        security={
                            "passed": True,
                            "failures": [],
                            "must_not_create_violations": ["bad.txt"],
                            "must_not_leak_violations": [],
                        },
                    ),
                    EvalCaseResult(
                        "security-payload-pass-overall-mismatch",
                        "baseline",
                        False,
                        True,
                        False,
                        1,
                        0,
                        4,
                        0,
                        100,
                        "failed non-security expectation",
                        suite="security",
                        security={
                            "passed": True,
                            "failures": [],
                            "must_not_create_violations": [],
                            "must_not_leak_violations": [],
                        },
                    ),
                    EvalCaseResult(
                        "security-fail",
                        "baseline",
                        False,
                        True,
                        False,
                        1,
                        0,
                        2,
                        0,
                        100,
                        "fail",
                        suite="security",
                        security={
                            "passed": False,
                            "failures": ["forbidden text leaked"],
                            "must_not_create_violations": ["report.html"],
                            "must_not_leak_violations": ["trace.jsonl: forbidden text #1 matched"],
                        },
                    ),
                    EvalCaseResult(
                        "security-malformed",
                        "baseline",
                        False,
                        True,
                        False,
                        1,
                        0,
                        3,
                        0,
                        100,
                        "fail",
                        suite="security",
                        security={
                            "passed": "no",
                            "failures": "not-a-list",
                            "must_not_create_violations": "not-a-list",
                            "must_not_leak_violations": None,
                        },
                    ),
                ],
            ),
            EvalSuiteResult(
                strategy="rag-select",
                total_cases=1,
                passed_cases=1,
                expected_matches=1,
                results=[
                    EvalCaseResult(
                        "default-only",
                        "rag-select",
                        True,
                        True,
                        True,
                        1,
                        0,
                        4,
                        0,
                        100,
                        "ok",
                        suite="default",
                    )
                ],
            ),
        ]

        summary = summarize_benchmark(suites)
        summary_data = summary.to_dict()["results"]

        self.assertIn("security", summary_data[0])
        self.assertEqual(
            summary_data[0]["security"],
            {
                "cases": 4,
                "expected_matches": 1,
                "blocked_actions": 10,
                "must_not_create_violations": 2,
                "must_not_leak_violations": 1,
                "failed_security_expectations": [
                    {"case_id": "security-fail", "failures": ["forbidden text leaked"]}
                ],
            },
        )
        self.assertIn("security", summary_data[1])
        self.assertEqual(
            summary_data[1]["security"],
            {
                "cases": 0,
                "expected_matches": 0,
                "blocked_actions": 0,
                "must_not_create_violations": 0,
                "must_not_leak_violations": 0,
                "failed_security_expectations": [],
            },
        )


if __name__ == "__main__":
    unittest.main()
