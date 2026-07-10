from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class EvalCase:
    case_id: str
    title: str
    category: str
    path: Path
    expected_should_pass: bool | None
    expected_must_block: bool | None


@dataclass(frozen=True)
class EvalCaseResult:
    case_id: str
    strategy: str
    passed: bool
    expected_passed: bool | None
    expected_match: bool
    steps: int
    parse_errors: int
    blocked_actions: int
    gate_failures: int
    context_chars_max: int
    final_summary: str


@dataclass(frozen=True)
class EvalSuiteResult:
    strategy: str
    total_cases: int
    passed_cases: int
    expected_matches: int
    results: list[EvalCaseResult]


def discover_eval_cases(root: Path) -> list[EvalCase]:
    if not root.exists():
        return []

    cases: list[EvalCase] = []
    for item in sorted(root.iterdir(), key=lambda path: path.name):
        if not item.is_dir():
            continue
        meta_path = item / "case.json"
        if not meta_path.exists():
            continue

        meta = json.loads(meta_path.read_text(encoding="utf-8-sig"))
        expected = meta.get("expected") or {}
        case_id = str(meta["id"])
        cases.append(
            EvalCase(
                case_id=case_id,
                title=str(meta.get("title", case_id)),
                category=str(meta.get("category", "uncategorized")),
                path=item,
                expected_should_pass=expected.get("should_pass"),
                expected_must_block=expected.get("must_block"),
            )
        )
    return cases
