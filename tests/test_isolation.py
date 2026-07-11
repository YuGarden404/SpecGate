import unittest

from specgate.isolation import (
    RoleContext,
    RoleExecution,
    action_allowed_for_role,
    build_isolation_evidence,
    build_role_contexts,
    filter_state_for_role,
)


class IsolationTests(unittest.TestCase):
    def test_filter_state_for_role_hides_unlisted_state_keys(self):
        state = {
            "task": "build dashboard",
            "plan": "step 1",
            "draft_patch": "<html>draft</html>",
            "review_notes": "missing search",
        }

        visible = filter_state_for_role("reviewer", state)

        self.assertIn("task", visible)
        self.assertIn("review_notes", visible)
        self.assertNotIn("draft_patch", visible)

    def test_filter_state_for_role_rejects_unknown_role(self):
        with self.assertRaises(ValueError):
            filter_state_for_role("unknown", {"task": "x"})

    def test_build_role_contexts_defines_planner_implementer_reviewer(self):
        contexts = build_role_contexts()

        self.assertTrue(all(isinstance(context, RoleContext) for context in contexts))
        roles = [context.role for context in contexts]
        self.assertEqual(roles, ["planner", "implementer", "reviewer"])
        reviewer = next(context for context in contexts if context.role == "reviewer")
        self.assertNotIn("draft_patch", reviewer.state_keys)
        self.assertIn("review_notes", reviewer.state_keys)
        self.assertIn("finish", reviewer.allowed_actions)


class IsolationCapabilityTests(unittest.TestCase):
    def test_planner_and_reviewer_cannot_write_files(self):
        self.assertFalse(action_allowed_for_role("planner", "write_file"))
        self.assertFalse(action_allowed_for_role("planner", "replace_file"))
        self.assertFalse(action_allowed_for_role("reviewer", "write_file"))
        self.assertFalse(action_allowed_for_role("reviewer", "replace_file"))

    def test_implementer_can_write_files(self):
        self.assertTrue(action_allowed_for_role("implementer", "write_file"))
        self.assertTrue(action_allowed_for_role("implementer", "replace_file"))
        self.assertTrue(action_allowed_for_role("implementer", "finish"))

    def test_action_allowed_for_role_rejects_unknown_role(self):
        with self.assertRaises(ValueError):
            action_allowed_for_role("auditor", "finish")

    def test_role_execution_to_dict_is_serializable(self):
        execution = RoleExecution(
            role="planner",
            phase="plan",
            context_chars=123,
            visible_sections=("Task", "Checklist"),
            allowed_actions=("read_file", "finish"),
            attempted_action="finish",
            action_allowed_by_role=True,
            blocked_reason=None,
            summary="Plan the page",
        )

        self.assertEqual(
            execution.to_dict(),
            {
                "role": "planner",
                "phase": "plan",
                "context_chars": 123,
                "visible_sections": ["Task", "Checklist"],
                "allowed_actions": ["read_file", "finish"],
                "attempted_action": "finish",
                "action_allowed_by_role": True,
                "blocked_reason": None,
                "summary": "Plan the page",
            },
        )

    def test_build_isolation_evidence_includes_executions(self):
        execution = RoleExecution(
            role="reviewer",
            phase="review",
            context_chars=321,
            visible_sections=("Final Artifact",),
            allowed_actions=("finish",),
            attempted_action="write_file",
            action_allowed_by_role=False,
            blocked_reason="role reviewer cannot perform write_file",
            summary=None,
        )

        evidence = build_isolation_evidence(
            strategy="multi-agent-isolated",
            executions=[execution],
            review_repairs=1,
        )

        self.assertEqual(evidence["strategy"], "multi-agent-isolated")
        self.assertEqual(evidence["role_runs"], 1)
        self.assertEqual(evidence["role_blocked_actions"], 1)
        self.assertEqual(evidence["review_repairs"], 1)
        self.assertEqual(evidence["executions"][0]["role"], "reviewer")


if __name__ == "__main__":
    unittest.main()
