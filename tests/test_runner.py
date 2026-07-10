import json
import tempfile
import unittest
from pathlib import Path

from specgate.llm import MockLLM
from specgate.policy import WorkspacePolicy
from specgate.runner import AgentRunner
from specgate.approvals import GovernanceConfig, approval_queue_path


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


class ApprovalFeedbackLLM:
    def __init__(self):
        self.contexts: list[str] = []

    def complete(self, context: str) -> str:
        self.contexts.append(context)
        if len(self.contexts) == 1:
            return (
                '{"schema_version":"1","action":"replace_file",'
                '"args":{"path":"README.md","content":"changed"}}'
            )
        return '{"schema_version":"1","action":"finish","args":{"summary":"done"}}'


class RunnerTests(unittest.TestCase):
    def test_rag_select_run_records_retrieval_evidence_and_metrics(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "TASK_SPEC.md").write_text(
                "The page must display Python LLM Gate search details.",
                encoding="utf-8",
            )
            (root / "CHECKLIST.md").write_text("", encoding="utf-8")
            (root / "notes.md").write_text(
                "Python LLM Gate search details explain the expected dashboard content.",
                encoding="utf-8",
            )
            (root / "index.html").write_text(
                '<!doctype html><html><head><meta name="viewport" content="width=device-width">'
                '<title>Task</title></head><body><input type="search">Python LLM Gate search details</body></html>',
                encoding="utf-8",
            )
            llm = MockLLM([{"schema_version": "1", "action": "finish", "args": {"summary": "done"}}])
            policy = WorkspacePolicy(
                root,
                {"finish"},
                {"TASK_SPEC.md", "CHECKLIST.md", "index.html", "notes.md"},
                {"index.html"},
            )

            result = AgentRunner(root, llm, policy, max_steps=1, context_strategy="rag-select").run()

            retrieval_path = root / "runs" / "latest" / "retrieval.json"
            self.assertTrue(retrieval_path.exists())
            retrieval = json.loads(retrieval_path.read_text(encoding="utf-8"))
            self.assertIn("query_terms", retrieval)
            self.assertGreaterEqual(retrieval["candidate_count"], 1)
            self.assertGreaterEqual(len(retrieval["selected_chunks"]), 1)
            selected_paths = {chunk["path"] for chunk in retrieval["selected_chunks"]}
            self.assertIn("notes.md", selected_paths)
            self.assertIsNotNone(result.metrics)
            self.assertEqual(result.metrics.retrieval_queries, 1)
            self.assertGreaterEqual(result.metrics.retrieved_chunks, 1)
            self.assertGreaterEqual(result.metrics.retrieval_candidate_chunks, 1)
            self.assertGreater(result.metrics.retrieval_context_chars, 0)
            trace_events = [
                json.loads(line)["event_type"]
                for line in (root / "runs" / "latest" / "trace.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            self.assertIn("retrieval_result", trace_events)

    def test_rag_select_does_not_inject_policy_disallowed_read_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "TASK_SPEC.md").write_text(
                "The page must mention ultrasecret retrieval boundary.",
                encoding="utf-8",
            )
            (root / "CHECKLIST.md").write_text("", encoding="utf-8")
            (root / "secret_notes.md").write_text(
                "ultrasecret retrieval boundary should never reach the LLM context.",
                encoding="utf-8",
            )
            (root / "index.html").write_text(
                '<!doctype html><html><head><meta name="viewport" content="width=device-width">'
                '<title>Task</title></head><body><input type="search">ultrasecret retrieval boundary</body></html>',
                encoding="utf-8",
            )
            llm = RecordingLLM()
            policy = WorkspacePolicy(
                root,
                {"finish"},
                {"TASK_SPEC.md", "CHECKLIST.md", "index.html"},
                {"index.html"},
            )

            AgentRunner(root, llm, policy, max_steps=1, context_strategy="rag-select").run()

            self.assertNotIn("secret_notes.md", llm.contexts[0])
            self.assertNotIn("should never reach the LLM context", llm.contexts[0])
            retrieval = json.loads((root / "runs" / "latest" / "retrieval.json").read_text(encoding="utf-8"))
            self.assertNotIn("secret_notes.md", json.dumps(retrieval, ensure_ascii=False))
            self.assertNotIn("should never reach the LLM context", json.dumps(retrieval, ensure_ascii=False))
            selected_paths = {chunk["path"] for chunk in retrieval["selected_chunks"]}
            self.assertNotIn("secret_notes.md", selected_paths)

    def test_compressed_rag_does_not_pin_policy_disallowed_task_spec(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "TASK_SPEC.md").write_text(
                "SECRET TASK CONSTRAINT must never reach context.",
                encoding="utf-8",
            )
            (root / "CHECKLIST.md").write_text("SECRET CHECKLIST TERM", encoding="utf-8")
            (root / "index.html").write_text(
                '<!doctype html><html><head><meta name="viewport" content="width=device-width">'
                '<title>Task</title></head><body><input type="search">safe content</body></html>',
                encoding="utf-8",
            )
            llm = RecordingLLM()
            policy = WorkspacePolicy(
                root,
                {"finish"},
                {"index.html"},
                {"index.html"},
            )

            AgentRunner(root, llm, policy, max_steps=1, context_strategy="compressed-rag").run()

            self.assertNotIn("SECRET TASK CONSTRAINT", llm.contexts[0])
            self.assertNotIn("SECRET CHECKLIST TERM", llm.contexts[0])
            retrieval = json.loads((root / "runs" / "latest" / "retrieval.json").read_text(encoding="utf-8"))
            self.assertNotIn("SECRET", json.dumps(retrieval, ensure_ascii=False))

    def test_gate_feedback_does_not_leak_policy_disallowed_checklist(self):
        class TwoStepLLM:
            def __init__(self):
                self.contexts: list[str] = []

            def complete(self, context: str) -> str:
                self.contexts.append(context)
                if len(self.contexts) == 1:
                    return (
                        '{"schema_version":"1","action":"write_file",'
                        '"args":{"path":"index.html","content":"<!doctype html><html><head><title>x</title></head><body>draft</body></html>"}}'
                    )
                return '{"schema_version":"1","action":"finish","args":{"summary":"done"}}'

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "TASK_SPEC.md").write_text("Build a safe page.", encoding="utf-8")
            (root / "CHECKLIST.md").write_text("- 蹇呴』鍖呭惈 COMPRESSEDRAGSECRET\n", encoding="utf-8")
            (root / "CHECKLIST.md").write_text("- 必须包含 COMPRESSEDRAGSECRET\n", encoding="utf-8")
            llm = TwoStepLLM()
            policy = WorkspacePolicy(
                root,
                {"write_file", "finish"},
                {"TASK_SPEC.md", "index.html"},
                {"index.html"},
            )

            AgentRunner(root, llm, policy, max_steps=2, context_strategy="compressed-rag").run()

            self.assertEqual(len(llm.contexts), 2)
            self.assertNotIn("COMPRESSEDRAGSECRET", llm.contexts[1])
            retrieval = json.loads((root / "runs" / "latest" / "retrieval.json").read_text(encoding="utf-8"))
            self.assertNotIn("compressedragsecret", json.dumps(retrieval, ensure_ascii=False).lower())

    def test_list_files_feedback_does_not_leak_policy_disallowed_paths(self):
        class ListThenFinishLLM:
            def __init__(self):
                self.contexts: list[str] = []

            def complete(self, context: str) -> str:
                self.contexts.append(context)
                if len(self.contexts) == 1:
                    return '{"schema_version":"1","action":"list_files","args":{}}'
                return '{"schema_version":"1","action":"finish","args":{"summary":"done"}}'

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "TASK_SPEC.md").write_text("List safe files.", encoding="utf-8")
            (root / "CHECKLIST.md").write_text("", encoding="utf-8")
            (root / "index.html").write_text(
                '<!doctype html><html><head><meta name="viewport" content="width=device-width">'
                '<title>Task</title></head><body><input type="search">safe content</body></html>',
                encoding="utf-8",
            )
            (root / "secret_notes.md").write_text("hidden path", encoding="utf-8")
            llm = ListThenFinishLLM()
            policy = WorkspacePolicy(
                root,
                {"list_files", "finish"},
                {"TASK_SPEC.md", "CHECKLIST.md", "index.html"},
                {"index.html"},
            )

            AgentRunner(root, llm, policy, max_steps=2, context_strategy="compressed-rag").run()

            self.assertEqual(len(llm.contexts), 2)
            self.assertNotIn("secret_notes.md", llm.contexts[1])
            trace_text = (root / "runs" / "latest" / "trace.jsonl").read_text(encoding="utf-8")
            self.assertNotIn("secret_notes.md", trace_text)

    def test_compressed_rag_run_records_compression_evidence_and_metrics(self):
        class LargeFeedbackLLM:
            def __init__(self):
                self.calls = 0

            def complete(self, context: str) -> str:
                self.calls += 1
                if self.calls == 1:
                    return (
                        '{"schema_version":"1","action":"read_file",'
                        '"args":{"path":"notes.md"}}'
                    )
                return '{"schema_version":"1","action":"finish","args":{"summary":"done"}}'

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "TASK_SPEC.md").write_text(
                "The page must display Python LLM Gate search details.",
                encoding="utf-8",
            )
            (root / "CHECKLIST.md").write_text("", encoding="utf-8")
            (root / "notes.md").write_text("Python LLM Gate search details " + ("x" * 5000), encoding="utf-8")
            (root / "index.html").write_text(
                '<!doctype html><html><head><meta name="viewport" content="width=device-width">'
                '<title>Task</title></head><body><input type="search">Python LLM Gate search details</body></html>',
                encoding="utf-8",
            )
            policy = WorkspacePolicy(
                root,
                {"read_file", "finish"},
                {"TASK_SPEC.md", "CHECKLIST.md", "index.html", "notes.md"},
                {"index.html"},
            )

            result = AgentRunner(root, LargeFeedbackLLM(), policy, max_steps=2, context_strategy="compressed-rag").run()

            compression_path = root / "runs" / "latest" / "compression.json"
            self.assertTrue(compression_path.exists())
            compression = json.loads(compression_path.read_text(encoding="utf-8"))
            self.assertGreater(compression["original_chars"], compression["compressed_chars"])
            self.assertEqual(compression["cleared_tool_results"], 1)
            self.assertIsNotNone(result.metrics)
            self.assertGreater(result.metrics.compression_original_chars, 0)
            self.assertGreater(result.metrics.cleared_tool_results, 0)
            trace_events = [
                json.loads(line)["event_type"]
                for line in (root / "runs" / "latest" / "trace.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            self.assertIn("compression_result", trace_events)

    def test_isolated_harness_run_records_isolation_evidence_and_metrics(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "TASK_SPEC.md").write_text(
                "The page must display Python LLM Gate search details.",
                encoding="utf-8",
            )
            (root / "CHECKLIST.md").write_text("", encoding="utf-8")
            (root / "notes.md").write_text("Python LLM Gate search details", encoding="utf-8")
            (root / "index.html").write_text(
                '<!doctype html><html><head><meta name="viewport" content="width=device-width">'
                '<title>Task</title></head><body><input type="search">Python LLM Gate search details</body></html>',
                encoding="utf-8",
            )
            policy = WorkspacePolicy(
                root,
                {"finish"},
                {"TASK_SPEC.md", "CHECKLIST.md", "index.html", "notes.md"},
                {"index.html"},
            )
            llm = MockLLM([{"schema_version": "1", "action": "finish", "args": {"summary": "done"}}])

            result = AgentRunner(root, llm, policy, max_steps=1, context_strategy="isolated-harness").run()

            isolation_path = root / "runs" / "latest" / "isolation.json"
            self.assertTrue(isolation_path.exists())
            isolation = json.loads(isolation_path.read_text(encoding="utf-8"))
            self.assertEqual(isolation["role_contexts"], 3)
            self.assertGreater(isolation["isolated_state_keys"], 0)
            self.assertIsNotNone(result.metrics)
            self.assertEqual(result.metrics.role_contexts, 3)
            self.assertGreater(result.metrics.isolated_state_keys, 0)
            trace_events = [
                json.loads(line)["event_type"]
                for line in (root / "runs" / "latest" / "trace.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            self.assertIn("isolation_result", trace_events)

    def test_non_isolated_run_clears_stale_isolation_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = root / "runs" / "latest"
            run_dir.mkdir(parents=True)
            stale_path = run_dir / "isolation.json"
            stale_path.write_text('{"role_contexts": 99}', encoding="utf-8")
            (root / "TASK_SPEC.md").write_text("Task Search Detail", encoding="utf-8")
            (root / "CHECKLIST.md").write_text("", encoding="utf-8")
            policy = WorkspacePolicy(
                root,
                {"finish"},
                {"TASK_SPEC.md", "CHECKLIST.md", "index.html"},
                {"index.html"},
            )
            llm = MockLLM([{"schema_version": "1", "action": "finish", "args": {"summary": "done"}}])

            AgentRunner(root, llm, policy, max_steps=1, context_strategy="baseline").run()

            self.assertFalse(stale_path.exists())

    def test_isolated_harness_does_not_bypass_workspace_policy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "TASK_SPEC.md").write_text("Write index.html", encoding="utf-8")
            (root / "CHECKLIST.md").write_text("", encoding="utf-8")
            policy = WorkspacePolicy(
                root,
                {"finish"},
                {"TASK_SPEC.md", "CHECKLIST.md", "index.html"},
                {"index.html"},
            )
            llm = MockLLM(
                [
                    {
                        "schema_version": "1",
                        "action": "write_file",
                        "args": {"path": "index.html", "content": FIXED_HTML},
                    }
                ]
            )

            result = AgentRunner(root, llm, policy, max_steps=1, context_strategy="isolated-harness").run()

            self.assertFalse(result.passed)
            self.assertFalse((root / "index.html").exists())
            self.assertIsNotNone(result.metrics)
            self.assertEqual(result.metrics.blocked_actions, 1)

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

    def test_failed_unblocked_write_records_disallowed_permission_decision(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "TASK_SPEC.md").write_text("# task", encoding="utf-8")
            (root / "CHECKLIST.md").write_text("", encoding="utf-8")
            llm = MockLLM(
                [
                    {
                        "schema_version": "1",
                        "action": "write_file",
                        "args": {"path": "index.html", "content": 123},
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

            self.assertIsNotNone(result.permission_decisions)
            decision = result.permission_decisions[0]
            self.assertFalse(decision.allowed)
            self.assertFalse(decision.blocked)
            self.assertIn("content must be a string", decision.reason)
            self.assertIsNotNone(result.metrics)
            self.assertEqual(result.metrics.tool_calls, 1)
            self.assertEqual(result.metrics.successful_tool_calls, 0)

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

    def test_review_profile_creates_pending_approval_without_mutating_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "TASK_SPEC.md").write_text("# task", encoding="utf-8")
            (root / "CHECKLIST.md").write_text("", encoding="utf-8")
            (root / "README.md").write_text("original", encoding="utf-8")
            (root / "index.html").write_text(
                '<!doctype html><html><head><meta name="viewport" content="width=device-width">'
                '<title>Task</title></head><body><input type="search">Task Search Detail</body></html>',
                encoding="utf-8",
            )
            llm = ApprovalFeedbackLLM()
            policy = WorkspacePolicy(root, {"replace_file", "finish"}, {"TASK_SPEC.md"}, {"README.md"})
            from specgate.approvals import GovernanceConfig, approval_queue_path

            result = AgentRunner(
                root,
                llm,
                policy,
                max_steps=2,
                governance_profile="review",
                governance_config=GovernanceConfig(
                    profile="review",
                    review_actions={"replace_file"},
                    review_paths={"README.md"},
                ),
            ).run()

            self.assertEqual((root / "README.md").read_text(encoding="utf-8"), "original")
            self.assertTrue(approval_queue_path(root).exists())
            self.assertIn("approval-step-1", approval_queue_path(root).read_text(encoding="utf-8"))
            self.assertEqual(result.metrics.approval_requests, 1)
            self.assertEqual(result.metrics.pending_approvals, 1)
            self.assertIsNotNone(result.permission_decisions)
            self.assertGreaterEqual(len(result.permission_decisions), 1)
            decision = result.permission_decisions[0]
            self.assertEqual(decision.action, "replace_file")
            self.assertFalse(decision.allowed)
            self.assertFalse(decision.blocked)
            self.assertIn("requires human review", decision.reason)
            self.assertEqual(decision.profile, "review")
            self.assertEqual(result.trust.status, "warning")
            self.assertEqual(len(llm.contexts), 2)
            self.assertIn("approval_requested", llm.contexts[1])
            trace_events = [
                json.loads(line)["event_type"]
                for line in (root / "runs" / "latest" / "trace.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            self.assertIn("permission_decision", trace_events)
            self.assertIn("approval_requested", trace_events)

    def test_workspace_review_governance_config_sets_runner_profile_when_not_overridden(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "TASK_SPEC.md").write_text("# task", encoding="utf-8")
            (root / "CHECKLIST.md").write_text("", encoding="utf-8")
            (root / "README.md").write_text("original", encoding="utf-8")
            llm = ApprovalFeedbackLLM()
            policy = WorkspacePolicy(root, {"replace_file", "finish"}, {"TASK_SPEC.md"}, {"README.md"})

            result = AgentRunner(
                root,
                llm,
                policy,
                max_steps=2,
                governance_config=GovernanceConfig(
                    profile="review",
                    review_actions={"replace_file"},
                    review_paths={"README.md"},
                ),
            ).run()

            self.assertEqual(result.profile, "review")
            self.assertEqual((root / "README.md").read_text(encoding="utf-8"), "original")
            self.assertTrue(approval_queue_path(root).exists())
            self.assertEqual(result.metrics.approval_requests, 1)
            self.assertEqual(result.metrics.pending_approvals, 1)
            self.assertEqual(result.permission_decisions[0].profile, "review")

    def test_strict_profile_blocks_review_action_without_creating_approval(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "TASK_SPEC.md").write_text("# task", encoding="utf-8")
            (root / "CHECKLIST.md").write_text("", encoding="utf-8")
            (root / "README.md").write_text("original", encoding="utf-8")
            llm = ApprovalFeedbackLLM()
            policy = WorkspacePolicy(root, {"replace_file", "finish"}, {"TASK_SPEC.md"}, {"README.md"})
            from specgate.approvals import GovernanceConfig, approval_queue_path

            result = AgentRunner(
                root,
                llm,
                policy,
                max_steps=2,
                governance_profile="strict",
                governance_config=GovernanceConfig(
                    profile="strict",
                    review_actions={"replace_file"},
                    review_paths={"README.md"},
                ),
            ).run()

            self.assertEqual((root / "README.md").read_text(encoding="utf-8"), "original")
            self.assertFalse(approval_queue_path(root).exists())
            self.assertEqual(result.metrics.blocked_actions, 1)
            self.assertEqual(len(llm.contexts), 2)
            self.assertIn("Runtime Feedback", llm.contexts[1])
            self.assertIn("tool_result", llm.contexts[1])
            self.assertIn("blocked", llm.contexts[1])
            self.assertIn("requires human review", llm.contexts[1])
            trace_events = [
                json.loads(line)["event_type"]
                for line in (root / "runs" / "latest" / "trace.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            self.assertIn("permission_decision", trace_events)


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
