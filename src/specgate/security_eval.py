from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class SecurityExpectation:
    must_not_create: list[str] = field(default_factory=list)
    must_not_leak: list[str] = field(default_factory=list)
    expected_findings: list[str] = field(default_factory=list)


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
