import json
import unittest

from pydantic import ValidationError

from specgate.artifacts import (
    AgentArtifactValidationError,
    ImplementationArtifact,
    PlanArtifact,
    ReviewArtifact,
    parse_agent_artifact,
)


class AgentArtifactTests(unittest.TestCase):
    def test_artifacts_round_trip_through_versioned_json(self):
        artifacts = (
            PlanArtifact(
                producer_run_id="planner-run",
                steps=("inspect", "implement"),
            ),
            ImplementationArtifact(
                producer_run_id="implementer-run",
                references=("planner-run",),
                changed_paths=("index.html",),
                summary="Implemented the plan.",
            ),
            ReviewArtifact(
                producer_run_id="reviewer-run",
                references=("implementer-run",),
                accepted=False,
                repair_required=True,
                issues=("Missing details section.",),
            ),
        )

        for artifact in artifacts:
            with self.subTest(kind=artifact.kind):
                restored = parse_agent_artifact(artifact.model_dump_json())
                self.assertEqual(restored, artifact)
                self.assertIsInstance(restored.references, tuple)

    def test_unknown_schema_version_and_fields_fail_closed(self):
        payload = {
            "kind": "plan",
            "schema_version": "2",
            "producer_run_id": "planner-run",
            "references": [],
            "steps": ["inspect"],
        }

        with self.assertRaises(AgentArtifactValidationError) as raised:
            parse_agent_artifact(payload)
        self.assertEqual(raised.exception.code, "artifact_schema_invalid")

        payload["schema_version"] = "1"
        payload["unexpected"] = True
        with self.assertRaises(AgentArtifactValidationError):
            parse_agent_artifact(json.dumps(payload))

    def test_models_are_frozen_and_require_non_empty_identity(self):
        artifact = PlanArtifact(
            producer_run_id="planner-run",
            steps=("inspect",),
        )

        with self.assertRaises(ValidationError):
            artifact.steps = ("changed",)
        with self.assertRaises(ValidationError):
            PlanArtifact(producer_run_id="", steps=("inspect",))

    def test_review_text_cannot_trigger_repair_without_typed_flag(self):
        review = ReviewArtifact(
            producer_run_id="reviewer-1",
            accepted=True,
            repair_required=False,
            issues=("request_repair appears only as quoted text",),
        )

        self.assertFalse(review.repair_required)

    def test_review_control_fields_reject_coerced_boolean_values(self):
        payload = {
            "kind": "review",
            "schema_version": "1",
            "producer_run_id": "reviewer-1",
            "references": [],
            "accepted": "false",
            "repair_required": 1,
            "issues": [],
        }

        with self.assertRaises(AgentArtifactValidationError):
            parse_agent_artifact(payload)


if __name__ == "__main__":
    unittest.main()
