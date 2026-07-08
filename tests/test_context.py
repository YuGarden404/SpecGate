import tempfile
import unittest
from pathlib import Path

from specgate.context import build_context_pack
from specgate.gate import GateCheck, GateIssue, GateResult
from specgate.trace import TraceStore


class ContextTests(unittest.TestCase):
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

            self.assertIn("TASK_SPEC.md", pack)
            self.assertIn("CHECKLIST.md", pack)
            self.assertIn("Gate 失败", pack)
            self.assertIn("index.html 摘要", pack)


if __name__ == "__main__":
    unittest.main()
