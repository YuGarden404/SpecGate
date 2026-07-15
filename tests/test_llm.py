import json
from io import BytesIO
import unittest
from urllib.error import HTTPError, URLError

from specgate.llm import LLMProviderError, OpenAICompatibleLLM
from specgate.llm_transport import LLMEndpointPolicy, LLMTransportError


class FakeResponse:
    def __init__(self, payload: dict):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


class CapturingOpener:
    def __init__(self):
        self.request = None

    def __call__(self, request, timeout):
        self.request = request
        self.timeout = timeout
        return FakeResponse({"choices": [{"message": {"content": '{"action":"finish"}'}}]})


class FakeChatTransport:
    def __init__(self, payload: bytes):
        self.payload = payload
        self.calls = []

    def post_json(
        self,
        endpoint,
        headers,
        body,
        *,
        stop_check,
        remaining_seconds,
    ):
        stop_check()
        self.calls.append(
            (endpoint, headers, json.loads(body.decode("utf-8")), remaining_seconds())
        )
        return self.payload


class OpenAICompatibleLLMTests(unittest.TestCase):
    def test_safe_transport_receives_strict_chat_completions_request(self):
        endpoint = LLMEndpointPolicy.from_csv("api.example.test").normalize(
            "https://api.example.test/v1"
        )
        transport = FakeChatTransport(
            b'{"choices":[{"message":{"content":"{\\"action\\":\\"finish\\"}"}}]}'
        )
        llm = OpenAICompatibleLLM(
            endpoint.base_url,
            "SENTINEL-api-key",
            "test-model",
            endpoint=endpoint,
            transport=transport,
            stop_check=lambda: None,
            remaining_seconds=lambda: 12.0,
        )

        text = llm.complete("context pack")

        self.assertEqual(text, '{"action":"finish"}')
        called_endpoint, headers, body, remaining = transport.calls[0]
        self.assertEqual(called_endpoint, endpoint)
        self.assertEqual(headers["Authorization"], "Bearer SENTINEL-api-key")
        self.assertEqual(body["model"], "test-model")
        self.assertEqual(body["temperature"], 0)
        self.assertEqual(body["max_tokens"], 4096)
        self.assertEqual(body["messages"][1], {"role": "user", "content": "context pack"})
        self.assertEqual(remaining, 12.0)
        self.assertNotIn("SENTINEL-api-key", repr(llm))

    def test_safe_transport_and_invalid_envelopes_use_stable_errors(self):
        endpoint = LLMEndpointPolicy.from_csv("api.example.test").normalize(
            "https://api.example.test/v1"
        )
        invalid_payloads = (
            b"\xff",
            b"not-json",
            b"{}",
            b'{"choices":[]}',
            b'{"choices":[{"message":{"content":7}}]}',
        )
        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                llm = OpenAICompatibleLLM(
                    endpoint.base_url,
                    "SENTINEL-api-key",
                    "test-model",
                    endpoint=endpoint,
                    transport=FakeChatTransport(payload),
                )
                with self.assertRaises(LLMProviderError) as raised:
                    llm.complete("context")
                self.assertEqual(raised.exception.code, "llm_response_invalid")
                self.assertNotIn("SENTINEL-api-key", str(raised.exception))

        class FailingTransport:
            def post_json(self, *args, **kwargs):
                raise LLMTransportError("llm_rate_limited", retryable=True)

        llm = OpenAICompatibleLLM(
            endpoint.base_url,
            "SENTINEL-api-key",
            "test-model",
            endpoint=endpoint,
            transport=FailingTransport(),
        )
        with self.assertRaises(LLMProviderError) as raised:
            llm.complete("context")
        self.assertEqual(raised.exception.code, "llm_rate_limited")
    def test_sends_context_to_chat_completions_and_returns_message_content(self):
        opener = CapturingOpener()
        llm = OpenAICompatibleLLM(
            base_url="https://api.example.test/v1",
            api_key="sk-test-secret",
            model="test-model",
            opener=opener,
        )

        text = llm.complete("context pack")

        self.assertEqual(text, '{"action":"finish"}')
        self.assertEqual(opener.request.full_url, "https://api.example.test/v1/chat/completions")
        self.assertEqual(opener.request.headers["Authorization"], "Bearer sk-test-secret")
        self.assertEqual(opener.request.headers["Accept"], "application/json")
        self.assertIn("SpecGate", opener.request.headers["User-agent"])
        body = json.loads(opener.request.data.decode("utf-8"))
        self.assertEqual(body["model"], "test-model")
        self.assertEqual(body["temperature"], 0)
        self.assertEqual(body["messages"][0]["role"], "system")
        self.assertIn("strict JSON", body["messages"][0]["content"])
        self.assertEqual(body["messages"][1], {"role": "user", "content": "context pack"})

    def test_rejects_empty_api_key(self):
        with self.assertRaises(ValueError):
            OpenAICompatibleLLM(base_url="https://api.example.test/v1", api_key="", model="test-model")

    def test_http_error_is_wrapped_without_leaking_api_key(self):
        error_body = BytesIO(b'{"error":"REFLECTED_BODY_SECRET_7b21"}')

        def forbidden(request, timeout):
            raise HTTPError(
                request.full_url,
                403,
                "Forbidden",
                hdrs={},
                fp=error_body,
            )

        llm = OpenAICompatibleLLM(
            base_url="https://api.example.test/v1",
            api_key="sk-test-secret",
            model="test-model",
            opener=forbidden,
        )

        with self.assertRaises(LLMProviderError) as caught:
            llm.complete("context pack")

        message = str(caught.exception)
        self.assertEqual(message, "HTTP 403 Forbidden")
        self.assertNotIn("REFLECTED_BODY_SECRET_7b21", message)
        self.assertNotIn("sk-test-secret", message)
        self.assertTrue(error_body.closed)

    def test_http_error_uses_standard_reason_and_handles_missing_body_stream(self):
        def forbidden(request, timeout):
            raise HTTPError(
                request.full_url,
                403,
                "REFLECTED_REASON_SECRET_4c12",
                hdrs={},
                fp=None,
            )

        llm = OpenAICompatibleLLM(
            base_url="https://api.example.test/v1",
            api_key="sk-test-secret",
            model="test-model",
            opener=forbidden,
        )

        with self.assertRaises(LLMProviderError) as caught:
            llm.complete("context pack")

        self.assertEqual(str(caught.exception), "HTTP 403 Forbidden")
        self.assertNotIn("REFLECTED_REASON_SECRET_4c12", str(caught.exception))

    def test_timeout_is_wrapped_as_provider_error(self):
        def timeout(request, timeout):
            raise TimeoutError("The read operation timed out")

        llm = OpenAICompatibleLLM(
            base_url="https://api.example.test/v1",
            api_key="sk-test-secret",
            model="test-model",
            opener=timeout,
        )

        with self.assertRaises(LLMProviderError) as caught:
            llm.complete("context pack")

        message = str(caught.exception)
        self.assertIn("timed out", message)
        self.assertNotIn("sk-test-secret", message)

    def test_legacy_network_reason_is_not_reflected(self):
        def unavailable(request, timeout):
            raise URLError("REFLECTED_NETWORK_SECRET_5d31")

        llm = OpenAICompatibleLLM(
            base_url="https://api.example.test/v1",
            api_key="sk-test-secret",
            model="test-model",
            opener=unavailable,
        )

        with self.assertRaises(LLMProviderError) as raised:
            llm.complete("context pack")

        self.assertEqual(raised.exception.code, "llm_provider_unavailable")
        self.assertNotIn("REFLECTED_NETWORK_SECRET_5d31", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
