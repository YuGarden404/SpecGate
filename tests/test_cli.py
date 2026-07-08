import tempfile
import unittest
from pathlib import Path

from specgate.cli import run_mock_demo


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


if __name__ == "__main__":
    unittest.main()
