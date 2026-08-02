from __future__ import annotations

from collections.abc import Mapping

from specgate.runtime_events import RunEventContext
from specgate.shell_terminal import ShellTerminal
from specgate.trace import redact


EVENT_CATEGORY = {
    "RunStarted": "Agent",
    "ContextBuilt": "Context",
    "LLMCompleted": "Agent",
    "GovernanceEvaluated": "Governance",
    "ToolCompleted": "Tool",
    "GateCompleted": "Gate",
    "ApprovalRequested": "Approval",
    "ApprovalClaimed": "Approval",
    "ApprovalApplied": "Approval",
    "ApprovalDenied": "Approval",
    "RunFinished": "Agent",
    "RunFailed": "Agent",
}

_MAX_VALUE_CHARS = 220
_MAX_FILE_CHARS = 80
_MAX_SELECTED_FILES = 4


def _bounded_text(value: object, *, limit: int = _MAX_VALUE_CHARS) -> str | None:
    if not isinstance(value, str):
        return None
    safe = str(redact(" ".join(value.split())))
    if not safe:
        return None
    if len(safe) <= limit:
        return safe
    return safe[: max(0, limit - 3)] + "..."


def _field(payload: Mapping[str, object], name: str) -> str | None:
    return _bounded_text(payload.get(name))


def _count(payload: Mapping[str, object], name: str) -> int | None:
    value = payload.get(name)
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return None


def _target(payload: Mapping[str, object]) -> str:
    action = _field(payload, "action") or "action"
    path = _field(payload, "path")
    return action if path is None else f"{action}: {path}"


def _context_line(payload: Mapping[str, object]) -> str:
    selected = payload.get("selected_files")
    if isinstance(selected, (list, tuple)):
        files = [
            item
            for item in (
                _bounded_text(value, limit=_MAX_FILE_CHARS)
                for value in selected[:_MAX_SELECTED_FILES]
            )
            if item is not None
        ]
        if files:
            suffix = ""
            if len(selected) > _MAX_SELECTED_FILES:
                suffix = f" (+{len(selected) - _MAX_SELECTED_FILES} more)"
            return f"Loaded {', '.join(files)}{suffix}"
    context_chars = _count(payload, "context_chars")
    if context_chars is not None:
        return f"Built ({context_chars} chars)"
    selected_count = _count(payload, "selected_count")
    if selected_count is not None:
        return f"Built ({selected_count} files)"
    return "Built"


def _governance_line(payload: Mapping[str, object]) -> str:
    decision = _field(payload, "decision")
    label = {
        "allow": "Allowed",
        "block": "Blocked",
        "require_approval": "Approval required",
    }.get(decision or "", "Evaluated")
    target = _target(payload)
    code = _field(payload, "code")
    suffix = f" ({code})" if code and decision != "allow" else ""
    return f"{label} {target}{suffix}"


def _tool_line(payload: Mapping[str, object]) -> str:
    if payload.get("blocked") is True:
        status = "Blocked"
    elif payload.get("ok") is False:
        status = "Failed"
    else:
        status = "Completed"
    code = _field(payload, "code")
    suffix = f" ({code})" if code and code != "ok" else ""
    return f"{_target(payload)} - {status}{suffix}"


def _gate_line(payload: Mapping[str, object]) -> str:
    label = "Passed" if payload.get("passed") is True else "Failed"
    summary = _field(payload, "summary")
    return label if summary is None else f"{label}: {summary}"


def _approval_line(event_type: str, payload: Mapping[str, object]) -> str:
    approval_id = _field(payload, "approval_id") or "approval"
    if event_type == "ApprovalRequested":
        risk = _field(payload, "risk_level")
        reason = _field(payload, "reason")
        details = _target(payload)
        if risk:
            details += f" ({risk})"
        if reason:
            details += f" - {reason}"
        return f"{approval_id} {details}"
    state = {
        "ApprovalClaimed": "claimed",
        "ApprovalApplied": "applied",
        "ApprovalDenied": "denied",
    }[event_type]
    reason = _field(payload, "reason")
    return f"{approval_id} {state}" + (f": {reason}" if reason else "")


def _run_finished_line(payload: Mapping[str, object]) -> str:
    status = _field(payload, "status") or "finished"
    label = {
        "completed": "Completed",
        "cancelled": "Cancelled",
        "timed_out": "Timed out",
        "needs_approval": "Pending approval",
        "failed": "Failed",
    }.get(status, f"Finished: {status}")
    code = _field(payload, "code")
    reason = _field(payload, "reason")
    detail = code or reason
    if detail and label not in {"Completed", "Cancelled"}:
        return f"{label}: {detail}"
    return label


def render_event_line(
    event_type: str,
    payload: Mapping[str, object],
) -> str | None:
    if event_type == "RunStarted":
        return "Started"
    if event_type == "ContextBuilt":
        return _context_line(payload)
    if event_type == "LLMCompleted":
        response_chars = _count(payload, "response_chars")
        return (
            "Model response received"
            if response_chars is None
            else f"Model response received ({response_chars} chars)"
        )
    if event_type == "GovernanceEvaluated":
        return _governance_line(payload)
    if event_type == "ToolCompleted":
        return _tool_line(payload)
    if event_type == "GateCompleted":
        return _gate_line(payload)
    if event_type in {
        "ApprovalRequested",
        "ApprovalClaimed",
        "ApprovalApplied",
        "ApprovalDenied",
    }:
        return _approval_line(event_type, payload)
    if event_type == "RunFinished":
        return _run_finished_line(payload)
    if event_type == "RunFailed":
        detail = _field(payload, "code") or _field(payload, "reason")
        return "Failed" if detail is None else f"Failed: {detail}"
    return None


class ShellEventRenderer:
    def __init__(self, terminal: ShellTerminal, *, verbose: bool):
        self._terminal = terminal
        self._verbose = verbose

    def emit(
        self,
        context: RunEventContext,
        event_type: str,
        payload: dict,
        *,
        step: int = 0,
        phase: str = "runtime",
    ) -> None:
        safe = redact(payload)
        assert isinstance(safe, dict)
        line = render_event_line(event_type, safe)
        if line is None:
            if not self._verbose:
                return
            self._terminal.write(
                f"[Event] {event_type} run={context.run_id} "
                f"step={step} phase={phase}",
                style="muted",
            )
            return

        category = EVENT_CATEGORY[event_type]
        suffix = (
            f" run={context.run_id} step={step} phase={phase}"
            if self._verbose
            else ""
        )
        self._terminal.write(
            f"[{category}] {line}{suffix}",
            style=category.lower(),
        )
