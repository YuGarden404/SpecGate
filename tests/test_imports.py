import importlib
from pathlib import Path
import unittest


class ImportTests(unittest.TestCase):
    def test_specgate_package_imports(self):
        import specgate

        self.assertEqual(specgate.__version__, "0.3.0")

    def test_project_metadata_version_matches_runtime_version(self):
        pyproject = (Path(__file__).parents[1] / "pyproject.toml").read_text(
            encoding="utf-8"
        )

        self.assertIn('version = "0.3.0"', pyproject)

    def test_shell_test_modules_import_as_package_modules(self):
        for module_name in (
            "tests.test_action_pipeline",
            "tests.test_interactive_shell",
            "tests.test_runner",
            "tests.test_runtime_events",
            "tests.test_shell_config",
            "tests.test_shell_e2e",
            "tests.test_shell_renderer",
            "tests.test_shell_runtime",
        ):
            with self.subTest(module=module_name):
                importlib.import_module(module_name)


class RuntimeDependencyTests(unittest.TestCase):
    def test_runtime_dependencies_are_declared_directly(self):
        pyproject = (Path(__file__).parents[1] / "pyproject.toml").read_text(
            encoding="utf-8"
        )

        self.assertIn('"pydantic>=2.10,<3"', pyproject)
        self.assertIn('"prompt-toolkit>=3.0,<4"', pyproject)
        self.assertIn('"PyYAML>=6,<7"', pyproject)


if __name__ == "__main__":
    unittest.main()
