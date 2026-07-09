import json
from io import BytesIO
import unittest
from urllib.error import HTTPError

from specgate.llm import LLMProviderError, OpenAICompatibleLLM


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


class OpenAICompatibleLLMTests(unittest.TestCase):
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
        def forbidden(request, timeout):
            raise HTTPError(
                request.full_url,
                403,
                "Forbidden",
                hdrs={},
                fp=BytesIO(b'{"error":"model not allowed"}'),
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
        self.assertIn("HTTP 403", message)
        self.assertIn("model not allowed", message)
        self.assertNotIn("sk-test-secret", message)

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


if __name__ == "__main__":
    unittest.main()
