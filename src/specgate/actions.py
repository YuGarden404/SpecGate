from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any


class ActionParseError(ValueError):
    pass


@dataclass(frozen=True)
class Action:
    schema_version: str
    action: str
    args: dict[str, Any]
    reason: str = ""


def _validate_action_args(action: str, args: dict[str, Any]) -> None:
    if action in {"write_file", "replace_file"}:
        if not isinstance(args.get("path"), str) or not isinstance(args.get("content"), str):
            raise ActionParseError(
                "invalid_action_payload: write action requires string path and content"
            )


def parse_action(raw: str) -> Action:
    text = raw.strip()
    if not text.startswith("{") or not text.endswith("}"):
        raise ActionParseError("model output must be one strict JSON object")

    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ActionParseError(f"invalid JSON: {exc.msg}") from exc

    if not isinstance(payload, dict):
        raise ActionParseError("action payload must be an object")

    for field in ("schema_version", "action", "args"):
        if field not in payload:
            raise ActionParseError(f"missing field: {field}")

    if not isinstance(payload["schema_version"], str):
        raise ActionParseError("schema_version must be a string")
    if payload["schema_version"] != "1":
        raise ActionParseError(f"unsupported schema_version: {payload['schema_version']}")
    if not isinstance(payload["action"], str):
        raise ActionParseError("action must be a string")
    if not isinstance(payload["args"], dict):
        raise ActionParseError("args must be an object")

    _validate_action_args(payload["action"], payload["args"])

    reason = payload.get("reason", "")
    if not isinstance(reason, str):
        raise ActionParseError("reason must be a string")

    return Action(
        schema_version=payload["schema_version"],
        action=payload["action"],
        args=payload["args"],
        reason=reason,
    )
