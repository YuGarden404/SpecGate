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


if __name__ == "__main__":
    unittest.main()
