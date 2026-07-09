import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from specgate.cli import main, run_mock_demo


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


if __name__ == "__main__":
    unittest.main()
