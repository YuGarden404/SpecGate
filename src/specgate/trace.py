from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Callable

from specgate.security import SECRET_PATTERNS
from specgate.workspace_fs import append_workspace_text, write_workspace_text


def redact(value: Any) -> Any:
    if isinstance(value, str):
        text = value
        for pattern in SECRET_PATTERNS:
            text = pattern.sub("[REDACTED]", text)
        return text
    if isinstance(value, dict):
        return {key: redact(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact(item) for item in value)
    return value


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class TraceStore:
    def __init__(
        self,
        path: Path,
        reset: bool = False,
        clock: Callable[[], str] = _utc_now,
    ):
        self.path = path
        self.root = path.parent
        self.relative = path.name
        self.clock = clock
        if reset:
            write_workspace_text(self.root, self.relative, "", encoding="utf-8")

    def append(self, event_type: str, payload: dict[str, Any]) -> None:
        event = {
            "timestamp": self.clock(),
            "event_type": event_type,
            "payload": redact(payload),
        }
        append_workspace_text(
            self.root,
            self.relative,
            json.dumps(event, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
