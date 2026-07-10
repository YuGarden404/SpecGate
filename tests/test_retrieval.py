import tempfile
import unittest
from pathlib import Path

from specgate.context_selector import select_context_files
from specgate.retrieval import build_query_terms, chunk_text, retrieve_chunks


class RetrievalTests(unittest.TestCase):
    def test_chunk_text_uses_overlapping_line_windows(self):
        text = "\n".join(f"line {number}" for number in range(1, 8))

        chunks = chunk_text(
            "docs/guide.md",
            text,
            chunk_lines=3,
            overlap_lines=1,
            max_chunk_chars=200,
        )

        self.assertEqual([(chunk.start_line, chunk.end_line) for chunk in chunks], [(1, 3), (3, 5), (5, 7)])
        self.assertTrue(all(chunk.path == "docs/guide.md" for chunk in chunks))
        self.assertEqual(chunks[0].text, "line 1\nline 2\nline 3")

    def test_build_query_terms_combines_task_checklist_and_gate_feedback(self):
        terms = build_query_terms(
            "Build a Python LLM Gate dashboard",
            "- must include search\n- must include details",
            "Gate failed: missing Python details",
        )

        for expected in ["python", "llm", "gate", "search", "details"]:
            self.assertIn(expected, terms)

    def test_retrieve_chunks_scores_top_matches_and_excludes_eval_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "notes.md").write_text("Python LLM Gate search details are required.", encoding="utf-8")
            (root / "unrelated.md").write_text("No matching content lives here.", encoding="utf-8")
            (root / "eval-runs").mkdir()
            (root / "eval-runs" / "latest.json").write_text(
                "Python LLM Gate search details are required.",
                encoding="utf-8",
            )

            result = retrieve_chunks(root, ["python", "llm", "gate", "search", "details"], top_k=2)

            selected_paths = [chunk.path for chunk in result.selected_chunks]
            self.assertIn("notes.md", selected_paths)
            self.assertNotIn("eval-runs/latest.json", selected_paths)
            notes_chunk = next(chunk for chunk in result.selected_chunks if chunk.path == "notes.md")
            self.assertGreater(notes_chunk.score, 0)
            self.assertIn("python", notes_chunk.matched_terms)

    def test_context_selector_skips_eval_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "TASK_SPEC.md").write_text("task spec", encoding="utf-8")
            (root / "eval-runs").mkdir()
            (root / "eval-runs" / "latest.json").write_text("runtime output", encoding="utf-8")

            selection = select_context_files(root, budget_chars=2000)
            statuses = {item.path: item.status for item in selection.files}

            self.assertEqual(statuses["TASK_SPEC.md"], "selected")
            self.assertEqual(statuses["eval-runs/latest.json"], "skipped")


if __name__ == "__main__":
    unittest.main()
