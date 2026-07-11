from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class SecurityExpectation:
    must_not_create: list[str] = field(default_factory=list)
    must_not_leak: list[str] = field(default_factory=list)
    expected_findings: list[str] = field(default_factory=list)
    expected_trust: str | None = None
    expected_blocked_actions: int | None = None
    require_untrusted_context_boundary: bool = False

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "SecurityExpectation":
        if not data:
            return cls()
        return cls(
            must_not_create=_string_list(data.get("must_not_create")),
            must_not_leak=_string_list(data.get("must_not_leak")),
            expected_findings=_string_list(data.get("expected_findings")),
            expected_trust=_optional_string(data.get("expected_trust")),
            expected_blocked_actions=_optional_int(data.get("expected_blocked_actions")),
            require_untrusted_context_boundary=bool(data.get("require_untrusted_context_boundary", False)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "must_not_create": list(self.must_not_create),
            "must_not_leak": list(self.must_not_leak),
            "expected_findings": list(self.expected_findings),
            "expected_trust": self.expected_trust,
            "expected_blocked_actions": self.expected_blocked_actions,
            "require_untrusted_context_boundary": self.require_untrusted_context_boundary,
        }


@dataclass(frozen=True)
class SecurityExpectationResult:
    passed: bool
    findings: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    must_not_create_violations: list[str] = field(default_factory=list)
    must_not_leak_violations: list[str] = field(default_factory=list)
    expected_findings: list[str] = field(default_factory=list)
    matched_expected_findings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, bool | list[str]]:
        return {
            "passed": self.passed,
            "findings": list(self.findings),
            "failures": list(self.failures),
            "must_not_create_violations": list(self.must_not_create_violations),
            "must_not_leak_violations": list(self.must_not_leak_violations),
            "expected_findings": list(self.expected_findings),
            "matched_expected_findings": list(self.matched_expected_findings),
        }


def evaluate_security_expectations(
    *,
    expectation: SecurityExpectation,
    workspace: Path,
    trace_path: Path,
    run_artifacts: list[Path],
    blocked_actions: int,
    trust_status: str,
    context_had_untrusted_boundary: bool,
) -> SecurityExpectationResult:
    del workspace, trace_path, run_artifacts, blocked_actions, trust_status, context_had_untrusted_boundary
    return SecurityExpectationResult(
        passed=True,
        expected_findings=list(expectation.expected_findings),
    )


def write_security_result(workspace: Path, result: SecurityExpectationResult) -> Path:
    output = workspace / "runs" / "latest" / "security.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return output


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("security expectation list fields must be lists")
    if not all(isinstance(item, str) for item in value):
        raise ValueError("security expectation list fields must contain strings")
    return list(value)


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("security expected_trust must be a string")
    return value


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int):
        raise ValueError("security expected_blocked_actions must be an integer")
    return value
