import json
import tempfile
import unittest
from pathlib import Path

from specgate.security_eval import (
    SecurityExpectation,
    SecurityExpectationResult,
    evaluate_security_expectations,
)


class SecurityEvalTests(unittest.TestCase):
    def test_empty_security_expectation_passes_with_no_findings(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            result = evaluate_security_expectations(
                expectation=SecurityExpectation(),
                workspace=workspace,
                trace_path=workspace / "runs" / "latest" / "trace.jsonl",
                run_artifacts=[],
                blocked_actions=0,
                trust_status="trusted",
                context_had_untrusted_boundary=False,
            )

        self.assertTrue(result.passed)
        self.assertEqual(result.findings, [])
        self.assertEqual(result.failures, [])
        self.assertEqual(
            result.to_dict(),
            {
                "passed": True,
                "findings": [],
                "failures": [],
                "must_not_create_violations": [],
                "must_not_leak_violations": [],
                "expected_findings": [],
                "matched_expected_findings": [],
            },
        )

    def test_security_result_round_trip_shape_is_json_serializable(self):
        result = SecurityExpectationResult(
            passed=False,
            findings=["blocked_secret_write"],
            failures=["missing expected finding: untrusted_context_boundary"],
            must_not_create_violations=[".env"],
            must_not_leak_violations=["trace.jsonl: OPENAI_API_KEY"],
            expected_findings=["blocked_secret_write", "untrusted_context_boundary"],
            matched_expected_findings=["blocked_secret_write"],
        )

        payload = result.to_dict()

        self.assertFalse(payload["passed"])
        self.assertEqual(payload["must_not_create_violations"], [".env"])
        self.assertEqual(payload["matched_expected_findings"], ["blocked_secret_write"])
        json.dumps(payload)


if __name__ == "__main__":
    unittest.main()
