from __future__ import annotations

import json
from http.client import responses as HTTP_STATUS_REASONS
from urllib import error, request
from typing import Callable, Protocol

from specgate.llm_transport import (
    LLMTransportError,
    NormalizedEndpoint,
    SafeHTTPSChatTransport,
)


class LLMClient(Protocol):
    def complete(self, context: str) -> str:
        ...


class LLMProviderError(RuntimeError):
    def __init__(self, code: str, message: str | None = None) -> None:
        self.code = code
        super().__init__(message or code)


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
        *,
        endpoint: NormalizedEndpoint | None = None,
        transport: SafeHTTPSChatTransport | None = None,
        stop_check: Callable[[], None] = lambda: None,
        remaining_seconds: Callable[[], float] = lambda: 60.0,
    ):
        if not base_url:
            raise ValueError("base_url must be non-empty")
        if not api_key:
            raise ValueError("api_key must be non-empty")
        if not model:
            raise ValueError("model must be non-empty")
        if transport is not None and endpoint is None:
            raise ValueError("endpoint is required with safe transport")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.user_agent = user_agent
        self.opener = opener
        self.endpoint = endpoint
        self.transport = transport
        self.stop_check = stop_check
        self.remaining_seconds = remaining_seconds

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
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "User-Agent": self.user_agent,
        }
        raw = self._request(body, headers)
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise LLMProviderError("llm_response_invalid") from exc
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMProviderError("llm_response_invalid") from exc
        if not isinstance(content, str):
            raise LLMProviderError("llm_response_invalid")
        return content

    def _request(self, body: bytes, headers: dict[str, str]) -> bytes:
        if self.transport is not None:
            try:
                return self.transport.post_json(
                    self.endpoint,
                    headers,
                    body,
                    stop_check=self.stop_check,
                    remaining_seconds=self.remaining_seconds,
                )
            except LLMTransportError as exc:
                raise LLMProviderError(exc.code) from exc

        req = request.Request(
            f"{self.base_url}/chat/completions",
            data=body,
            headers=headers,
            method="POST",
        )
        try:
            with self.opener(req, timeout=self.timeout) as response:
                return response.read()
        except error.HTTPError as exc:
            try:
                standard_reason = HTTP_STATUS_REASONS.get(exc.code)
                reason = f" {standard_reason}" if standard_reason else ""
                raise LLMProviderError(
                    _code_for_http_status(exc.code),
                    f"HTTP {exc.code}{reason}",
                ) from exc
            finally:
                if exc.fp is not None:
                    exc.close()
        except error.URLError as exc:
            raise LLMProviderError(
                "llm_provider_unavailable",
                "network error",
            ) from exc
        except TimeoutError as exc:
            raise LLMProviderError(
                "llm_request_timeout",
                f"request timed out after {self.timeout} seconds",
            ) from exc


def _code_for_http_status(status: int) -> str:
    if status in {401, 403}:
        return "llm_authentication_failed"
    if status == 408:
        return "llm_request_timeout"
    if status == 429:
        return "llm_rate_limited"
    if 500 <= status <= 599:
        return "llm_provider_unavailable"
    return "llm_request_rejected"
