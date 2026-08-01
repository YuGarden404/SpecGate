from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field, fields, replace
from enum import Enum
import json
from pathlib import Path
from threading import Lock
from typing import Any, Protocol

import specgate.workspace_fs as workspace_fs
from specgate.gate import GateCheck, GateIssue, GateResult
from specgate.metrics import RunMetrics, add_run_metrics
from specgate.trace import redact


class RunStatus(str, Enum):
    RUNNING = "running"
    NEEDS_APPROVAL = "needs_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


@dataclass(frozen=True)
class Observation:
    kind: str
    payload: dict[str, Any]


@dataclass(frozen=True)
class RunState:
    run_id: str
    revision: int = 0
    status: RunStatus = RunStatus.RUNNING
    step: int = 0
    observations: tuple[Observation, ...] = ()
    latest_gate: GateResult | None = None
    pending_approval_id: str | None = None
    finish_requested: bool = False
    metrics: RunMetrics = field(default_factory=RunMetrics)


@dataclass(frozen=True)
class StateDelta:
    status: RunStatus | None = None
    step: int | None = None
    append_observations: tuple[Observation, ...] = ()
    latest_gate: GateResult | None = None
    pending_approval_id: str | None = None
    clear_pending_approval: bool = False
    finish_requested: bool | None = None
    metrics: RunMetrics = field(default_factory=RunMetrics)


class RunStateConflict(RuntimeError):
    pass


class RunStateFormatError(ValueError):
    pass


class RunStateSerializationError(ValueError):
    pass


class RunStateStore(Protocol):
    def create(self, state: RunState) -> RunState: ...

    def get(self, run_id: str) -> RunState: ...

    def apply(
        self,
        run_id: str,
        expected_revision: int,
        delta: StateDelta,
    ) -> RunState: ...


class InMemoryRunStateStore:
    def __init__(self) -> None:
        self._states: dict[str, RunState] = {}
        self._lock = Lock()

    def create(self, state: RunState) -> RunState:
        with self._lock:
            if state.run_id in self._states:
                raise RunStateConflict(f"run already exists: {state.run_id}")
            owned = deepcopy(state)
            self._states[state.run_id] = owned
            return deepcopy(owned)

    def get(self, run_id: str) -> RunState:
        with self._lock:
            return deepcopy(self._states[run_id])

    def apply(
        self,
        run_id: str,
        expected_revision: int,
        delta: StateDelta,
    ) -> RunState:
        with self._lock:
            current = self._states[run_id]
            if current.revision != expected_revision:
                raise RunStateConflict(
                    "stale run state: "
                    f"expected {expected_revision}, actual {current.revision}"
                )
            updated = _apply_delta(current, delta)
            owned = deepcopy(updated)
            self._states[run_id] = owned
            return deepcopy(owned)


class FileRunStateStore:
    schema_version = "1"
    state_file = "state.json"
    lock_file = "state.json.lock"

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def create(self, state: RunState) -> RunState:
        with workspace_fs.workspace_file_lock(self.root, self.lock_file):
            if self._read_optional() is not None:
                raise RunStateConflict(f"run already exists: {state.run_id}")
            persisted = _persistable_state(state)
            self._write(persisted)
        return deepcopy(persisted)

    def get(self, run_id: str) -> RunState:
        with workspace_fs.workspace_file_lock(self.root, self.lock_file):
            state = self._read_optional()
        if state is None or state.run_id != run_id:
            raise KeyError(run_id)
        return deepcopy(state)

    def apply(
        self,
        run_id: str,
        expected_revision: int,
        delta: StateDelta,
    ) -> RunState:
        with workspace_fs.workspace_file_lock(self.root, self.lock_file):
            current = self._read_optional()
            if current is None or current.run_id != run_id:
                raise KeyError(run_id)
            if current.revision != expected_revision:
                raise RunStateConflict(
                    "stale run state: "
                    f"expected {expected_revision}, actual {current.revision}"
                )
            updated = _persistable_state(_apply_delta(current, delta))
            self._write(updated)
        return deepcopy(updated)

    def _read_optional(self) -> RunState | None:
        try:
            text = workspace_fs.read_workspace_text(
                self.root,
                self.state_file,
                encoding="utf-8",
                errors="strict",
            )
        except UnicodeDecodeError as exc:
            raise RunStateFormatError("run state must be valid UTF-8") from exc
        except workspace_fs.WorkspacePathError as exc:
            if (
                exc.rule_family == "path_race"
                and exc.missing_path == self.state_file
            ):
                return None
            raise
        try:
            payload = json.loads(text)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise RunStateFormatError("invalid run state JSON") from exc
        return _decode_state(payload)

    def _write(self, state: RunState) -> None:
        payload = _encode_state(state)
        workspace_fs.write_workspace_text(
            self.root,
            self.state_file,
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
            errors="strict",
        )


def _apply_delta(current: RunState, delta: StateDelta) -> RunState:
    return replace(
        current,
        revision=current.revision + 1,
        status=current.status if delta.status is None else delta.status,
        step=current.step if delta.step is None else delta.step,
        observations=current.observations + delta.append_observations,
        latest_gate=(
            current.latest_gate
            if delta.latest_gate is None
            else delta.latest_gate
        ),
        pending_approval_id=(
            None
            if delta.clear_pending_approval
            else (
                current.pending_approval_id
                if delta.pending_approval_id is None
                else delta.pending_approval_id
            )
        ),
        finish_requested=(
            current.finish_requested
            if delta.finish_requested is None
            else delta.finish_requested
        ),
        metrics=add_run_metrics(current.metrics, delta.metrics),
    )


def _persistable_state(state: RunState) -> RunState:
    payload = redact(_encode_state(state))
    try:
        encoded = json.dumps(payload, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise RunStateSerializationError(
            "run state contains a non-serializable value"
        ) from exc
    try:
        decoded = json.loads(encoded)
    except json.JSONDecodeError as exc:
        raise RunStateSerializationError("run state serialization failed") from exc
    return _decode_state(decoded)


def _encode_state(state: RunState) -> dict[str, Any]:
    return {
        "schema_version": FileRunStateStore.schema_version,
        "run_id": state.run_id,
        "revision": state.revision,
        "status": state.status.value,
        "step": state.step,
        "observations": [
            {"kind": observation.kind, "payload": deepcopy(observation.payload)}
            for observation in state.observations
        ],
        "latest_gate": _encode_gate(state.latest_gate),
        "pending_approval_id": state.pending_approval_id,
        "finish_requested": state.finish_requested,
        "metrics": state.metrics.to_dict(),
    }


def _decode_state(payload: Any) -> RunState:
    required = {
        "schema_version",
        "run_id",
        "revision",
        "status",
        "step",
        "observations",
        "latest_gate",
        "pending_approval_id",
        "finish_requested",
        "metrics",
    }
    _require_exact_mapping(payload, required, "run state")
    if payload["schema_version"] != FileRunStateStore.schema_version:
        raise RunStateFormatError("unsupported run state schema version")
    run_id = _require_non_empty_string(payload["run_id"], "run_id")
    revision = _require_non_negative_int(payload["revision"], "revision")
    step = _require_non_negative_int(payload["step"], "step")
    try:
        status = RunStatus(payload["status"])
    except (TypeError, ValueError) as exc:
        raise RunStateFormatError("invalid run status") from exc
    raw_observations = payload["observations"]
    if not isinstance(raw_observations, list):
        raise RunStateFormatError("observations must be a list")
    observations = tuple(_decode_observation(item) for item in raw_observations)
    pending = payload["pending_approval_id"]
    if pending is not None and not isinstance(pending, str):
        raise RunStateFormatError("pending approval id must be a string or null")
    finish_requested = payload["finish_requested"]
    if not isinstance(finish_requested, bool):
        raise RunStateFormatError("finish_requested must be a boolean")
    return RunState(
        run_id=run_id,
        revision=revision,
        status=status,
        step=step,
        observations=observations,
        latest_gate=_decode_gate(payload["latest_gate"]),
        pending_approval_id=pending,
        finish_requested=finish_requested,
        metrics=_decode_metrics(payload["metrics"]),
    )


def _decode_observation(payload: Any) -> Observation:
    _require_exact_mapping(payload, {"kind", "payload"}, "observation")
    kind = _require_non_empty_string(payload["kind"], "observation kind")
    content = payload["payload"]
    if not isinstance(content, dict):
        raise RunStateFormatError("observation payload must be an object")
    return Observation(kind, deepcopy(content))


def _encode_gate(gate: GateResult | None) -> dict[str, Any] | None:
    if gate is None:
        return None
    return {
        "passed": gate.passed,
        "checks": [
            {"code": check.code, "passed": check.passed, "message": check.message}
            for check in gate.checks
        ],
        "issues": [
            {
                "code": issue.code,
                "severity": issue.severity,
                "message": issue.message,
                "evidence": issue.evidence,
                "repair_hint": issue.repair_hint,
            }
            for issue in gate.issues
        ],
        "summary": gate.summary,
        "artifact_sha256": gate.artifact_sha256,
        "checklist_sha256": gate.checklist_sha256,
    }


def _decode_gate(payload: Any) -> GateResult | None:
    if payload is None:
        return None
    required = {
        "passed",
        "checks",
        "issues",
        "summary",
        "artifact_sha256",
        "checklist_sha256",
    }
    _require_exact_mapping(payload, required, "gate result")
    if not isinstance(payload["passed"], bool):
        raise RunStateFormatError("gate passed must be a boolean")
    if not isinstance(payload["checks"], list):
        raise RunStateFormatError("gate checks must be a list")
    if not isinstance(payload["issues"], list):
        raise RunStateFormatError("gate issues must be a list")
    return GateResult(
        payload["passed"],
        [_decode_gate_check(item) for item in payload["checks"]],
        [_decode_gate_issue(item) for item in payload["issues"]],
        _require_string(payload["summary"], "gate summary"),
        artifact_sha256=_require_optional_string(
            payload["artifact_sha256"], "artifact sha256"
        ),
        checklist_sha256=_require_optional_string(
            payload["checklist_sha256"], "checklist sha256"
        ),
    )


def _decode_gate_check(payload: Any) -> GateCheck:
    _require_exact_mapping(payload, {"code", "passed", "message"}, "gate check")
    if not isinstance(payload["passed"], bool):
        raise RunStateFormatError("gate check passed must be a boolean")
    return GateCheck(
        _require_string(payload["code"], "gate check code"),
        payload["passed"],
        _require_string(payload["message"], "gate check message"),
    )


def _decode_gate_issue(payload: Any) -> GateIssue:
    required = {"code", "severity", "message", "evidence", "repair_hint"}
    _require_exact_mapping(payload, required, "gate issue")
    return GateIssue(
        _require_string(payload["code"], "gate issue code"),
        _require_string(payload["severity"], "gate issue severity"),
        _require_string(payload["message"], "gate issue message"),
        _require_string(payload["evidence"], "gate issue evidence"),
        _require_string(payload["repair_hint"], "gate issue repair hint"),
    )


def _decode_metrics(payload: Any) -> RunMetrics:
    metric_fields = {item.name: item for item in fields(RunMetrics)}
    _require_exact_mapping(payload, set(metric_fields), "run metrics")
    values: dict[str, int | bool] = {}
    defaults = RunMetrics()
    for name in metric_fields:
        value = payload[name]
        expected = getattr(defaults, name)
        if isinstance(expected, bool):
            if not isinstance(value, bool):
                raise RunStateFormatError(f"metric {name} must be a boolean")
        elif isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise RunStateFormatError(
                f"metric {name} must be a non-negative integer"
            )
        values[name] = value
    return RunMetrics(**values)


def _require_exact_mapping(
    payload: Any,
    keys: set[str],
    label: str,
) -> None:
    if not isinstance(payload, dict) or set(payload) != keys:
        raise RunStateFormatError(f"{label} fields are invalid")


def _require_non_negative_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise RunStateFormatError(f"{label} must be a non-negative integer")
    return value


def _require_string(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise RunStateFormatError(f"{label} must be a string")
    return value


def _require_non_empty_string(value: Any, label: str) -> str:
    text = _require_string(value, label)
    if not text:
        raise RunStateFormatError(f"{label} must not be empty")
    return text


def _require_optional_string(value: Any, label: str) -> str | None:
    if value is None:
        return None
    return _require_string(value, label)
