import io
import json
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from specgate import cli
from specgate.approvals import ApprovalQueue, PendingApproval, approval_queue_path
from specgate.cli import main, run_mock_demo, run_real_llm
from specgate.llm import LLMProviderError


class CliTests(unittest.TestCase):
    def _write_eval_case(self, root: Path, case_id: str = "real-case") -> Path:
        case = root / case_id
        case.mkdir()
        (case / "case.json").write_text(
            json.dumps(
                {
                    "id": case_id,
                    "title": "Real provider case",
                    "category": "generation",
                    "expected": {"should_pass": True, "must_block": False},
                }
            ),
            encoding="utf-8",
        )
        (case / "TASK_SPEC.md").write_text("Create a searchable detail page.", encoding="utf-8")
        (case / "CHECKLIST.md").write_text("- Must include checklist\n", encoding="utf-8")
        (case / "index.html").write_text("draft", encoding="utf-8")
        (case / "specgate.toml").write_text(
            (
                "[policy]\n"
                'allowed_actions=["write_file","finish"]\n'
                'allowed_read_paths=["TASK_SPEC.md","CHECKLIST.md","index.html"]\n'
                'allowed_write_paths=["index.html"]\n'
            ),
            encoding="utf-8",
        )
        return case

    def test_run_mock_demo_creates_artifact_and_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "TASK_SPEC.md").write_text("# 页面设计\n生成 AI for Coding 知识导航", encoding="utf-8")
            (root / "CHECKLIST.md").write_text("- 必须包含 Spec\n- 必须包含 Gate\n", encoding="utf-8")

            exit_code = run_mock_demo(root)

            self.assertEqual(exit_code, 0)
            self.assertTrue((root / "index.html").exists())
            self.assertTrue((root / "reports" / "latest" / "index.html").exists())

            html = (root / "index.html").read_text(encoding="utf-8")
            self.assertIn("AI for Coding 知识图谱", html)
            self.assertIn('type="search"', html)
            self.assertIn("knowledgeDetail", html)
            self.assertGreaterEqual(html.count('class="node'), 10)
            self.assertIn("function filterNodes", html)
            self.assertIn("function showDetail", html)
            self.assertIn("function highlightRelations", html)

    def test_run_mock_demo_records_requested_governance_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "TASK_SPEC.md").write_text("# task", encoding="utf-8")
            (root / "CHECKLIST.md").write_text("- Must include Spec\n- Must include Gate\n", encoding="utf-8")

            exit_code = run_mock_demo(root, governance_profile="review")

            self.assertEqual(exit_code, 0)
            trace_text = (root / "runs" / "latest" / "trace.jsonl").read_text(encoding="utf-8")
            report_text = (root / "reports" / "latest" / "index.html").read_text(encoding="utf-8")
            self.assertTrue('"profile": "review"' in trace_text or "Profile: review" in report_text)

    def test_run_mock_demo_rejects_unknown_governance_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "TASK_SPEC.md").write_text("# task", encoding="utf-8")
            (root / "CHECKLIST.md").write_text("", encoding="utf-8")

            with self.assertRaises(SystemExit) as raised:
                main(["run-mock-demo", str(root), "--governance-profile", "unsafe"])

            self.assertEqual(raised.exception.code, 2)

    def test_run_mock_demo_uses_workspace_config_when_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "TASK_SPEC.md").write_text("# task", encoding="utf-8")
            (root / "CHECKLIST.md").write_text("", encoding="utf-8")
            (root / "specgate.toml").write_text(
                "\n".join(
                    [
                        "[policy]",
                        'allowed_actions = ["write_file", "replace_file", "read_file", "list_files", "finish"]',
                        'allowed_read_paths = ["TASK_SPEC.md", "CHECKLIST.md", "index.html"]',
                        'allowed_write_paths = ["other.html"]',
                    ]
                ),
                encoding="utf-8",
            )

            exit_code = run_mock_demo(root)

            self.assertEqual(exit_code, 1)
            self.assertFalse((root / "index.html").exists())
            trace_text = (root / "runs" / "latest" / "trace.jsonl").read_text(encoding="utf-8")
            self.assertIn("write path not allowed", trace_text)

    def test_load_workspace_settings_includes_workspace_governance(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "specgate.toml").write_text(
                "\n".join(
                    [
                        "[policy]",
                        'allowed_actions = ["write_file", "finish"]',
                        'allowed_read_paths = ["TASK_SPEC.md"]',
                        'allowed_write_paths = ["README.md"]',
                        "",
                        "[governance]",
                        'profile = "review"',
                        'review_actions = ["write_file"]',
                        'review_paths = ["README.md"]',
                    ]
                ),
                encoding="utf-8",
            )

            settings = cli._load_workspace_settings(root)

            self.assertEqual(settings.governance.profile, "review")
            self.assertEqual(settings.governance.review_actions, {"write_file"})
            self.assertEqual(settings.governance.review_paths, {"README.md"})

    def test_run_mock_demo_uses_workspace_governance_profile_when_not_overridden(self):
        captured = {}

        class RecordingRunner:
            def __init__(self, root, llm, policy, max_steps=5, governance_profile=None, governance_config=None):
                captured["governance_profile"] = governance_profile
                captured["governance_config"] = governance_config

            def run(self):
                from specgate.gate import GateCheck, GateResult
                from specgate.runner import RunResult

                return RunResult(
                    True,
                    1,
                    GateResult(True, [GateCheck("ok", True, "ok")], [], "Gate passed"),
                    profile="review",
                )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "specgate.toml").write_text(
                "\n".join(
                    [
                        "[policy]",
                        'allowed_actions = ["write_file", "finish"]',
                        'allowed_read_paths = ["TASK_SPEC.md"]',
                        'allowed_write_paths = ["index.html"]',
                        "",
                        "[governance]",
                        'profile = "review"',
                        'review_actions = ["write_file"]',
                    ]
                ),
                encoding="utf-8",
            )

            with patch("specgate.cli.AgentRunner", RecordingRunner):
                exit_code = run_mock_demo(root)

            self.assertEqual(exit_code, 0)
            self.assertIsNone(captured["governance_profile"])
            self.assertEqual(captured["governance_config"].profile, "review")

    def test_run_mock_demo_cli_explicit_governance_profile_overrides_workspace(self):
        captured = {}

        class RecordingRunner:
            def __init__(self, root, llm, policy, max_steps=5, governance_profile=None, governance_config=None):
                captured["governance_profile"] = governance_profile
                captured["governance_config"] = governance_config

            def run(self):
                from specgate.gate import GateCheck, GateResult
                from specgate.runner import RunResult

                return RunResult(
                    True,
                    1,
                    GateResult(True, [GateCheck("ok", True, "ok")], [], "Gate passed"),
                    profile="strict",
                )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "specgate.toml").write_text(
                "\n".join(
                    [
                        "[policy]",
                        'allowed_actions = ["write_file", "finish"]',
                        'allowed_read_paths = ["TASK_SPEC.md"]',
                        'allowed_write_paths = ["index.html"]',
                        "",
                        "[governance]",
                        'profile = "review"',
                        'review_actions = ["write_file"]',
                    ]
                ),
                encoding="utf-8",
            )

            with patch("specgate.cli.AgentRunner", RecordingRunner):
                exit_code = main(["run-mock-demo", str(root), "--governance-profile", "strict"])

            self.assertEqual(exit_code, 0)
            self.assertEqual(captured["governance_profile"], "strict")
            self.assertEqual(captured["governance_config"].profile, "review")

    def test_approvals_list_empty_queue_reports_no_pending_approvals(self):
        with tempfile.TemporaryDirectory() as tmp:
            with redirect_stdout(io.StringIO()) as output:
                code = main(["approvals", "list", tmp])

            self.assertEqual(code, 0)
            self.assertIn("no pending approvals", output.getvalue())

    def test_approvals_list_prints_pending_approval_details(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            secret = "sk-test-secret-1234567890"
            ApprovalQueue(
                [
                    PendingApproval(
                        id="approval-step-2",
                        step=2,
                        action="replace_file",
                        path="README.md",
                        risk_level="review",
                        reason="replace_file on protected path requires human review",
                        profile="review",
                        arguments_preview={"content": secret},
                    )
                ]
            ).write(approval_queue_path(root))

            with redirect_stdout(io.StringIO()) as output:
                code = main(["approvals", "list", tmp])

            stdout = output.getvalue()
            self.assertEqual(code, 0)
            self.assertIn("id", stdout)
            self.assertIn("status", stdout)
            self.assertIn("action", stdout)
            self.assertIn("path", stdout)
            self.assertIn("reason", stdout)
            self.assertIn("approval-step-2", stdout)
            self.assertIn("pending", stdout)
            self.assertIn("replace_file", stdout)
            self.assertIn("README.md", stdout)
            self.assertIn("requires human review", stdout)
            self.assertNotIn("arguments_preview", stdout)
            self.assertNotIn("content", stdout)
            self.assertNotIn("sk-test-secret", stdout)

    def test_approvals_approve_marks_pending_item_without_printing_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ApprovalQueue(
                [
                    PendingApproval(
                        id="approval-step-1",
                        step=1,
                        action="replace_file",
                        path="README.md",
                        risk_level="review",
                        reason="requires human review",
                        profile="review",
                        status="pending",
                        action_payload={
                            "schema_version": "1",
                            "action": "replace_file",
                            "args": {"path": "README.md", "content": "secret sk-test-secret-1234567890"},
                        },
                    )
                ]
            ).write(approval_queue_path(root))

            with redirect_stdout(io.StringIO()) as output:
                code = main(["approvals", "approve", tmp, "approval-step-1"])

            queue = ApprovalQueue.read(approval_queue_path(root))
            self.assertEqual(code, 0)
            self.assertEqual(queue.approvals[0].status, "approved")
            self.assertIsNotNone(queue.approvals[0].decided_at)
            self.assertNotIn("sk-test-secret", output.getvalue())

    def test_approvals_deny_marks_pending_item_with_reason(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ApprovalQueue(
                [
                    PendingApproval(
                        id="approval-step-1",
                        step=1,
                        action="replace_file",
                        path="README.md",
                        risk_level="review",
                        reason="requires human review",
                        profile="review",
                        status="pending",
                    )
                ]
            ).write(approval_queue_path(root))

            with redirect_stdout(io.StringIO()) as output:
                code = main(["approvals", "deny", tmp, "approval-step-1", "--reason", "too broad"])

            queue = ApprovalQueue.read(approval_queue_path(root))
            self.assertEqual(code, 0)
            self.assertEqual(queue.approvals[0].status, "denied")
            self.assertEqual(queue.approvals[0].decision_reason, "too broad")
            self.assertIn("denied approval-step-1", output.getvalue())

    def test_approvals_approve_rejects_missing_item_cleanly(self):
        with tempfile.TemporaryDirectory() as tmp:
            with redirect_stdout(io.StringIO()) as output:
                code = main(["approvals", "approve", tmp, "missing"])

            self.assertNotEqual(code, 0)
            self.assertIn("could not update approval", output.getvalue())
            self.assertNotIn("Traceback", output.getvalue())

    def test_approvals_list_prints_decision_reason_without_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ApprovalQueue(
                [
                    PendingApproval(
                        id="approval-step-1",
                        step=1,
                        action="replace_file",
                        path="README.md",
                        risk_level="review",
                        reason="requires human review",
                        profile="review",
                        status="denied",
                        decision_reason="too broad",
                        action_payload={"args": {"content": "secret sk-test-secret-1234567890"}},
                    )
                ]
            ).write(approval_queue_path(root))

            with redirect_stdout(io.StringIO()) as output:
                code = main(["approvals", "list", tmp])

            text = output.getvalue()
            self.assertEqual(code, 0)
            self.assertIn("decision_reason", text)
            self.assertIn("too broad", text)
            self.assertNotIn("sk-test-secret", text)

    def test_approvals_list_malformed_queue_reports_clean_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            queue_path = approval_queue_path(root)
            queue_path.parent.mkdir(parents=True)
            queue_path.write_text(
                json.dumps({"approvals": [{"sk-test-secret-1234567890": "value"}]}),
                encoding="utf-8",
            )

            stdout = io.StringIO()
            stderr = io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                code = main(["approvals", "list", tmp])

            text = stdout.getvalue() + stderr.getvalue()
            self.assertNotEqual(code, 0)
            self.assertIn("could not read pending approvals", text)
            self.assertNotIn("sk-test-secret", text)
            self.assertNotIn("Traceback", text)

    def test_approvals_list_malformed_field_type_reports_clean_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            queue_path = approval_queue_path(root)
            queue_path.parent.mkdir(parents=True)
            queue_path.write_text(
                json.dumps(
                    {
                        "approvals": [
                            {
                                "id": {"secret": "sk-test-secret-1234567890"},
                                "step": 1,
                                "action": "replace_file",
                                "path": "README.md",
                                "risk_level": "review",
                                "reason": "requires human review",
                                "profile": "review",
                                "status": "pending",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            stdout = io.StringIO()
            stderr = io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                code = main(["approvals", "list", tmp])

            text = stdout.getvalue() + stderr.getvalue()
            self.assertNotEqual(code, 0)
            self.assertIn("could not read pending approvals", text)
            self.assertNotIn("sk-test-secret", text)
            self.assertNotIn("Traceback", text)

    def test_credentials_cli_status_set_and_clear(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / ".env"

            with redirect_stdout(io.StringIO()):
                self.assertEqual(
                    main(["credentials", "set", "openai", "--value", "sk-test-secret-123456", "--env-file", str(env_file)]),
                    0,
                )
                self.assertEqual(main(["credentials", "status", "openai", "--env-file", str(env_file)]), 0)
                self.assertEqual(main(["credentials", "clear", "openai", "--env-file", str(env_file)]), 0)
            self.assertFalse(env_file.exists() and "OPENAI_API_KEY" in env_file.read_text(encoding="utf-8"))

    def test_eval_cli_runs_mock_suite_and_writes_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            case = root / "basic"
            case.mkdir()
            (case / "case.json").write_text(
                '{"id":"basic","title":"Basic","category":"generation","expected":{"should_pass":false,"must_block":false}}',
                encoding="utf-8",
            )
            (case / "TASK_SPEC.md").write_text("任务", encoding="utf-8")
            (case / "CHECKLIST.md").write_text("- 必须包含 Missing\n", encoding="utf-8")
            (case / "index.html").write_text("<html></html>", encoding="utf-8")
            (case / "specgate.toml").write_text(
                '[policy]\nallowed_actions=["finish"]\nallowed_read_paths=["TASK_SPEC.md","CHECKLIST.md","index.html"]\nallowed_write_paths=["index.html"]\n',
                encoding="utf-8",
            )

            with redirect_stdout(io.StringIO()) as output:
                code = main(["eval", str(root), "--context-strategy", "compressed"])

            self.assertEqual(code, 0)
            stdout = output.getvalue()
            self.assertIn("strategy=compressed", stdout)
            self.assertIn("cases=1", stdout)
            self.assertIn("expected_matches=1", stdout)
            results_path = root / "eval-runs" / "latest" / "results.json"
            self.assertTrue(results_path.exists())
            results = json.loads(results_path.read_text(encoding="utf-8"))
            self.assertEqual(results["strategy"], "compressed")
            self.assertEqual(results["total_cases"], 1)
            self.assertEqual(results["expected_matches"], 1)

    def test_eval_cli_filters_by_suite(self):
        calls = []

        def fake_run_eval_suite(*args, **kwargs):
            calls.append((args, kwargs))
            return SimpleNamespace(
                strategy=kwargs["strategy"],
                total_cases=1,
                passed_cases=1,
                expected_matches=1,
                results=[],
            )

        with tempfile.TemporaryDirectory() as tmp:
            with patch("specgate.cli.run_eval_suite", side_effect=fake_run_eval_suite), redirect_stdout(io.StringIO()):
                code = main(["eval", tmp, "--suite", "security"])

        self.assertEqual(code, 0)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1]["suite"], "security")

    def test_benchmark_cli_runs_multiple_mock_strategies_and_writes_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            case = root / "basic"
            case.mkdir()
            (case / "case.json").write_text(
                json.dumps(
                    {
                        "id": "basic",
                        "title": "Basic",
                        "category": "generation",
                        "expected": {"should_pass": True, "must_block": False},
                        "mock_responses": [
                            {"schema_version": "1", "action": "finish", "args": {"summary": "done"}}
                        ],
                    }
                ),
                encoding="utf-8",
            )
            (case / "TASK_SPEC.md").write_text("Create a search details page.", encoding="utf-8")
            (case / "CHECKLIST.md").write_text("- Must include Search\n- Must include Detail\n", encoding="utf-8")
            (case / "index.html").write_text(
                '<!doctype html><html><head><meta name="viewport" content="width=device-width">'
                '<title>Task</title></head><body><input type="search">Search Detail</body></html>',
                encoding="utf-8",
            )
            (case / "specgate.toml").write_text(
                '[policy]\nallowed_actions=["finish"]\n'
                'allowed_read_paths=["TASK_SPEC.md","CHECKLIST.md","index.html"]\n'
                'allowed_write_paths=["index.html"]\n',
                encoding="utf-8",
            )

            with redirect_stdout(io.StringIO()) as output:
                code = main(["benchmark", str(root), "--strategies", "baseline", "rag-select"])

            self.assertEqual(code, 0)
            self.assertIn("SpecGate benchmark finished", output.getvalue())
            benchmark_path = root / "eval-runs" / "latest" / "benchmark.json"
            self.assertTrue(benchmark_path.exists())
            self.assertTrue((root / "eval-runs" / "latest" / "results-baseline.json").exists())
            self.assertTrue((root / "eval-runs" / "latest" / "results-rag-select.json").exists())
            data = json.loads(benchmark_path.read_text(encoding="utf-8"))
            self.assertEqual([item["strategy"] for item in data["results"]], ["baseline", "rag-select"])
            self.assertEqual(data["results"][0]["total_cases"], 1)

    def test_benchmark_cli_filters_by_suite(self):
        calls = []

        def fake_run_eval_suite(*args, **kwargs):
            calls.append((args, kwargs))
            return SimpleNamespace(
                strategy=kwargs["strategy"],
                total_cases=1,
                passed_cases=1,
                expected_matches=1,
                results=[],
            )

        with tempfile.TemporaryDirectory() as tmp:
            with patch("specgate.cli.run_eval_suite", side_effect=fake_run_eval_suite), redirect_stdout(io.StringIO()):
                code = main(["benchmark", tmp, "--suite", "security", "--strategies", "baseline", "rag-select"])

        self.assertEqual(code, 0)
        self.assertEqual([call[1]["strategy"] for call in calls], ["baseline", "rag-select"])
        self.assertEqual([call[1]["suite"] for call in calls], ["security", "security"])

    def test_repository_security_benchmark_smoke(self):
        with tempfile.TemporaryDirectory() as tmp:
            temp_cases = Path(tmp) / "eval_cases"
            shutil.copytree(
                Path("examples/eval_cases"),
                temp_cases,
                ignore=shutil.ignore_patterns("eval-runs"),
            )

            with redirect_stdout(io.StringIO()) as output:
                code = main(["benchmark", str(temp_cases), "--suite", "security", "--strategies", "baseline"])

            self.assertEqual(code, 0)
            self.assertIn("SpecGate benchmark finished", output.getvalue())
            benchmark_path = temp_cases / "eval-runs" / "latest" / "benchmark.json"
            self.assertTrue(benchmark_path.exists())
            benchmark_text = benchmark_path.read_text(encoding="utf-8")
            self.assertNotIn("sk-rag-injection", benchmark_text)
            self.assertNotIn("sk-hidden-html", benchmark_text)
            self.assertNotIn("sk-tool-result", benchmark_text)
            data = json.loads(benchmark_text)
            self.assertGreaterEqual(data["results"][0]["security"]["cases"], 6)

    def test_benchmark_cli_returns_failure_when_any_strategy_misses_expected_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            case = root / "failing"
            case.mkdir()
            (case / "case.json").write_text(
                json.dumps(
                    {
                        "id": "failing",
                        "title": "Failing",
                        "category": "generation",
                        "expected": {"should_pass": True, "must_block": False},
                        "mock_responses": [
                            {"schema_version": "1", "action": "finish", "args": {"summary": "done"}}
                        ],
                    }
                ),
                encoding="utf-8",
            )
            (case / "TASK_SPEC.md").write_text("Create a search details page.", encoding="utf-8")
            (case / "CHECKLIST.md").write_text("- Must include MissingTerm\n", encoding="utf-8")
            (case / "index.html").write_text("<html></html>", encoding="utf-8")
            (case / "specgate.toml").write_text(
                '[policy]\nallowed_actions=["finish"]\n'
                'allowed_read_paths=["TASK_SPEC.md","CHECKLIST.md","index.html"]\n'
                'allowed_write_paths=["index.html"]\n',
                encoding="utf-8",
            )

            with redirect_stdout(io.StringIO()):
                code = main(["benchmark", str(root), "--strategies", "baseline"])

            self.assertEqual(code, 1)
            benchmark_path = root / "eval-runs" / "latest" / "benchmark.json"
            self.assertTrue(benchmark_path.exists())
            data = json.loads(benchmark_path.read_text(encoding="utf-8"))
            self.assertEqual(data["results"][0]["expected_matches"], 0)

    def test_eval_cli_uses_case_governance_profile_when_not_overridden(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            case = root / "review-case"
            case.mkdir()
            (case / "case.json").write_text(
                json.dumps(
                    {
                        "id": "review-case",
                        "title": "Review case",
                        "category": "governance",
                        "expected": {"should_pass": False, "must_block": False},
                        "mock_responses": [
                            {
                                "schema_version": "1",
                                "action": "replace_file",
                                "args": {"path": "README.md", "content": "updated"},
                            },
                            {
                                "schema_version": "1",
                                "action": "finish",
                                "args": {"summary": "done"},
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            (case / "TASK_SPEC.md").write_text("Update README.md.", encoding="utf-8")
            (case / "README.md").write_text("draft", encoding="utf-8")
            (case / "specgate.toml").write_text(
                (
                    "[policy]\n"
                    'allowed_actions=["replace_file","finish"]\n'
                    'allowed_read_paths=["TASK_SPEC.md"]\n'
                    'allowed_write_paths=["README.md"]\n'
                    "[governance]\n"
                    'profile="review"\n'
                    'review_actions=["replace_file"]\n'
                    'review_paths=["README.md"]\n'
                ),
                encoding="utf-8",
            )

            with redirect_stdout(io.StringIO()):
                code = main(["eval", str(root)])

            self.assertEqual(code, 0)
            results_path = root / "eval-runs" / "latest" / "results.json"
            self.assertTrue(results_path.exists())
            results = json.loads(results_path.read_text(encoding="utf-8"))
            self.assertEqual(results["expected_matches"], 1)
            self.assertEqual(results["results"][0]["pending_approvals"], 1)

    def test_eval_cli_save_workspaces_writes_case_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            case = root / "basic"
            case.mkdir()
            (case / "case.json").write_text(
                json.dumps(
                    {
                        "id": "basic",
                        "title": "Basic",
                        "category": "generation",
                        "expected": {"should_pass": False, "must_block": False},
                    }
                ),
                encoding="utf-8",
            )
            (case / "TASK_SPEC.md").write_text("Task", encoding="utf-8")
            (case / "CHECKLIST.md").write_text("- Must include Missing\n", encoding="utf-8")
            (case / "index.html").write_text("<html></html>", encoding="utf-8")
            (case / "specgate.toml").write_text(
                '[policy]\nallowed_actions=["finish"]\nallowed_read_paths=["TASK_SPEC.md","CHECKLIST.md","index.html"]\nallowed_write_paths=["index.html"]\n',
                encoding="utf-8",
            )

            with redirect_stdout(io.StringIO()):
                code = main(["eval", str(root), "--save-workspaces"])

            self.assertEqual(code, 0)
            self.assertTrue((root / "eval-runs" / "latest" / "workspaces" / "basic" / "index.html").exists())

    def test_eval_cli_returns_failure_when_no_cases_exist(self):
        with tempfile.TemporaryDirectory() as tmp:
            empty_root = Path(tmp) / "empty"
            empty_root.mkdir()
            missing_root = Path(tmp) / "missing"

            for root in (empty_root, missing_root):
                with self.subTest(root=root), redirect_stdout(io.StringIO()) as output:
                    code = main(["eval", str(root)])

                self.assertEqual(code, 1)
                self.assertIn("no cases", output.getvalue())

    def test_eval_cli_uses_real_provider_when_requested(self):
        class FakeRealLLM:
            init_args = []

            def __init__(self, base_url, api_key, model, user_agent="", timeout=60):
                self.init_args.append((base_url, api_key, model, user_agent, timeout))
                self.calls = 0

            def complete(self, context: str) -> str:
                self.calls += 1
                if self.calls > 1:
                    return json.dumps(
                        {
                            "schema_version": "1",
                            "action": "finish",
                            "args": {"summary": "done"},
                        }
                    )
                html = (
                    "<!doctype html><html><head>"
                    '<meta name="viewport" content="width=device-width, initial-scale=1">'
                    "<title>Real checklist page</title></head>"
                    '<body><input type="search" aria-label="search">'
                    "<main><h1>search</h1><section>detail checklist</section></main>"
                    "</body></html>"
                )
                return json.dumps(
                    {
                        "schema_version": "1",
                        "action": "write_file",
                        "args": {"path": "index.html", "content": html},
                    }
                )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env_file = root / ".env"
            self._write_eval_case(root)
            env_file.write_text("OPENAI_COMPATIBLE_API_KEY=sk-test-secret\n", encoding="utf-8")

            with patch("specgate.cli.OpenAICompatibleLLM", FakeRealLLM), redirect_stdout(io.StringIO()) as output:
                code = main(
                    [
                        "eval",
                        str(root),
                        "--context-strategy",
                        "injection-safe",
                        "--provider",
                        "openai-compatible",
                        "--model",
                        "test-model",
                        "--base-url",
                        "https://api.example.test/v1",
                        "--env-file",
                        str(env_file),
                        "--timeout",
                        "12",
                        "--max-steps",
                        "2",
                        "--governance-profile",
                        "review",
                    ]
                )

            self.assertEqual(code, 0)
            self.assertIn("strategy=injection-safe", output.getvalue())
            self.assertIn("expected_matches=1", output.getvalue())
            self.assertEqual(
                FakeRealLLM.init_args,
                [("https://api.example.test/v1", "sk-test-secret", "test-model", "SpecGate/0.1 OpenAI-Compatible", 12.0)],
            )
            results_path = root / "eval-runs" / "latest" / "results.json"
            self.assertTrue(results_path.exists())
            results = json.loads(results_path.read_text(encoding="utf-8"))
            self.assertEqual(results["strategy"], "injection-safe")
            self.assertEqual(results["expected_matches"], 1)
            self.assertEqual(results["results"][0]["trust_status"], "trusted")

    def test_eval_cli_real_provider_fails_closed_without_credential(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_eval_case(root)

            with patch.dict(os.environ, {}, clear=True), redirect_stdout(io.StringIO()) as output:
                code = main(
                    [
                        "eval",
                        str(root),
                        "--provider",
                        "openai-compatible",
                        "--model",
                        "test-model",
                        "--base-url",
                        "https://api.example.test/v1",
                        "--env-file",
                        str(root / ".env"),
                    ]
                )

            self.assertEqual(code, 1)
            self.assertIn("not configured", output.getvalue())
            self.assertFalse((root / "eval-runs" / "latest" / "results.json").exists())

    def test_eval_cli_reports_provider_error_without_traceback(self):
        class FailingRealLLM:
            def __init__(self, base_url, api_key, model, user_agent="", timeout=60):
                pass

            def complete(self, context: str) -> str:
                raise LLMProviderError("HTTP 503 Service Unavailable")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env_file = root / ".env"
            self._write_eval_case(root)
            env_file.write_text("OPENAI_COMPATIBLE_API_KEY=sk-test-secret\n", encoding="utf-8")

            with patch("specgate.cli.OpenAICompatibleLLM", FailingRealLLM), redirect_stdout(io.StringIO()) as output:
                code = main(
                    [
                        "eval",
                        str(root),
                        "--provider",
                        "openai-compatible",
                        "--model",
                        "test-model",
                        "--base-url",
                        "https://api.example.test/v1",
                        "--env-file",
                        str(env_file),
                    ]
                )

            self.assertEqual(code, 1)
            text = output.getvalue()
            self.assertIn("provider request failed", text)
            self.assertIn("HTTP 503", text)
            self.assertNotIn("Traceback", text)
            self.assertNotIn("sk-test-secret", text)

    def test_real_run_fails_closed_without_credential(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "TASK_SPEC.md").write_text("# task", encoding="utf-8")
            (root / "CHECKLIST.md").write_text("", encoding="utf-8")
            (root / "specgate.toml").write_text(
                "\n".join(
                    [
                        "[policy]",
                        'allowed_actions = ["write_file", "replace_file", "read_file", "list_files", "finish"]',
                        'allowed_read_paths = ["TASK_SPEC.md", "CHECKLIST.md", "index.html"]',
                        'allowed_write_paths = ["index.html"]',
                    ]
                ),
                encoding="utf-8",
            )

            with patch.dict(os.environ, {}, clear=True), redirect_stdout(io.StringIO()) as output:
                exit_code = main(
                    [
                        "run",
                        str(root),
                        "--provider",
                        "openai-compatible",
                        "--model",
                        "test-model",
                        "--base-url",
                        "https://api.example.test/v1",
                        "--env-file",
                        str(root / ".env"),
                    ]
                )

            self.assertEqual(exit_code, 1)
            self.assertIn("not configured", output.getvalue())
            self.assertFalse((root / "runs" / "latest" / "trace.jsonl").exists())

    def test_real_run_uses_provider_inside_existing_runner(self):
        class FakeRealLLM:
            def __init__(self, base_url, api_key, model, user_agent="", timeout=60):
                self.calls = 0

            def complete(self, context: str) -> str:
                self.calls += 1
                if self.calls == 1:
                    return (
                        '{"schema_version":"1","action":"write_file",'
                        '"args":{"path":"index.html","content":"<!doctype html><html><body>draft</body></html>"}}'
                    )
                return (
                    '{"schema_version":"1","action":"replace_file",'
                    '"args":{"path":"index.html","content":"'
                    '<!doctype html><html><head><meta name=\\"viewport\\" content=\\"width=device-width, initial-scale=1\\">'
                    '<title>AI for Coding Knowledge Navigator</title></head><body><input type=\\"search\\">'
                    + "".join(
                        f'<section class=\\"node\\" data-related=\\"rel{i}\\"><h2>Node {i}</h2><p>Spec Gate Checklist {i}</p></section>'
                        for i in range(10)
                    )
                    + '<script>function highlightRelations(){} function filterNodes(){}</script></body></html>"}}'
                )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env_file = root / ".env"
            (root / "TASK_SPEC.md").write_text("# task", encoding="utf-8")
            (root / "CHECKLIST.md").write_text("- 必须包含 Spec\n- 必须包含 Gate\n", encoding="utf-8")
            (root / "specgate.toml").write_text(
                "\n".join(
                    [
                        "[policy]",
                        'allowed_actions = ["write_file", "replace_file", "read_file", "list_files", "finish"]',
                        'allowed_read_paths = ["TASK_SPEC.md", "CHECKLIST.md", "index.html"]',
                        'allowed_write_paths = ["index.html"]',
                    ]
                ),
                encoding="utf-8",
            )
            env_file.write_text("OPENAI_COMPATIBLE_API_KEY=sk-test-secret\n", encoding="utf-8")

            with patch("specgate.cli.OpenAICompatibleLLM", FakeRealLLM), redirect_stdout(io.StringIO()):
                exit_code = run_real_llm(
                    root=root,
                    provider="openai-compatible",
                    model="test-model",
                    base_url="https://api.example.test/v1",
                    env_file=env_file,
                    max_steps=3,
                    user_agent="SpecGate/0.1 OpenAI-Compatible",
                    timeout=60,
                )

            self.assertEqual(exit_code, 0)
            self.assertTrue((root / "index.html").exists())
            self.assertTrue((root / "reports" / "latest" / "index.html").exists())
            trace_text = (root / "runs" / "latest" / "trace.jsonl").read_text(encoding="utf-8")
            self.assertNotIn("sk-test-secret", trace_text)

    def test_real_run_reports_provider_error_without_traceback(self):
        class FailingRealLLM:
            def __init__(self, base_url, api_key, model, user_agent="", timeout=60):
                pass

            def complete(self, context: str) -> str:
                raise LLMProviderError("HTTP 403 Forbidden: model not allowed")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env_file = root / ".env"
            (root / "TASK_SPEC.md").write_text("# task", encoding="utf-8")
            (root / "CHECKLIST.md").write_text("", encoding="utf-8")
            (root / "specgate.toml").write_text(
                "\n".join(
                    [
                        "[policy]",
                        'allowed_actions = ["write_file", "replace_file", "read_file", "list_files", "finish"]',
                        'allowed_read_paths = ["TASK_SPEC.md", "CHECKLIST.md", "index.html"]',
                        'allowed_write_paths = ["index.html"]',
                    ]
                ),
                encoding="utf-8",
            )
            env_file.write_text("OPENAI_COMPATIBLE_API_KEY=sk-test-secret\n", encoding="utf-8")

            with patch("specgate.cli.OpenAICompatibleLLM", FailingRealLLM), redirect_stdout(io.StringIO()) as output:
                exit_code = run_real_llm(
                    root=root,
                    provider="openai-compatible",
                    model="test-model",
                    base_url="https://api.example.test/v1",
                    env_file=env_file,
                    max_steps=3,
                    user_agent="SpecGate/0.1 OpenAI-Compatible",
                    timeout=60,
                )

            self.assertEqual(exit_code, 1)
            text = output.getvalue()
            self.assertIn("provider request failed", text)
            self.assertIn("HTTP 403", text)
            self.assertNotIn("Traceback", text)
            self.assertNotIn("sk-test-secret", text)


if __name__ == "__main__":
    unittest.main()
