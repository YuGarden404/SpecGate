import tempfile
import unittest
from pathlib import Path

from specgate.llm import MockLLM
from specgate.policy import WorkspacePolicy
from specgate.runner import AgentRunner


BROKEN_HTML = "<html><head><title>x</title></head><body></body></html>"
FIXED_HTML = (
    """<!doctype html><html><head><meta name="viewport" content="width=device-width, initial-scale=1">"""
    """<title>AI for Coding Knowledge Navigator</title></head><body><input type="search">"""
    + "".join(
        f'<section class="node" data-related="rel{i}"><h2>Node {i}</h2><p>Spec Gate Checklist 定义 {i}</p></section>'
        for i in range(10)
    )
    + "<script>function highlightRelations(){} function filterNodes(){}</script></body></html>"
)


class MutatingLLM:
    def __init__(self, root: Path):
        self.root = root
        self.calls = 0

    def complete(self, context: str) -> str:
        self.calls += 1
        if self.calls == 1:
            return (
                '{"schema_version":"1","action":"write_file",'
                '"args":{"path":"index.html","content":"<!doctype html><html><body>draft</body></html>"}}'
            )
        if self.calls == 2:
            (self.root / "index.html").write_text("external edit", encoding="utf-8")
            return (
                '{"schema_version":"1","action":"replace_file",'
                '"args":{"path":"index.html","content":"agent overwrite"}}'
            )
        return '{"schema_version":"1","action":"finish","args":{"summary":"done"}}'


class RunnerTests(unittest.TestCase):
    def test_gate_failure_feedback_changes_next_action(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "TASK_SPEC.md").write_text("# 页面设计\n生成知识导航", encoding="utf-8")
            (root / "CHECKLIST.md").write_text("- 必须包含 Spec\n- 必须包含 Gate\n", encoding="utf-8")
            llm = MockLLM(
                [
                    {"schema_version": "1", "action": "write_file", "args": {"path": "index.html", "content": BROKEN_HTML}},
                    {"schema_version": "1", "action": "replace_file", "args": {"path": "index.html", "content": FIXED_HTML}},
                    {"schema_version": "1", "action": "finish", "args": {"summary": "done"}},
                ]
            )
            policy = WorkspacePolicy(
                root,
                {"write_file", "replace_file", "read_file", "list_files", "finish"},
                {"TASK_SPEC.md", "CHECKLIST.md", "index.html"},
                {"index.html"},
            )

            result = AgentRunner(root, llm, policy, max_steps=5).run()

            self.assertTrue(result.passed)
            self.assertEqual(llm.calls, 3)
            self.assertIn("Node 9", (root / "index.html").read_text(encoding="utf-8"))

    def test_guardrail_block_is_recorded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "TASK_SPEC.md").write_text("# 页面设计", encoding="utf-8")
            (root / "CHECKLIST.md").write_text("", encoding="utf-8")
            llm = MockLLM(
                [
                    {"schema_version": "1", "action": "run_command", "args": {"command": "dir"}},
                ]
            )
            policy = WorkspacePolicy(root, {"write_file"}, {"TASK_SPEC.md"}, {"index.html"})

            result = AgentRunner(root, llm, policy, max_steps=1).run()

            self.assertFalse(result.passed)
            trace_text = (root / "runs" / "latest" / "trace.jsonl").read_text(encoding="utf-8")
            self.assertIn("unknown action", trace_text)

    def test_external_file_change_is_blocked_and_traced(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "TASK_SPEC.md").write_text("# 页面设计", encoding="utf-8")
            (root / "CHECKLIST.md").write_text("", encoding="utf-8")
            llm = MutatingLLM(root)
            policy = WorkspacePolicy(
                root,
                {"write_file", "replace_file", "finish"},
                {"TASK_SPEC.md", "CHECKLIST.md", "index.html"},
                {"index.html"},
            )

            AgentRunner(root, llm, policy, max_steps=3).run()

            trace_text = (root / "runs" / "latest" / "trace.jsonl").read_text(encoding="utf-8")
            self.assertIn("file changed since run started", trace_text)
            self.assertEqual((root / "index.html").read_text(encoding="utf-8"), "external edit")


if __name__ == "__main__":
    unittest.main()
