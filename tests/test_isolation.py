import unittest

from specgate.isolation import RoleContext, build_role_contexts, filter_state_for_role


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


if __name__ == "__main__":
    unittest.main()
