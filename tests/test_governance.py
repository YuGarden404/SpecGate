import tempfile
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest import mock

from specgate.actions import Action
from specgate.approvals import ActionRisk, GovernanceConfig
from specgate.governance import (
    GovernanceDecisionKind,
    GovernanceEngine,
)
from specgate.policy import WorkspacePolicy
from specgate.tool_registry import default_tool_registry
from specgate.tool_runtime import ToolRuntime


class GovernanceEngineTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        self.engine = GovernanceEngine()
        self.runtime = ToolRuntime(default_tool_registry())

    def _prepare(self, action: Action):
        preparation = self.runtime.prepare(action)
        self.assertIsNotNone(preparation.call)
        self.assertIsNone(preparation.failure)
        return preparation.call

    def test_capability_cannot_expand_workspace_policy(self):
        call = self._prepare(
            Action(
                "1",
                "write_file",
                {"path": "index.html", "content": "x"},
            )
        )
        policy = WorkspacePolicy(
            self.root,
            {"read_file"},
            {"index.html"},
            set(),
        )

        decision = self.engine.evaluate(
            call,
            capabilities=frozenset({"write_file"}),
            policy=policy,
            config=GovernanceConfig(profile="strict"),
        )

        self.assertEqual(decision.kind, GovernanceDecisionKind.BLOCK)
        self.assertEqual(decision.code, "action")
        self.assertEqual(decision.rule_family, "action")

    def test_missing_capability_blocks_before_workspace_policy(self):
        call = self._prepare(
            Action(
                "1",
                "write_file",
                {"path": "index.html", "content": "x"},
            )
        )
        policy = WorkspacePolicy(
            self.root,
            {"write_file"},
            set(),
            {"index.html"},
        )

        decision = self.engine.evaluate(
            call,
            capabilities=frozenset({"read_file"}),
            policy=policy,
            config=GovernanceConfig(profile="review"),
        )

        self.assertEqual(decision.kind, GovernanceDecisionKind.BLOCK)
        self.assertEqual(decision.code, "capability")
        self.assertEqual(decision.rule_family, "capability")

    def test_review_profile_requires_approval_for_review_risk(self):
        call = self._prepare(
            Action(
                "1",
                "write_file",
                {"path": "index.html", "content": "x"},
            )
        )
        policy = WorkspacePolicy(
            self.root,
            {"write_file"},
            set(),
            {"index.html"},
        )

        decision = self.engine.evaluate(
            call,
            capabilities=frozenset({"write_file"}),
            policy=policy,
            config=GovernanceConfig(
                profile="review",
                review_actions={"write_file"},
            ),
        )

        self.assertEqual(
            decision.kind,
            GovernanceDecisionKind.REQUIRE_APPROVAL,
        )
        self.assertEqual(decision.code, "review")
        self.assertEqual(decision.risk.level, "review")

    def test_strict_profile_blocks_the_same_review_risk(self):
        call = self._prepare(
            Action(
                "1",
                "write_file",
                {"path": "index.html", "content": "x"},
            )
        )
        policy = WorkspacePolicy(
            self.root,
            {"write_file"},
            set(),
            {"index.html"},
        )

        decision = self.engine.evaluate(
            call,
            capabilities=frozenset({"write_file"}),
            policy=policy,
            config=GovernanceConfig(
                profile="strict",
                review_actions={"write_file"},
            ),
        )

        self.assertEqual(decision.kind, GovernanceDecisionKind.BLOCK)
        self.assertEqual(decision.code, "review")
        self.assertEqual(decision.risk.level, "review")

    def test_safe_action_is_allowed(self):
        call = self._prepare(
            Action("1", "read_file", {"path": "README.md"})
        )
        policy = WorkspacePolicy(
            self.root,
            {"read_file"},
            {"README.md"},
            set(),
        )

        decision = self.engine.evaluate(
            call,
            capabilities=frozenset({"read_file"}),
            policy=policy,
            config=GovernanceConfig(profile="strict"),
        )

        self.assertEqual(decision.kind, GovernanceDecisionKind.ALLOW)
        self.assertEqual(decision.code, "safe")
        self.assertEqual(decision.risk.level, "safe")

    def test_unknown_risk_level_fails_closed(self):
        call = self._prepare(
            Action("1", "read_file", {"path": "README.md"})
        )
        policy = WorkspacePolicy(
            self.root,
            {"read_file"},
            {"README.md"},
            set(),
        )

        with mock.patch(
            "specgate.governance.classify_action_risk",
            return_value=ActionRisk("unknown", "unexpected risk"),
        ):
            decision = self.engine.evaluate(
                call,
                capabilities=frozenset({"read_file"}),
                policy=policy,
                config=GovernanceConfig(profile="strict"),
            )

        self.assertEqual(decision.kind, GovernanceDecisionKind.BLOCK)
        self.assertEqual(decision.code, "invalid_risk")
        self.assertEqual(decision.rule_family, "governance")

    def test_decision_is_frozen(self):
        call = self._prepare(
            Action("1", "read_file", {"path": "README.md"})
        )
        policy = WorkspacePolicy(
            self.root,
            {"read_file"},
            {"README.md"},
            set(),
        )
        decision = self.engine.evaluate(
            call,
            capabilities=frozenset({"read_file"}),
            policy=policy,
            config=GovernanceConfig(),
        )

        with self.assertRaises(FrozenInstanceError):
            decision.code = "changed"


if __name__ == "__main__":
    unittest.main()
