import tempfile
import unittest
from pathlib import Path
from unittest import mock

import specgate.workspace_fs as workspace_fs
from specgate.context_selector import select_context_files
from specgate.retrieval import RetrievalConfig, build_query_terms, chunk_text, retrieve_chunks
from specgate.workspace_fs import WorkspacePathError


class RetrievalTests(unittest.TestCase):
    def _symlink_or_skip(self, link: Path, target: Path) -> None:
        try:
            link.symlink_to(target)
        except OSError as exc:
            self.skipTest(f"symlink creation unavailable: {exc}")

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

    def test_retrieval_preserves_path_tiebreak_and_character_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            content = "python gate search"
            (root / "b.md").write_text(content, encoding="utf-8")
            (root / "a.md").write_text(content, encoding="utf-8")
            config = RetrievalConfig(top_k=2, budget_chars=len(content))

            result = retrieve_chunks(
                root,
                ["python", "gate", "search"],
                config,
            )

            self.assertEqual([chunk.path for chunk in result.selected_chunks], ["a.md"])
            self.assertEqual(result.used_chars, len(content))
            self.assertTrue(any("b.md:1: budget exceeded" in reason for reason in result.dropped_reasons))

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

    def test_retrieval_rejects_external_link_and_records_rule_family(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as outside:
            root = Path(tmp)
            sentinel = "EXTERNAL_RETRIEVAL_SENTINEL python gate search"
            external = Path(outside) / "notes.md"
            external.write_text(sentinel, encoding="utf-8")
            self._symlink_or_skip(root / "linked-notes.md", external)
            (root / "safe-notes.md").write_text("python gate search safe", encoding="utf-8")

            result = retrieve_chunks(root, ["python", "gate", "search"])

            self.assertEqual([chunk.path for chunk in result.selected_chunks], ["safe-notes.md"])
            self.assertTrue(any("linked_path" in reason for reason in result.dropped_reasons))
            self.assertNotIn(sentinel, str(result))

    def test_retrieval_records_scan_path_race_without_candidates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "notes.md").write_text("python gate search", encoding="utf-8")

            with mock.patch(
                "specgate.workspace_fs.read_workspace_text",
                side_effect=WorkspacePathError("ancestor replaced", "path_race"),
            ):
                result = retrieve_chunks(root, ["python", "gate", "search"])

            self.assertEqual(result.candidate_count, 0)
            self.assertEqual(result.selected_chunks, [])
            self.assertTrue(any("path_race" in reason for reason in result.dropped_reasons))

    def test_retrieval_skips_linked_candidate_and_keeps_safe_chunks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "safe.md").write_text("python gate search safe", encoding="utf-8")
            sentinel = "EXTERNAL_RETRIEVAL_SENTINEL python gate search"
            (root / "linked.md").write_text(sentinel, encoding="utf-8")
            original_is_link_like = workspace_fs.is_link_like

            def mark_linked(path):
                if Path(path).name == "linked.md":
                    return True
                return original_is_link_like(path)

            with mock.patch(
                "specgate.workspace_fs.is_link_like",
                side_effect=mark_linked,
            ):
                result = retrieve_chunks(root, ["python", "gate", "search"])

            self.assertEqual([chunk.path for chunk in result.selected_chunks], ["safe.md"])
            self.assertTrue(any("linked_path" in reason for reason in result.dropped_reasons))
            self.assertNotIn(sentinel, str(result))

    def test_excluded_directory_link_does_not_empty_retrieval(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "safe.md").write_text("python gate search safe", encoding="utf-8")
            (root / "eval-runs").mkdir()
            (root / "eval-runs" / "linked.md").write_text(
                "EXTERNAL_EXCLUDED_SENTINEL python gate search",
                encoding="utf-8",
            )
            original_is_link_like = workspace_fs.is_link_like

            def mark_linked(path):
                if Path(path).name == "linked.md":
                    return True
                return original_is_link_like(path)

            with mock.patch(
                "specgate.workspace_fs.iter_workspace_files",
                side_effect=WorkspacePathError("excluded linked entry", "linked_path"),
            ), mock.patch(
                "specgate.workspace_fs.is_link_like",
                side_effect=mark_linked,
            ):
                result = retrieve_chunks(root, ["python", "gate", "search"])

            self.assertEqual([chunk.path for chunk in result.selected_chunks], ["safe.md"])
            self.assertTrue(any("linked_path" in reason for reason in result.dropped_reasons))
            self.assertNotIn("EXTERNAL_EXCLUDED_SENTINEL", str(result))


if __name__ == "__main__":
    unittest.main()
