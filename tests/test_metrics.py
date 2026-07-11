import unittest

from specgate.metrics import (
    PermissionDecision,
    RunMetrics,
    TrustSummary,
    build_trust_summary,
    classify_rule_family,
)


class MetricsTests(unittest.TestCase):
    def test_classifies_rule_family_from_reason(self):
        self.assertEqual(classify_rule_family("unknown action: run_command"), "action")
        self.assertEqual(classify_rule_family("unimplemented action: network"), "action")
        self.assertEqual(classify_rule_family("path escapes workspace"), "path")
        self.assertEqual(classify_rule_family("path must be relative"), "path")
        self.assertEqual(classify_rule_family("missing required path"), "path")
        self.assertEqual(classify_rule_family("write path not allowed: .env"), "allowlist")
        self.assertEqual(classify_rule_family("file changed since run started"), "snapshot")
        self.assertEqual(classify_rule_family("snapshot mismatch: changed since run started"), "snapshot")
        self.assertEqual(classify_rule_family("unknown tool: shell"), "tool")
        self.assertEqual(classify_rule_family("tool call rejected"), "tool")
        self.assertEqual(classify_rule_family("finish requested"), "none")
        self.assertEqual(classify_rule_family("model not allowed by provider"), "none")

    def test_run_metrics_has_complete_defaults_and_to_dict(self):
        metrics = RunMetrics()

        self.assertEqual(
            metrics.to_dict(),
            {
                "steps": 0,
                "context_chars_max": 0,
                "llm_calls": 0,
                "tool_calls": 0,
                "successful_tool_calls": 0,
                "blocked_actions": 0,
                "parse_errors": 0,
                "gate_runs": 0,
                "gate_failures": 0,
                "finish_actions": 0,
                "approval_requests": 0,
                "pending_approvals": 0,
                "approved_approvals": 0,
                "denied_approvals": 0,
                "applied_approvals": 0,
                "failed_approvals": 0,
                "retrieval_queries": 0,
                "retrieved_chunks": 0,
                "retrieval_candidate_chunks": 0,
                "retrieval_context_chars": 0,
                "compression_original_chars": 0,
                "compression_compressed_chars": 0,
                "cleared_tool_results": 0,
                "role_contexts": 0,
                "isolated_state_keys": 0,
                "role_runs": 0,
                "role_blocked_actions": 0,
                "review_repairs": 0,
                "planner_runs": 0,
                "implementer_runs": 0,
                "reviewer_runs": 0,
                "role_cycle_limit_reached": False,
                "max_steps_reached": False,
            },
        )

    def test_run_metrics_to_dict_includes_complete_fields(self):
        metrics = RunMetrics(
            steps=7,
            context_chars_max=4096,
            llm_calls=6,
            tool_calls=5,
            successful_tool_calls=4,
            blocked_actions=3,
            parse_errors=2,
            gate_runs=2,
            gate_failures=1,
            finish_actions=1,
            approval_requests=2,
            pending_approvals=1,
            approved_approvals=1,
            denied_approvals=1,
            applied_approvals=1,
            failed_approvals=1,
            retrieval_queries=1,
            retrieved_chunks=3,
            retrieval_candidate_chunks=8,
            retrieval_context_chars=1200,
            compression_original_chars=2000,
            compression_compressed_chars=500,
            cleared_tool_results=2,
            role_contexts=3,
            isolated_state_keys=9,
            role_runs=3,
            role_blocked_actions=1,
            review_repairs=2,
            planner_runs=1,
            implementer_runs=1,
            reviewer_runs=1,
            role_cycle_limit_reached=True,
            max_steps_reached=True,
        )

        self.assertEqual(
            metrics.to_dict(),
            {
                "steps": 7,
                "context_chars_max": 4096,
                "llm_calls": 6,
                "tool_calls": 5,
                "successful_tool_calls": 4,
                "blocked_actions": 3,
                "parse_errors": 2,
                "gate_runs": 2,
                "gate_failures": 1,
                "finish_actions": 1,
                "approval_requests": 2,
                "pending_approvals": 1,
                "approved_approvals": 1,
                "denied_approvals": 1,
                "applied_approvals": 1,
                "failed_approvals": 1,
                "retrieval_queries": 1,
                "retrieved_chunks": 3,
                "retrieval_candidate_chunks": 8,
                "retrieval_context_chars": 1200,
                "compression_original_chars": 2000,
                "compression_compressed_chars": 500,
                "cleared_tool_results": 2,
                "role_contexts": 3,
                "isolated_state_keys": 9,
                "role_runs": 3,
                "role_blocked_actions": 1,
                "review_repairs": 2,
                "planner_runs": 1,
                "implementer_runs": 1,
                "reviewer_runs": 1,
                "role_cycle_limit_reached": True,
                "max_steps_reached": True,
            },
        )

    def test_run_metrics_includes_retrieval_fields(self):
        metrics = RunMetrics(
            retrieval_queries=1,
            retrieved_chunks=3,
            retrieval_candidate_chunks=8,
            retrieval_context_chars=900,
        )

        data = metrics.to_dict()

        self.assertEqual(data["retrieval_queries"], 1)
        self.assertEqual(data["retrieved_chunks"], 3)
        self.assertEqual(data["retrieval_candidate_chunks"], 8)
        self.assertEqual(data["retrieval_context_chars"], 900)

    def test_run_metrics_includes_role_level_fields(self):
        metrics = RunMetrics(
            role_runs=3,
            role_blocked_actions=1,
            review_repairs=1,
            planner_runs=1,
            implementer_runs=1,
            reviewer_runs=1,
        )

        data = metrics.to_dict()

        self.assertEqual(data["role_runs"], 3)
        self.assertEqual(data["role_blocked_actions"], 1)
        self.assertEqual(data["review_repairs"], 1)
        self.assertEqual(data["planner_runs"], 1)
        self.assertEqual(data["implementer_runs"], 1)
        self.assertEqual(data["reviewer_runs"], 1)

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

    def test_permission_decision_defaults_and_to_dict(self):
        decision = PermissionDecision(
            step=1,
            action="finish",
            path=None,
            allowed=True,
            blocked=False,
            reason="finish requested",
        )

        self.assertEqual(decision.profile, "strict")
        self.assertEqual(decision.rule_family, "none")
        self.assertEqual(
            decision.to_dict(),
            {
                "step": 1,
                "action": "finish",
                "path": None,
                "allowed": True,
                "blocked": False,
                "reason": "finish requested",
                "profile": "strict",
                "rule_family": "none",
            },
        )

    def test_trust_summary_to_dict(self):
        summary = TrustSummary("warning", ["parse_errors_present"])

        self.assertEqual(
            summary.to_dict(),
            {"status": "warning", "reasons": ["parse_errors_present"]},
        )

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

    def test_trusted_summary_uses_final_gate_verdict_not_historical_failures(self):
        trust = build_trust_summary(True, RunMetrics(finish_actions=1, gate_failures=1))

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

    def test_warning_summary_when_role_blocked_actions_present(self):
        trust = build_trust_summary(
            True,
            RunMetrics(finish_actions=1, role_blocked_actions=1),
        )

        self.assertEqual(trust.status, "warning")
        self.assertIn("role_blocked_actions_present", trust.reasons)

    def test_warning_summary_when_gate_passes_with_parse_errors(self):
        metrics = RunMetrics(
            steps=3,
            parse_errors=1,
            finish_actions=1,
        )

        trust = build_trust_summary(True, metrics)

        self.assertEqual(trust.status, "warning")
        self.assertIn("parse_errors_present", trust.reasons)

    def test_warning_summary_when_gate_passes_with_pending_approval(self):
        metrics = RunMetrics(steps=2, finish_actions=1, approval_requests=1, pending_approvals=1)

        trust = build_trust_summary(True, metrics)

        self.assertEqual(trust.status, "warning")
        self.assertIn("pending_approvals_present", trust.reasons)

    def test_warning_summary_when_gate_passes_with_human_denial(self):
        trust = build_trust_summary(True, RunMetrics(finish_actions=1, denied_approvals=1))

        self.assertEqual(trust.status, "warning")
        self.assertIn("human_denial_present", trust.reasons)

    def test_failed_summary_when_gate_passes_with_failed_approval(self):
        trust = build_trust_summary(True, RunMetrics(finish_actions=1, failed_approvals=1))

        self.assertEqual(trust.status, "failed")
        self.assertIn("approval_failed", trust.reasons)

    def test_failed_summary_when_finish_is_missing(self):
        trust = build_trust_summary(True, RunMetrics(steps=2, finish_actions=0))

        self.assertEqual(trust.status, "failed")
        self.assertIn("missing_finish", trust.reasons)

    def test_failed_summary_when_gate_fails_or_max_steps_reached(self):
        gate_failed = build_trust_summary(False, RunMetrics(steps=1, max_steps_reached=False))
        exhausted = build_trust_summary(True, RunMetrics(steps=5, max_steps_reached=True))

        self.assertEqual(gate_failed.status, "failed")
        self.assertIn("gate_failed", gate_failed.reasons)
        self.assertEqual(exhausted.status, "failed")
        self.assertIn("max_steps_reached", exhausted.reasons)

    def test_failed_summary_when_role_cycle_limit_reached(self):
        trust = build_trust_summary(
            True,
            RunMetrics(finish_actions=1, role_cycle_limit_reached=True),
        )

        self.assertEqual(trust.status, "failed")
        self.assertIn("role_cycle_limit_reached", trust.reasons)


if __name__ == "__main__":
    unittest.main()
