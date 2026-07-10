import unittest

from specgate.metrics import (
    PermissionDecision,
    RunMetrics,
    build_trust_summary,
    classify_rule_family,
)


class MetricsTests(unittest.TestCase):
    def test_classifies_rule_family_from_reason(self):
        self.assertEqual(classify_rule_family("unknown action: run_command"), "action")
        self.assertEqual(classify_rule_family("path escapes workspace"), "path")
        self.assertEqual(classify_rule_family("write path not allowed: .env"), "allowlist")
        self.assertEqual(classify_rule_family("file changed since run started"), "snapshot")
        self.assertEqual(classify_rule_family("unknown tool: shell"), "tool")
        self.assertEqual(classify_rule_family("finish requested"), "none")

    def test_permission_decision_from_tool_result_shape(self):
        decision = PermissionDecision(
            step=2,
            action="write_file",
            path=".env",
            allowed=False,
            blocked=True,
            reason="write path not allowed: .env",
            profile="strict",
            rule_family="allowlist",
        )

        self.assertEqual(decision.step, 2)
        self.assertFalse(decision.allowed)
        self.assertTrue(decision.blocked)
        self.assertEqual(decision.rule_family, "allowlist")

    def test_trusted_summary_requires_clean_finish_and_passing_gate(self):
        metrics = RunMetrics(
            steps=2,
            llm_calls=2,
            tool_calls=2,
            successful_tool_calls=2,
            finish_actions=1,
        )

        trust = build_trust_summary(True, metrics)

        self.assertEqual(trust.status, "trusted")
        self.assertEqual(trust.reasons, ["clean_finish"])

    def test_warning_summary_when_gate_passes_with_blocked_action(self):
        metrics = RunMetrics(
            steps=3,
            llm_calls=3,
            tool_calls=3,
            successful_tool_calls=2,
            blocked_actions=1,
            finish_actions=1,
        )

        trust = build_trust_summary(True, metrics)

        self.assertEqual(trust.status, "warning")
        self.assertIn("blocked_actions_present", trust.reasons)

    def test_failed_summary_when_gate_fails_or_max_steps_reached(self):
        gate_failed = build_trust_summary(False, RunMetrics(steps=1, max_steps_reached=False))
        exhausted = build_trust_summary(True, RunMetrics(steps=5, max_steps_reached=True))

        self.assertEqual(gate_failed.status, "failed")
        self.assertIn("gate_failed", gate_failed.reasons)
        self.assertEqual(exhausted.status, "failed")
        self.assertIn("max_steps_reached", exhausted.reasons)


if __name__ == "__main__":
    unittest.main()
