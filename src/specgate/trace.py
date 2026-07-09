from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from specgate.security import SECRET_PATTERNS


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
    return value


class TraceStore:
    def __init__(self, path: Path, reset: bool = False):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if reset:
            self.path.write_text("", encoding="utf-8")

    def append(self, event_type: str, payload: dict[str, Any]) -> None:
        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_type": event_type,
            "payload": redact(payload),
        }
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")
