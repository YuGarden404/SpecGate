import json
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


class FeedbackAwareLLM:
    def __init__(self):
        self.contexts: list[str] = []

    def complete(self, context: str) -> str:
        self.contexts.append(context)
        if len(self.contexts) == 1:
            return "not json"
        return '{"schema_version":"1","action":"finish","args":{"summary":"done"}}'


class RecordingLLM:
    def __init__(self):
        self.contexts: list[str] = []

    def complete(self, context: str) -> str:
        self.contexts.append(context)
        return '{"schema_version":"1","action":"finish","args":{"summary":"done"}}'


class RunnerTests(unittest.TestCase):
    def test_successful_write_finish_records_metrics_and_trust(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "TASK_SPEC.md").write_text("# task", encoding="utf-8")
            (root / "CHECKLIST.md").write_text("", encoding="utf-8")
            llm = MockLLM(
                [
                    {
                        "schema_version": "1",
                        "action": "write_file",
                        "args": {
                            "path": "index.html",
                            "content": (
                                '<!doctype html><html><head><meta name="viewport" content="width=device-width">'
                                '<title>Task</title></head><body><input type="search">Task Search Detail</body></html>'
                            ),
                        },
                    },
                    {"schema_version": "1", "action": "finish", "args": {"summary": "done"}},
                ]
            )
            policy = WorkspacePolicy(
                root,
                {"write_file", "finish"},
                {"TASK_SPEC.md", "CHECKLIST.md", "index.html"},
                {"index.html"},
            )

            result = AgentRunner(root, llm, policy, max_steps=3).run()

            self.assertTrue(result.passed)
            self.assertEqual(result.profile, "strict")
            self.assertIsNotNone(result.metrics)
            self.assertEqual(result.metrics.llm_calls, 2)
            self.assertEqual(result.metrics.tool_calls, 2)
            self.assertEqual(result.metrics.successful_tool_calls, 2)
            self.assertEqual(result.metrics.gate_runs, 1)
            self.assertEqual(result.metrics.gate_failures, 0)
            self.assertEqual(result.metrics.finish_actions, 1)
            self.assertIsNotNone(result.trust)
            self.assertEqual(result.trust.status, "trusted")

    def test_blocked_env_write_records_permission_decision_and_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "TASK_SPEC.md").write_text("# task", encoding="utf-8")
            (root / "CHECKLIST.md").write_text("", encoding="utf-8")
            llm = MockLLM(
                [
                    {
                        "schema_version": "1",
                        "action": "write_file",
                        "args": {"path": ".env", "content": "SECRET=123"},
                    }
                ]
            )
            policy = WorkspacePolicy(
                root,
                {"write_file"},
                {"TASK_SPEC.md", "CHECKLIST.md", "index.html"},
                {"index.html"},
            )

            result = AgentRunner(root, llm, policy, max_steps=1, governance_profile="review").run()

            self.assertIsNotNone(result.metrics)
            self.assertEqual(result.metrics.blocked_actions, 1)
            self.assertEqual(result.profile, "review")
            self.assertIsNotNone(result.permission_decisions)
            self.assertEqual(len(result.permission_decisions), 1)
            decision = result.permission_decisions[0]
            self.assertEqual(decision.path, ".env")
            self.assertEqual(decision.profile, "review")
            self.assertEqual(decision.rule_family, "allowlist")
            trace_events = [
                json.loads(line)["event_type"]
                for line in (root / "runs" / "latest" / "trace.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            self.assertIn("permission_decision", trace_events)
            self.assertIn("run_summary", trace_events)

    def test_max_step_exhaustion_marks_metrics_and_failed_trust(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "TASK_SPEC.md").write_text("# task", encoding="utf-8")
            (root / "CHECKLIST.md").write_text("", encoding="utf-8")
            llm = MockLLM(
                [
                    {
                        "schema_version": "1",
                        "action": "write_file",
                        "args": {
                            "path": "index.html",
                            "content": (
                                '<!doctype html><html><head><meta name="viewport" content="width=device-width">'
                                '<title>Task</title></head><body><input type="search">Task Search Detail</body></html>'
                            ),
                        },
                    }
                ]
            )
            policy = WorkspacePolicy(
                root,
                {"write_file"},
                {"TASK_SPEC.md", "CHECKLIST.md", "index.html"},
                {"index.html"},
            )

            result = AgentRunner(root, llm, policy, max_steps=1).run()

            self.assertIsNotNone(result.metrics)
            self.assertTrue(result.metrics.max_steps_reached)
            self.assertIsNotNone(result.trust)
            self.assertEqual(result.trust.status, "failed")
            self.assertIn("max_steps_reached", result.trust.reasons)

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
            self.assertTrue((root / "memory.json").exists())
            self.assertIn("Gate", (root / "memory.json").read_text(encoding="utf-8"))

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

    def test_latest_trace_is_reset_for_each_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "TASK_SPEC.md").write_text("# task", encoding="utf-8")
            (root / "CHECKLIST.md").write_text("", encoding="utf-8")
            trace_path = root / "runs" / "latest" / "trace.jsonl"
            trace_path.parent.mkdir(parents=True)
            trace_path.write_text("old event\n", encoding="utf-8")
            llm = MockLLM([{"schema_version": "1", "action": "run_command", "args": {"command": "dir"}}])
            policy = WorkspacePolicy(root, {"write_file"}, {"TASK_SPEC.md"}, {"index.html"})

            AgentRunner(root, llm, policy, max_steps=1).run()

            trace_text = trace_path.read_text(encoding="utf-8")
            self.assertNotIn("old event", trace_text)
            self.assertIn("unknown action", trace_text)

    def test_parse_error_feedback_reaches_next_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "TASK_SPEC.md").write_text("# task", encoding="utf-8")
            (root / "CHECKLIST.md").write_text("", encoding="utf-8")
            llm = FeedbackAwareLLM()
            policy = WorkspacePolicy(root, {"finish"}, {"TASK_SPEC.md", "CHECKLIST.md", "index.html"}, {"index.html"})

            result = AgentRunner(root, llm, policy, max_steps=2).run()

            self.assertEqual(len(llm.contexts), 2)
            self.assertIsNotNone(result.metrics)
            self.assertEqual(result.metrics.parse_errors, 1)
            self.assertIn("Runtime Feedback", llm.contexts[1])
            self.assertIn("parse_error", llm.contexts[1])
            self.assertIn("model output must be one strict JSON object", llm.contexts[1])

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


class RunnerContextStrategyTests(unittest.TestCase):
    def test_runner_passes_context_strategy_and_records_context_size(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "TASK_SPEC.md").write_text("Task", encoding="utf-8")
            (root / "CHECKLIST.md").write_text("- must include Task\n", encoding="utf-8")
            (root / "index.html").write_text(
                '<!doctype html><html><head><meta name="viewport" content="width=device-width">'
                "<title>Task</title></head><body>Task Search Detail</body></html>",
                encoding="utf-8",
            )
            policy = WorkspacePolicy(
                root=root,
                allowed_actions={"finish"},
                allowed_read_paths={"TASK_SPEC.md", "CHECKLIST.md", "index.html"},
                allowed_write_paths={"index.html"},
            )
            llm = RecordingLLM()

            result = AgentRunner(root, llm, policy, max_steps=1, context_strategy="injection-safe").run()

            self.assertGreater(result.context_chars_max, 0)
            self.assertIn("## Context Strategy\ninjection-safe", llm.contexts[0])
            trace = (root / "runs" / "latest" / "trace.jsonl").read_text(encoding="utf-8")
            self.assertIn("context_built", trace)
            self.assertIn("context_chars", trace)


if __name__ == "__main__":
    unittest.main()
