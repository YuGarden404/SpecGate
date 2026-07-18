import json
import tempfile
import unittest
from pathlib import Path

from specgate.user_config import (
    UserConfigError,
    UserLLMConfig,
    load_user_llm_config,
    resolve_user_llm_config,
    save_user_llm_config,
    user_config_path,
)


class UserConfigTests(unittest.TestCase):
    def test_config_home_override_isolated_from_real_profile(self):
        path = user_config_path(
            environ={"SPECGATE_CONFIG_HOME": "D:/isolated/specgate"},
            home=Path("D:/Users/example"),
            platform="win32",
        )
        self.assertEqual(path, Path("D:/isolated/specgate/config.json"))

    def test_windows_uses_appdata(self):
        path = user_config_path(
            environ={"APPDATA": "D:/Profiles/example/AppData/Roaming"},
            home=Path("D:/Profiles/example"),
            platform="win32",
        )
        self.assertEqual(
            path,
            Path("D:/Profiles/example/AppData/Roaming/SpecGate/config.json"),
        )

    def test_linux_uses_xdg_then_home_fallback(self):
        self.assertEqual(
            user_config_path(
                environ={"XDG_CONFIG_HOME": "/tmp/xdg"},
                home=Path("/home/example"),
                platform="linux",
            ),
            Path("/tmp/xdg/specgate/config.json"),
        )
        self.assertEqual(
            user_config_path(
                environ={},
                home=Path("/home/example"),
                platform="linux",
            ),
            Path("/home/example/.config/specgate/config.json"),
        )

    def test_round_trip_writes_only_non_secret_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "nested" / "config.json"
            config = UserLLMConfig(
                provider="openai-compatible",
                base_url="https://api.example.test/v1",
                model="gpt-test",
            )

            save_user_llm_config(config, path=path)

            raw = path.read_text(encoding="utf-8")
            self.assertEqual(load_user_llm_config(path=path), config)
            self.assertNotIn("api_key", raw.lower())
            self.assertNotIn("secret", raw.lower())
            self.assertEqual(list(path.parent.glob(f".{path.name}.*.tmp")), [])

    def test_missing_config_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(
                load_user_llm_config(path=Path(tmp) / "missing.json")
            )

    def test_malformed_or_sensitive_config_fails_closed(self):
        invalid_payloads = (
            "{",
            json.dumps(
                {
                    "schema_version": 99,
                    "provider": "openai-compatible",
                    "base_url": "https://api.test/v1",
                    "model": "m",
                }
            ),
            json.dumps(
                {
                    "schema_version": 1,
                    "provider": "openai-compatible",
                    "base_url": "https://api.test/v1",
                    "model": "m",
                    "api_key": "sk-secret",
                }
            ),
            json.dumps(
                {
                    "schema_version": 1,
                    "provider": "anthropic",
                    "base_url": "https://api.test/v1",
                    "model": "m",
                }
            ),
        )
        for payload in invalid_payloads:
            with self.subTest(payload=payload), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "config.json"
                path.write_text(payload, encoding="utf-8")

                with self.assertRaises(UserConfigError):
                    load_user_llm_config(path=path)

    def test_resolution_priority_is_cli_then_environment_then_file(self):
        saved = UserLLMConfig(
            "openai-compatible",
            "https://saved.test/v1",
            "saved-model",
        )

        resolved = resolve_user_llm_config(
            provider="openai-compatible",
            model="cli-model",
            base_url=None,
            environ={
                "SPECGATE_LLM_BASE_URL": "https://env.test/v1",
                "SPECGATE_LLM_MODEL": "env-model",
            },
            saved=saved,
        )

        self.assertEqual(resolved.model, "cli-model")
        self.assertEqual(resolved.base_url, "https://env.test/v1")

    def test_resolution_reports_configure_command_when_incomplete(self):
        with self.assertRaisesRegex(UserConfigError, "specgate configure"):
            resolve_user_llm_config(
                provider="openai-compatible",
                model=None,
                base_url=None,
                environ={},
                saved=None,
            )


if __name__ == "__main__":
    unittest.main()
