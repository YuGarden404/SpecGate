from pathlib import Path
import unittest


class ImportTests(unittest.TestCase):
    def test_specgate_package_imports(self):
        import specgate

        self.assertEqual(specgate.__version__, "0.2.0")

    def test_project_metadata_version_matches_runtime_version(self):
        pyproject = (Path(__file__).parents[1] / "pyproject.toml").read_text(
            encoding="utf-8"
        )

        self.assertIn('version = "0.2.0"', pyproject)


class RuntimeDependencyTests(unittest.TestCase):
    def test_runtime_dependencies_are_declared_directly(self):
        pyproject = (Path(__file__).parents[1] / "pyproject.toml").read_text(
            encoding="utf-8"
        )

        self.assertIn('"pydantic>=2.10,<3"', pyproject)
        self.assertIn('"PyYAML>=6,<7"', pyproject)


if __name__ == "__main__":
    unittest.main()
