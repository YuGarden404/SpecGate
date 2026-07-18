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

    def test_gitlab_docker_build_is_daemonless_on_shared_runner(self):
        workflow = (ROOT / ".gitlab-ci.yml").read_text(encoding="utf-8")
        normalized_lines = {line.strip() for line in workflow.splitlines()}

        self.assertIn(
            "gcr.io/kaniko-project/executor:v1.23.2-debug",
            workflow,
        )
        self.assertIn('entrypoint: [""]', workflow)
        self.assertIn("/kaniko/executor", workflow)
        self.assertIn('--context "$CI_PROJECT_DIR"', workflow)
        self.assertIn('--dockerfile "$CI_PROJECT_DIR/Dockerfile"', workflow)
        self.assertIn("--no-push", workflow)
        self.assertIn("- specgate-web --help", normalized_lines)

        for privileged_docker_dependency in (
            "docker:26-dind",
            "DOCKER_HOST",
            "docker build",
            "docker run",
        ):
            with self.subTest(dependency=privileged_docker_dependency):
                self.assertNotIn(privileged_docker_dependency, workflow)


if __name__ == "__main__":
    unittest.main()
