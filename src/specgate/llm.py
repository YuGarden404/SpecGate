from __future__ import annotations

import json
from urllib import error, request
from typing import Protocol


class LLMClient(Protocol):
    def complete(self, context: str) -> str:
        ...


class LLMProviderError(RuntimeError):
    pass


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


class OpenAICompatibleLLM:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        max_tokens: int = 4096,
        timeout: float = 60,
        user_agent: str = "SpecGate/0.1 OpenAI-Compatible",
        opener=request.urlopen,
    ):
        if not base_url:
            raise ValueError("base_url must be non-empty")
        if not api_key:
            raise ValueError("api_key must be non-empty")
        if not model:
            raise ValueError("model must be non-empty")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.user_agent = user_agent
        self.opener = opener

    def complete(self, context: str) -> str:
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are the decision engine inside SpecGate. "
                        "Return exactly one strict JSON action object. "
                        "Do not wrap it in Markdown and do not add natural language."
                    ),
                },
                {"role": "user", "content": context},
            ],
            "temperature": 0,
            "max_tokens": self.max_tokens,
        }
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = request.Request(
            f"{self.base_url}/chat/completions",
            data=body,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "User-Agent": self.user_agent,
            },
            method="POST",
        )
        try:
            with self.opener(req, timeout=self.timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
            if len(body) > 500:
                body = body[:500] + "...[truncated]"
            detail = f": {body}" if body else ""
            raise LLMProviderError(f"HTTP {exc.code} {exc.reason}{detail}") from exc
        except error.URLError as exc:
            raise LLMProviderError(f"network error: {exc.reason}") from exc
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ValueError("OpenAI-compatible response does not contain choices[0].message.content") from exc
