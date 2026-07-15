import tempfile
import unittest
from pathlib import Path

from specgate.context import (
    build_context_pack,
    build_context_pack_with_metadata,
    build_role_context_pack_with_metadata,
)
from specgate.context_lifecycle import CompressionConfig
from specgate.retrieval import RetrievalConfig
from specgate.gate import GateCheck, GateIssue, GateResult
from specgate.trace import TraceStore
from specgate.workspace_fs import WorkspacePathError


class ContextTests(unittest.TestCase):
    def test_trace_store_rejects_link_without_overwriting_external_file(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as outside:
            root = Path(tmp)
            external = Path(outside) / "trace.jsonl"
            external.write_text("EXTERNAL_TRACE_SENTINEL", encoding="utf-8")
            link = root / "trace.jsonl"
            try:
                link.symlink_to(external)
            except OSError as exc:
                self.skipTest(f"symlink creation unavailable: {exc}")

            with self.assertRaises(WorkspacePathError):
                TraceStore(link, reset=True)

            self.assertEqual(
                external.read_text(encoding="utf-8"),
                "EXTERNAL_TRACE_SENTINEL",
            )

    def test_context_builders_apply_explicit_budget_retrieval_and_compression_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "TASK_SPEC.md").write_text(
                "# Task\nBuild a runtime configuration dashboard.",
                encoding="utf-8",
            )
            (root / "CHECKLIST.md").write_text(
                "- Include runtime configuration evidence.",
                encoding="utf-8",
            )
            for index in range(4):
                (root / f"notes-{index}.md").write_text(
                    ("runtime configuration evidence " * 80) + str(index),
                    encoding="utf-8",
                )
            events = [
                {
                    "event_type": "tool_result",
                    "action": "read_file",
                    "data": "x" * 500,
                }
            ]
            retrieval = RetrievalConfig(top_k=1, budget_chars=500)
            compression = CompressionConfig(
                max_tool_result_chars=100,
                summary_budget_chars=500,
            )

            context, metadata = build_context_pack_with_metadata(
                root,
                None,
                runtime_feedback=events,
                strategy="compressed-rag",
                context_budget_chars=1000,
                retrieval_config=retrieval,
                compression_config=compression,
            )
            _role_context, role_metadata = build_role_context_pack_with_metadata(
                root,
                "planner",
                {},
                None,
                runtime_feedback=events,
                context_budget_chars=1000,
                retrieval_config=retrieval,
                compression_config=compression,
            )

        self.assertIn("budget_chars: 1000", context)
        self.assertIn("## Policy Boundary", context)
        self.assertIn("## Latest Gate Feedback", context)
        self.assertEqual(metadata["retrieval"]["budget_chars"], 500)
        self.assertLessEqual(len(metadata["retrieval"]["selected_chunks"]), 1)
        self.assertEqual(metadata["compression"]["cleared_tool_results"], 1)
        self.assertEqual(role_metadata["retrieval"]["budget_chars"], 500)
        self.assertEqual(role_metadata["compression"]["cleared_tool_results"], 1)

    def test_trace_redacts_secret_like_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            trace = TraceStore(Path(tmp) / "trace.jsonl")

            trace.append("llm_response", {"text": "key sk-abc123456789"})

            raw = (Path(tmp) / "trace.jsonl").read_text(encoding="utf-8")
            self.assertNotIn("sk-abc123456789", raw)
            self.assertIn("[REDACTED]", raw)

    def test_context_pack_contains_task_docs_and_gate_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "TASK_SPEC.md").write_text("# 页面设计\n做知识导航", encoding="utf-8")
            (root / "CHECKLIST.md").write_text("- 必须包含 Spec", encoding="utf-8")
            (root / "index.html").write_text("<html><body>draft</body></html>", encoding="utf-8")
            gate = GateResult(
                False,
                [GateCheck("node_count", False, "至少 10 个知识节点")],
                [GateIssue("too_few_nodes", "error", "知识节点不足", "0", "添加至少 10 个节点")],
                "Gate 失败：添加至少 10 个节点",
            )

            pack = build_context_pack(root, gate)

            self.assertIn("Context Manifest", pack)
            self.assertIn("Selected Files", pack)
            self.assertIn("Tool Registry", pack)
            self.assertIn("write_file", pack)
            self.assertIn("finish", pack)
            self.assertIn("schema_version", pack)
            self.assertIn('"action"', pack)
            self.assertIn("TASK_SPEC.md", pack)
            self.assertIn("selected", pack)
            self.assertIn("CHECKLIST.md", pack)
            self.assertIn("Gate 失败", pack)
            self.assertIn("index.html 摘要", pack)

    def test_context_pack_includes_cross_session_memory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "TASK_SPEC.md").write_text("# task", encoding="utf-8")
            (root / "CHECKLIST.md").write_text("", encoding="utf-8")
            (root / "memory.json").write_text(
                '{"runs":[{"passed":true,"steps":3,"gate_summary":"reuse search layout"}]}',
                encoding="utf-8",
            )

            pack = build_context_pack(root, None)

            self.assertIn("Memory", pack)
            self.assertIn("reuse search layout", pack)
            self.assertNotIn("### memory.json", pack)


if __name__ == "__main__":
    unittest.main()
