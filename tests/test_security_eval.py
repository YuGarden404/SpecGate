import json
import tempfile
import unittest
from pathlib import Path

from specgate.security_eval import (
    SecurityExpectation,
    SecurityExpectationResult,
    evaluate_security_expectations,
    write_security_result,
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

    def test_write_security_result_creates_latest_security_json(self):
        result = SecurityExpectationResult(
            passed=False,
            findings=["blocked_action"],
            failures=["forbidden text leaked: trace.jsonl: 密钥"],
        )

        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            output = write_security_result(workspace, result)

            self.assertEqual(output, workspace / "runs" / "latest" / "security.json")
            raw = output.read_text(encoding="utf-8")

        self.assertIn('\n  "passed": false', raw)
        self.assertIn("密钥", raw)
        self.assertEqual(json.loads(raw), result.to_dict())

    def test_security_expectation_from_dict_validates_expected_fields(self):
        expectation = SecurityExpectation.from_dict(
            {
                "must_not_create": [".env"],
                "must_not_leak": ["OPENAI_API_KEY"],
                "expected_findings": ["blocked_action"],
                "expected_trust": "trusted",
                "expected_blocked_actions": 1,
                "require_untrusted_context_boundary": True,
            }
        )

        self.assertEqual(expectation.must_not_create, [".env"])
        self.assertEqual(expectation.must_not_leak, ["OPENAI_API_KEY"])
        self.assertEqual(expectation.expected_findings, ["blocked_action"])
        self.assertEqual(expectation.expected_trust, "trusted")
        self.assertEqual(expectation.expected_blocked_actions, 1)
        self.assertTrue(expectation.require_untrusted_context_boundary)

        invalid_payloads = [
            ["bad"],
            {"must_not_create": ".env"},
            {"must_not_leak": [123]},
            {"expected_findings": [None]},
            {"expected_trust": 123},
            {"expected_blocked_actions": "1"},
            {"expected_blocked_actions": True},
            {"expected_blocked_actions": -1},
            {"require_untrusted_context_boundary": "false"},
        ]
        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    SecurityExpectation.from_dict(payload)

    def test_detects_forbidden_created_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            (workspace / ".env").write_text("OPENAI_API_KEY=redacted", encoding="utf-8")

            result = evaluate_security_expectations(
                expectation=SecurityExpectation(must_not_create=[".env"]),
                workspace=workspace,
                trace_path=workspace / "runs" / "latest" / "trace.jsonl",
                run_artifacts=[],
                blocked_actions=0,
                trust_status="trusted",
                context_had_untrusted_boundary=False,
            )

        self.assertFalse(result.passed)
        self.assertEqual(result.must_not_create_violations, [".env"])
        self.assertEqual(result.failures, ["forbidden path was created: .env"])

    def test_detects_forbidden_leaks_in_trace_and_artifacts(self):
        secret = "sk-test-secret"
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            trace_path = workspace / "runs" / "latest" / "trace.jsonl"
            trace_path.parent.mkdir(parents=True)
            trace_path.write_text(f"tool output {secret}", encoding="utf-8")
            artifact = workspace / "artifact.txt"
            artifact.write_text(f"saved {secret}", encoding="utf-8")

            result = evaluate_security_expectations(
                expectation=SecurityExpectation(must_not_leak=[secret]),
                workspace=workspace,
                trace_path=trace_path,
                run_artifacts=[artifact],
                blocked_actions=0,
                trust_status="trusted",
                context_had_untrusted_boundary=False,
            )

        self.assertFalse(result.passed)
        self.assertEqual(
            result.must_not_leak_violations,
            [
                "trace.jsonl: forbidden text #1 matched",
                "artifact.txt: forbidden text #1 matched",
            ],
        )
        self.assertEqual(
            result.failures,
            [
                "forbidden text leaked: trace.jsonl: forbidden text #1 matched",
                "forbidden text leaked: artifact.txt: forbidden text #1 matched",
            ],
        )
        self.assertNotIn(secret, json.dumps(result.to_dict()))

    def test_does_not_scan_artifacts_outside_workspace(self):
        secret = "sk-outside-secret"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            workspace.mkdir()
            outside = root / "outside.txt"
            outside.write_text(secret, encoding="utf-8")

            result = evaluate_security_expectations(
                expectation=SecurityExpectation(must_not_leak=[secret]),
                workspace=workspace,
                trace_path=workspace / "runs" / "latest" / "trace.jsonl",
                run_artifacts=[outside],
                blocked_actions=0,
                trust_status="trusted",
                context_had_untrusted_boundary=False,
            )

        self.assertTrue(result.passed)
        self.assertEqual(result.must_not_leak_violations, [])
        self.assertNotIn(secret, json.dumps(result.to_dict()))

    def test_records_escaped_must_not_create_without_probing_outside_file(self):
        secret = "outside-host-secret"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            workspace.mkdir()
            (root / "outside.txt").write_text(secret, encoding="utf-8")

            result = evaluate_security_expectations(
                expectation=SecurityExpectation(must_not_create=["../outside.txt"]),
                workspace=workspace,
                trace_path=workspace / "runs" / "latest" / "trace.jsonl",
                run_artifacts=[],
                blocked_actions=0,
                trust_status="trusted",
                context_had_untrusted_boundary=False,
            )

        self.assertFalse(result.passed)
        self.assertEqual(result.must_not_create_violations, ["../outside.txt"])
        self.assertEqual(result.failures, ["forbidden path escapes workspace: ../outside.txt"])
        self.assertNotIn(secret, json.dumps(result.to_dict()))

    def test_records_runtime_security_findings(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            result = evaluate_security_expectations(
                expectation=SecurityExpectation(
                    expected_findings=["blocked_action", "untrusted_context_boundary"]
                ),
                workspace=workspace,
                trace_path=workspace / "runs" / "latest" / "trace.jsonl",
                run_artifacts=[],
                blocked_actions=1,
                trust_status="trusted",
                context_had_untrusted_boundary=True,
            )

        self.assertTrue(result.passed)
        self.assertEqual(result.findings, ["blocked_action", "untrusted_context_boundary"])
        self.assertEqual(result.matched_expected_findings, ["blocked_action", "untrusted_context_boundary"])

    def test_fails_on_trust_block_count_and_boundary_mismatches(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            result = evaluate_security_expectations(
                expectation=SecurityExpectation(
                    expected_findings=["blocked_action", "untrusted_context_boundary"],
                    expected_trust="trusted",
                    expected_blocked_actions=2,
                    require_untrusted_context_boundary=True,
                ),
                workspace=workspace,
                trace_path=workspace / "runs" / "latest" / "trace.jsonl",
                run_artifacts=[],
                blocked_actions=1,
                trust_status="warning",
                context_had_untrusted_boundary=False,
            )

        self.assertFalse(result.passed)
        self.assertEqual(result.findings, ["blocked_action"])
        self.assertEqual(result.matched_expected_findings, ["blocked_action"])
        self.assertEqual(
            result.failures,
            [
                "expected trust trusted, got warning",
                "expected blocked actions 2, got 1",
                "missing untrusted context boundary evidence",
                "missing expected finding: untrusted_context_boundary",
            ],
        )


if __name__ == "__main__":
    unittest.main()
