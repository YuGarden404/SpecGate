import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from specgate.cli import main, run_mock_demo, run_real_llm
from specgate.llm import LLMProviderError


class CliTests(unittest.TestCase):
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
