import json
import tempfile
import unittest
from pathlib import Path

from specgate.eval_runner import discover_eval_cases


class EvalRunnerDiscoveryTests(unittest.TestCase):
    def test_discovers_cases_with_case_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            case = root / "create-page"
            case.mkdir()
            (case / "case.json").write_text(
                json.dumps(
                    {
                        "id": "create-page",
                        "title": "Create page",
                        "category": "generation",
                        "expected": {"should_pass": True, "must_block": False},
                    }
                ),
                encoding="utf-8",
            )
            (case / "TASK_SPEC.md").write_text("Task", encoding="utf-8")
            (case / "CHECKLIST.md").write_text("- Must include Task\n", encoding="utf-8")
            (case / "index.html").write_text("<html></html>", encoding="utf-8")
            (case / "specgate.toml").write_text(
                (
                    "[policy]\n"
                    'allowed_actions=["finish"]\n'
                    'allowed_read_paths=["TASK_SPEC.md","CHECKLIST.md","index.html"]\n'
                    'allowed_write_paths=["index.html"]\n'
                ),
                encoding="utf-8",
            )

            cases = discover_eval_cases(root)

        self.assertEqual(len(cases), 1)
        self.assertEqual(cases[0].case_id, "create-page")
        self.assertEqual(cases[0].title, "Create page")
        self.assertEqual(cases[0].category, "generation")
        self.assertEqual(cases[0].path, case)
        self.assertTrue(cases[0].expected_should_pass)
        self.assertFalse(cases[0].expected_must_block)

    def test_discovery_skips_directories_without_case_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "not-a-case").mkdir()

            cases = discover_eval_cases(root)

        self.assertEqual(cases, [])

    def test_discovery_uses_none_for_missing_expected_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            case = root / "missing-expected"
            case.mkdir()
            (case / "case.json").write_text(
                json.dumps({"id": "missing-expected", "title": "Missing expected", "category": "metadata"}),
                encoding="utf-8-sig",
            )

            cases = discover_eval_cases(root)

        self.assertEqual(len(cases), 1)
        self.assertIsNone(cases[0].expected_should_pass)
        self.assertIsNone(cases[0].expected_must_block)


if __name__ == "__main__":
    unittest.main()
