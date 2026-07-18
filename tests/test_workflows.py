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

    def test_gitlab_pipeline_is_unit_test_only_on_shared_runner(self):
        workflow = (ROOT / ".gitlab-ci.yml").read_text(encoding="utf-8")
        normalized_lines = {line.strip() for line in workflow.splitlines()}

        self.assertIn("unit-test:", workflow)
        self.assertIn("python -m unittest discover -s tests -v", workflow)
        self.assertIn("- specgate --help", normalized_lines)

        for unsupported_build_dependency in (
            "docker-build:",
            "docker:26-dind",
            "kaniko-project",
            "moby/buildkit",
            "DOCKER_HOST",
            "docker build",
            "docker run",
            "buildctl",
        ):
            with self.subTest(dependency=unsupported_build_dependency):
                self.assertNotIn(unsupported_build_dependency, workflow)


if __name__ == "__main__":
    unittest.main()
