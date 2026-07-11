import unittest

from specgate.context_lifecycle import (
    CompressionConfig,
    compress_runtime_feedback,
    pin_critical_sections,
)


class ContextLifecycleTests(unittest.TestCase):
    def test_compress_runtime_feedback_clears_large_tool_result_but_keeps_status(self):
        feedback = [
            {
                "event_type": "tool_result",
                "payload": {
                    "action": "read_file",
                    "result": {
                        "ok": True,
                        "blocked": False,
                        "status": "safe",
                        "message": "read notes.md",
                        "data": {"path": "notes.md", "content": "x" * 5000},
                    },
                },
            }
        ]

        summary = compress_runtime_feedback(feedback, CompressionConfig(max_tool_result_chars=80))

        rendered = summary.rendered_events[0]
        self.assertIn("[cleared tool result", rendered)
        self.assertIn('"action": "read_file"', rendered)
        self.assertIn('"ok": true', rendered)
        self.assertIn('"blocked": false', rendered)
        self.assertIn('"status": "safe"', rendered)
        self.assertIn('"message": "read notes.md"', rendered)
        self.assertIn('"path": "notes.md"', rendered)
        self.assertNotIn("x" * 200, rendered)
        self.assertEqual(summary.cleared_tool_results, 1)
        self.assertLess(summary.compressed_chars, summary.original_chars)

    def test_compress_runtime_feedback_preserves_false_blocked_from_runner_shape(self):
        feedback = [
            {
                "type": "tool_result",
                "action": "read_file",
                "ok": True,
                "blocked": False,
                "message": "read notes.md",
                "data": {"path": "notes.md", "content": "x" * 5000},
            }
        ]

        summary = compress_runtime_feedback(feedback, CompressionConfig(max_tool_result_chars=80))

        rendered = summary.rendered_events[0]
        self.assertIn('"blocked": false', rendered)
        self.assertIn('"path": "notes.md"', rendered)

    def test_compress_runtime_feedback_summarizes_large_non_tool_event(self):
        feedback = [{"event_type": "llm_response", "payload": {"text": "y" * 5000}}]

        summary = compress_runtime_feedback(feedback, CompressionConfig(max_tool_result_chars=120))

        self.assertIn("[summarized event", summary.rendered_events[0])
        self.assertNotIn("y" * 200, summary.rendered_events[0])
        self.assertEqual(summary.cleared_tool_results, 0)

    def test_compress_runtime_feedback_budget_keeps_latest_event(self):
        feedback = [
            {"event_type": "tool_result", "payload": {"action": "read_file", "result": {"ok": True, "message": f"old-{index}"}}}
            for index in range(20)
        ]
        feedback.append({"event_type": "parse_error", "payload": {"error": "latest-important-error"}})

        summary = compress_runtime_feedback(
            feedback,
            CompressionConfig(max_tool_result_chars=200, summary_budget_chars=260),
        )

        rendered = "\n".join(summary.rendered_events)
        self.assertIn("latest-important-error", rendered)
        self.assertNotIn("old-0", rendered)

    def test_compress_runtime_feedback_tiny_budget_stays_under_budget(self):
        feedback = [{"event_type": "parse_error", "payload": {"error": "latest-important-error"}}]

        summary = compress_runtime_feedback(feedback, CompressionConfig(summary_budget_chars=20))

        self.assertLessEqual(summary.compressed_chars, 20)

    def test_pin_critical_sections_puts_constraints_policy_and_gate_at_end(self):
        sections = [
            ("Memory", "old memory"),
            ("Task Constraints", "must include search"),
            ("Policy Boundary", "write only index.html"),
            ("Latest Gate Feedback", "missing details"),
        ]

        pinned = pin_critical_sections(sections)

        self.assertEqual(
            [name for name, _ in pinned[-3:]],
            ["Task Constraints", "Policy Boundary", "Latest Gate Feedback"],
        )


if __name__ == "__main__":
    unittest.main()
