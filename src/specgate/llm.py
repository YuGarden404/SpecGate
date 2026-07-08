from __future__ import annotations

import json
from typing import Protocol


class LLMClient(Protocol):
    def complete(self, context: str) -> str:
        ...


class MockLLM:
    def __init__(self, responses: list[dict]):
        self.responses = responses
        self.calls = 0

    def complete(self, context: str) -> str:
        if self.calls >= len(self.responses):
            return json.dumps({"schema_version": "1", "action": "finish", "args": {"summary": "no more responses"}})
        response = self.responses[self.calls]
        self.calls += 1
        return json.dumps(response, ensure_ascii=False)
