import json
import tempfile
import unittest
from pathlib import Path

from specgate.eval_runner import discover_eval_cases, run_eval_suite


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


class EvalRunnerExecutionTests(unittest.TestCase):
    def _case_dir(self, root: Path, case_id: str) -> Path:
        case = root / case_id
        case.mkdir()
        (case / "case.json").write_text(
            json.dumps(
                {
                    "id": case_id,
                    "title": "Mock execution",
                    "category": "generation",
                    "expected": {"should_pass": True, "must_block": False},
                }
            ),
            encoding="utf-8",
        )
        (case / "TASK_SPEC.md").write_text("Create a searchable detail page.", encoding="utf-8")
        (case / "CHECKLIST.md").write_text("- Must include checklist\n", encoding="utf-8")
        (case / "index.html").write_text("draft", encoding="utf-8")
        (case / "specgate.toml").write_text(
            (
                "[policy]\n"
                'allowed_actions=["write_file","finish"]\n'
                'allowed_read_paths=["TASK_SPEC.md","CHECKLIST.md","index.html"]\n'
                'allowed_write_paths=["index.html"]\n'
            ),
            encoding="utf-8",
        )
        return case

    def test_run_eval_suite_executes_mock_case_and_writes_trace_stats(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            case = self._case_dir(root, "mock-case")
            original_html = (case / "index.html").read_text(encoding="utf-8")
            html = (
                "<!doctype html><html><head>"
                '<meta name="viewport" content="width=device-width, initial-scale=1">'
                "<title>Mock checklist page</title></head>"
                "<body><input type=\"search\" aria-label=\"搜索\">"
                "<main><h1>搜索</h1><section>详情 checklist</section></main>"
                "</body></html>"
            )
            responses = {
                "mock-case": [
                    {
                        "schema_version": "1",
                        "action": "write_file",
                        "args": {"path": "index.html", "content": html},
                    },
                    {"schema_version": "1", "action": "finish", "args": {"summary": "done"}},
                ]
            }

            suite = run_eval_suite(root, strategy="baseline", scripted_responses=responses)

            self.assertEqual(suite.total_cases, 1)
            self.assertEqual(suite.passed_cases, 1)
            self.assertEqual(suite.expected_matches, 1)
            self.assertEqual(original_html, "draft")
            self.assertEqual((case / "index.html").read_text(encoding="utf-8"), "draft")

            results_path = root / "eval-runs" / "latest" / "results.json"
            self.assertTrue(results_path.exists())
            data = json.loads(results_path.read_text(encoding="utf-8"))
            self.assertEqual(data["strategy"], "baseline")
            self.assertEqual(data["results"][0]["case_id"], "mock-case")
            self.assertEqual(data["results"][0]["context_chars_max"], suite.results[0].context_chars_max)
            self.assertGreater(data["results"][0]["context_chars_max"], 0)

    def test_direct_finish_counts_failed_final_gate_without_gate_trace_event(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._case_dir(root, "direct-finish")
            responses = {
                "direct-finish": [
                    {"schema_version": "1", "action": "finish", "args": {"summary": "done"}}
                ]
            }

            suite = run_eval_suite(root, strategy="baseline", scripted_responses=responses)

            self.assertFalse(suite.results[0].passed)
            self.assertEqual(suite.results[0].gate_failures, 1)


if __name__ == "__main__":
    unittest.main()
