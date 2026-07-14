import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class WorkflowTests(unittest.TestCase):
    def test_pages_installs_project_before_regenerating_mock_demo(self):
        workflow = (
            ROOT / ".github" / "workflows" / "pages.yml"
        ).read_text(encoding="utf-8")
        install_command = "run: python -m pip install -e ."
        demo_command = (
            "run: python -m specgate.cli run-mock-demo "
            "examples/knowledge_nav"
        )

        self.assertIn(
            install_command,
            workflow,
            "Pages workflow 必须安装 pyproject.toml 声明的依赖",
        )
        self.assertIn(demo_command, workflow)
        self.assertLess(
            workflow.index(install_command),
            workflow.index(demo_command),
            "Pages 必须在生成 mock demo 前安装项目依赖",
        )


if __name__ == "__main__":
    unittest.main()
