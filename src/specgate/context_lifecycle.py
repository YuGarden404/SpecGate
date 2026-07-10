from __future__ import annotations

from dataclasses import dataclass, field
import json


@dataclass(frozen=True)
class CompressionConfig:
    max_tool_result_chars: int = 1200
    summary_budget_chars: int = 2500
    pin_latest_gate_feedback: bool = True
    pin_policy: bool = True


@dataclass(frozen=True)
class CompressionSummary:
    original_chars: int
    compressed_chars: int
    cleared_tool_results: int
    summarized_events: int
    pinned_sections: list[str] = field(default_factory=list)
    dropped_sections: list[str] = field(default_factory=list)
    rendered_events: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, int | list[str]]:
        return {
            "original_chars": self.original_chars,
            "compressed_chars": self.compressed_chars,
            "cleared_tool_results": self.cleared_tool_results,
            "summarized_events": self.summarized_events,
            "pinned_sections": self.pinned_sections,
            "dropped_sections": self.dropped_sections,
            "rendered_events": self.rendered_events,
        }


def compress_runtime_feedback(events: list[dict], config: CompressionConfig | None = None) -> CompressionSummary:
    cfg = config or CompressionConfig()
    original = json.dumps(events, ensure_ascii=False, sort_keys=True)
    rendered: list[str] = []
    cleared = 0
    summarized = 0
    for event in events:
        text = json.dumps(event, ensure_ascii=False, sort_keys=True)
        if len(text) > cfg.max_tool_result_chars and _event_type(event) == "tool_result":
            cleared += 1
            payload = _payload(event)
            action = event.get("action") or payload.get("action") or "unknown"
            result = payload.get("result", {})
            ok = event.get("ok")
            if ok is None and isinstance(result, dict):
                ok = result.get("ok")
            blocked = _first_present("blocked", event, payload)
            if blocked is None and isinstance(result, dict):
                blocked = result.get("blocked")
            status = _first_present("status", event, payload)
            if status is None and isinstance(result, dict):
                status = result.get("status")
            message = _first_present("message", event, payload)
            if message is None and isinstance(result, dict):
                message = result.get("message")
            path = _path_from_event(event, payload, result)
            text = json.dumps(
                {
                    "event_type": "tool_result",
                    "action": action,
                    "ok": ok,
                    "blocked": blocked,
                    "status": status,
                    "message": message,
                    "path": path,
                    "data": f"[cleared tool result {len(text)} chars]",
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        elif len(text) > cfg.max_tool_result_chars:
            summarized += 1
            text = text[: cfg.max_tool_result_chars] + f"...[summarized event {len(text) - cfg.max_tool_result_chars} chars]"
        rendered.append(text)

    compressed = "\n".join(rendered)
    if len(compressed) > cfg.summary_budget_chars:
        rendered = _fit_latest_events(rendered, cfg.summary_budget_chars)
        compressed = "\n".join(rendered)
    return CompressionSummary(
        original_chars=len(original),
        compressed_chars=len(compressed),
        cleared_tool_results=cleared,
        summarized_events=summarized,
        rendered_events=rendered,
    )


def pin_critical_sections(sections: list[tuple[str, str]]) -> list[tuple[str, str]]:
    pinned_names = {"Task Constraints", "Policy Boundary", "Latest Gate Feedback"}
    normal = [section for section in sections if section[0] not in pinned_names]
    pinned = [section for section in sections if section[0] in pinned_names]
    order = {"Task Constraints": 0, "Policy Boundary": 1, "Latest Gate Feedback": 2}
    return normal + sorted(pinned, key=lambda item: order[item[0]])


def _event_type(event: dict) -> str:
    return str(event.get("event_type") or event.get("type") or "")


def _payload(event: dict) -> dict:
    payload = event.get("payload", {})
    return payload if isinstance(payload, dict) else {}


def _first_present(key: str, *sources: dict):
    for source in sources:
        if key in source:
            return source[key]
    return None


def _path_from_event(event: dict, payload: dict, result: object) -> object:
    for source in (event, payload):
        path = source.get("path")
        if path is not None:
            return path
        data = source.get("data")
        if isinstance(data, dict) and data.get("path") is not None:
            return data.get("path")
    if isinstance(result, dict):
        path = result.get("path")
        if path is not None:
            return path
        data = result.get("data")
        if isinstance(data, dict):
            return data.get("path")
    return None


def _fit_latest_events(rendered: list[str], budget_chars: int) -> list[str]:
    marker = "[dropped earlier events to fit compression budget]"
    if budget_chars <= 0:
        return []
    if budget_chars <= len(marker):
        return [marker[:budget_chars]]
    selected: list[str] = []
    used = len(marker)
    for event_text in reversed(rendered):
        separator = 1 if selected else 0
        next_used = used + separator + len(event_text)
        if next_used > budget_chars:
            continue
        selected.append(event_text)
        used = next_used
    if not selected and rendered:
        remaining = max(0, budget_chars - len(marker) - 1)
        if remaining:
            selected.append(rendered[-1][-remaining:])
    selected.reverse()
    return [marker, *selected]
