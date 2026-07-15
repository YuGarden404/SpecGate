import json
import unittest

from specgate.runtime_config import RunRuntimeConfig, RuntimeConfigError


class RunRuntimeConfigTests(unittest.TestCase):
    def test_defaults_and_canonical_json_are_stable(self):
        config = RunRuntimeConfig()

        self.assertEqual(
            config.to_dict(),
            {
                "schema_version": 1,
                "source": "created",
                "governance_profile": "review",
                "context_strategy": "injection-safe",
                "max_steps": 5,
                "context_budget_chars": 12000,
                "retrieval_top_k": 6,
                "retrieval_budget_chars": 9000,
                "compression_max_tool_result_chars": 1200,
            },
        )
        self.assertEqual(
            config.to_json(),
            json.dumps(
                config.to_dict(),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
        )
        self.assertEqual(RunRuntimeConfig.from_json(config.to_json()), config)

    def test_settings_and_migration_constructors_set_source(self):
        values = {
            "governance_profile": "strict",
            "context_strategy": "rag-select",
            "max_steps": 7,
            "context_budget_chars": 16000,
            "retrieval_top_k": 4,
            "retrieval_budget_chars": 7000,
            "compression_max_tool_result_chars": 900,
        }

        self.assertEqual(RunRuntimeConfig.from_settings(values).source, "created")
        self.assertEqual(RunRuntimeConfig.for_migration(values).source, "migration")

    def test_numeric_boundaries_are_inclusive(self):
        minimum = RunRuntimeConfig(
            max_steps=1,
            context_budget_chars=1000,
            retrieval_top_k=1,
            retrieval_budget_chars=500,
            compression_max_tool_result_chars=100,
        )
        maximum = RunRuntimeConfig(
            max_steps=20,
            context_budget_chars=100000,
            retrieval_top_k=20,
            retrieval_budget_chars=50000,
            compression_max_tool_result_chars=10000,
        )

        self.assertEqual(minimum.max_steps, 1)
        self.assertEqual(maximum.max_steps, 20)

    def test_invalid_numeric_values_report_the_field(self):
        cases = (
            ("max_steps", 0),
            ("max_steps", 21),
            ("context_budget_chars", 999),
            ("context_budget_chars", 100001),
            ("retrieval_top_k", 0),
            ("retrieval_top_k", 21),
            ("retrieval_budget_chars", 499),
            ("retrieval_budget_chars", 50001),
            ("compression_max_tool_result_chars", 99),
            ("compression_max_tool_result_chars", 10001),
        )
        for field, value in cases:
            with self.subTest(field=field, value=value), self.assertRaises(
                RuntimeConfigError
            ) as raised:
                RunRuntimeConfig(**{field: value})
            self.assertEqual(raised.exception.field, field)
            self.assertEqual(raised.exception.code, "invalid_runtime_config")

    def test_bool_float_string_and_none_are_not_integers(self):
        for value in (True, 5.0, "5", None):
            with self.subTest(value=value), self.assertRaises(RuntimeConfigError):
                RunRuntimeConfig(max_steps=value)

    def test_json_rejects_missing_unknown_and_invalid_schema_fields(self):
        valid = RunRuntimeConfig().to_dict()
        missing = dict(valid)
        missing.pop("max_steps")
        invalid_payloads = (
            missing,
            {**valid, "unknown": 1},
            {**valid, "schema_version": 2},
            {**valid, "schema_version": True},
        )

        for payload in invalid_payloads:
            with self.subTest(payload=payload), self.assertRaises(
                RuntimeConfigError
            ):
                RunRuntimeConfig.from_json(json.dumps(payload))

        for raw in ("[]", "null", "not-json"):
            with self.subTest(raw=raw), self.assertRaises(RuntimeConfigError):
                RunRuntimeConfig.from_json(raw)


if __name__ == "__main__":
    unittest.main()
