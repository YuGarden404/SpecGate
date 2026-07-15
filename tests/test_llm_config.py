import json
import unittest

from specgate.llm_config import LLMConfigError, LLMRunConfig


class LLMRunConfigTests(unittest.TestCase):
    def test_mock_and_real_snapshots_round_trip_canonically(self):
        mock = LLMRunConfig.mock()
        real = LLMRunConfig.real(
            "https://api.example.test/v1",
            "test-model",
            "a" * 64,
        )

        self.assertEqual(LLMRunConfig.from_json(mock.to_json()), mock)
        self.assertEqual(LLMRunConfig.from_json(real.to_json()), real)
        self.assertEqual(json.loads(mock.to_json())["source"], "created")

    def test_mock_rejects_real_fields_and_real_requires_all_fields(self):
        with self.assertRaises(LLMConfigError):
            LLMRunConfig(mode="mock", model="test-model")
        with self.assertRaises(LLMConfigError):
            LLMRunConfig(mode="openai-compatible", base_url=None)

    def test_json_rejects_unknown_missing_bool_schema_and_bad_fingerprint(self):
        valid = LLMRunConfig.mock().to_dict()
        invalid = (
            {**valid, "unknown": 1},
            {key: value for key, value in valid.items() if key != "mode"},
            {**valid, "schema_version": True},
            {
                **LLMRunConfig.real(
                    "https://api.example.test/v1",
                    "m",
                    "a" * 64,
                ).to_dict(),
                "credential_fingerprint": "not-a-sha256",
            },
        )

        for payload in invalid:
            with self.subTest(payload=payload), self.assertRaises(LLMConfigError):
                LLMRunConfig.from_json(json.dumps(payload))

        for raw in ("[]", "null", "not-json"):
            with self.subTest(raw=raw), self.assertRaises(LLMConfigError):
                LLMRunConfig.from_json(raw)


if __name__ == "__main__":
    unittest.main()
