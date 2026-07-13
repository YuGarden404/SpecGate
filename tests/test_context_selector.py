import tempfile
import unittest
from pathlib import Path

from specgate.context_selector import select_context_files


def _statuses(selection):
    return {item.path: item.status for item in selection.files}


class ContextSelectorTests(unittest.TestCase):
    def test_selects_priority_task_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "TASK_SPEC.md").write_text("task spec", encoding="utf-8")
            (root / "CHECKLIST.md").write_text("checklist", encoding="utf-8")
            (root / "README.md").write_text("readme", encoding="utf-8")
            (root / "index.html").write_text("<html></html>", encoding="utf-8")

            selection = select_context_files(root, budget_chars=2000)
            statuses = _statuses(selection)

            self.assertEqual(statuses["TASK_SPEC.md"], "selected")
            self.assertEqual(statuses["CHECKLIST.md"], "selected")
            self.assertEqual(statuses["README.md"], "selected")
            self.assertEqual(statuses["index.html"], "selected")
            self.assertLessEqual(selection.used_chars, selection.budget_chars)

    def test_prunes_runtime_outputs_and_cache_dirs_without_leaking_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "TASK_SPEC.md").write_text("task spec", encoding="utf-8")
            (root / "runs" / "latest").mkdir(parents=True)
            (root / "runs" / "latest" / "trace.jsonl").write_text(
                "EXCLUDED_RUN_SENTINEL",
                encoding="utf-8",
            )
            (root / "reports" / "latest").mkdir(parents=True)
            (root / "reports" / "latest" / "index.html").write_text(
                "EXCLUDED_REPORT_SENTINEL",
                encoding="utf-8",
            )
            (root / "__pycache__").mkdir()
            (root / "__pycache__" / "x.pyc").write_bytes(b"cache")

            selection = select_context_files(root, budget_chars=2000)
            statuses = _statuses(selection)

            self.assertEqual(statuses["TASK_SPEC.md"], "selected")
            self.assertNotIn("runs/latest/trace.jsonl", statuses)
            self.assertNotIn("reports/latest/index.html", statuses)
            self.assertNotIn("__pycache__/x.pyc", statuses)
            self.assertNotIn("EXCLUDED_RUN_SENTINEL", str(selection))
            self.assertNotIn("EXCLUDED_REPORT_SENTINEL", str(selection))

    def test_applies_budget_to_low_priority_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "TASK_SPEC.md").write_text("A" * 40, encoding="utf-8")
            (root / "notes.txt").write_text("B" * 200, encoding="utf-8")

            selection = select_context_files(root, budget_chars=80)
            by_path = {item.path: item for item in selection.files}

            self.assertEqual(by_path["TASK_SPEC.md"].status, "selected")
            self.assertIn(by_path["notes.txt"].status, {"truncated", "skipped"})
            self.assertLessEqual(selection.used_chars, 80)

    def test_skips_non_text_suffixes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "TASK_SPEC.md").write_text("task spec", encoding="utf-8")
            (root / "image.png").write_bytes(b"\x89PNG")

            selection = select_context_files(root, budget_chars=2000)
            statuses = _statuses(selection)

            self.assertEqual(statuses["TASK_SPEC.md"], "selected")
            self.assertEqual(statuses["image.png"], "skipped")

    def test_rejects_invalid_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                select_context_files(Path(tmp), budget_chars=0)


if __name__ == "__main__":
    unittest.main()
