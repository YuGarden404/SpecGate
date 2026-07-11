from __future__ import annotations

from dataclasses import dataclass, field

from specgate.isolation import RoleExecution


ROLE_SEQUENCE = ("planner", "implementer", "reviewer")


@dataclass
class MultiAgentState:
    plan: str = ""
    review_notes: str = ""
    repair_requested: bool = False
    review_repairs: int = 0
    executions: list[RoleExecution] = field(default_factory=list)

    def to_shared_state(self) -> dict[str, object]:
        return {
            "plan": self.plan,
            "review_notes": self.review_notes,
            "repair_requested": self.repair_requested,
            "review_repairs": self.review_repairs,
        }
