import json
import tempfile
import unittest
from pathlib import Path

from specgate.user_config import (
    UserConfigError,
    UserLLMConfig,
    UserShellConfig,
    load_user_llm_config,
    load_user_shell_config,
    load_user_shell_config_draft,
    resolve_user_llm_config,
    save_user_llm_config,
    save_user_shell_config,
    user_config_path,
)


class UserConfigTests(unittest.TestCase):
    def test_schema_v1_migrates_to_real_shell_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "provider": "openai-compatible",
                        "base_url": "https://api.test/v1",
                        "model": "model-v1",
                    }
                ),
                encoding="utf-8",
            )

            config = load_user_shell_config(path=path)

        self.assertIsNotNone(config)
        assert config is not None
        self.assertEqual(config.mode, "real")
        self.assertIsNone(config.workspace)
        self.assertFalse(config.verbose)
        self.assertEqual(config.llm, UserLLMConfig(
            "openai-compatible",
            "https://api.test/v1",
            "model-v1",
        ))

    def test_schema_v2_mock_round_trip_writes_no_secret(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            config = UserShellConfig(
                mode="mock",
                workspace="D:/work/site",
                verbose=True,
                llm=None,
            )

            save_user_shell_config(config, path=path)

            raw = path.read_text(encoding="utf-8")
            self.assertEqual(load_user_shell_config(path=path), config)
            self.assertNotIn("api_key", raw.lower())
            self.assertNotIn("secret", raw.lower())

    def test_saving_llm_defaults_preserves_shell_preferences(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            save_user_shell_config(
                UserShellConfig(
                    mode="mock",
                    workspace="D:/work/site",
                    verbose=True,
                    llm=None,
                ),
                path=path,
            )

            save_user_llm_config(
                UserLLMConfig(
                    "openai-compatible",
                    "https://api.test/v1",
                    "model-v2",
                ),
                path=path,
            )

            saved = load_user_shell_config(path=path)

        self.assertIsNotNone(saved)
        assert saved is not None
        self.assertEqual(saved.mode, "mock")
        self.assertEqual(saved.workspace, "D:/work/site")
        self.assertTrue(saved.verbose)
        self.assertEqual(saved.llm, UserLLMConfig(
            "openai-compatible",
            "https://api.test/v1",
            "model-v2",
        ))

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
            json.dumps(
                {
                    "schema_version": 2,
                    "provider": "openai-compatible",
                    "base_url": "https://api.test/v1",
                    "model": "m",
                    "mode": "real",
                    "workspace": None,
                    "verbose": False,
                    "api_key": "sk-secret",
                }
            ),
            json.dumps(
                {
                    "schema_version": 2,
                    "provider": "openai-compatible",
                    "base_url": None,
                    "model": None,
                    "mode": "real",
                    "workspace": None,
                    "verbose": False,
                }
            ),
        )
        for payload in invalid_payloads:
            with self.subTest(payload=payload), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "config.json"
                path.write_text(payload, encoding="utf-8")

                with self.assertRaises(UserConfigError):
                    load_user_llm_config(path=path)

    def test_draft_recovers_valid_fields_when_one_field_is_corrupt(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": 2,
                        "provider": "openai-compatible",
                        "base_url": "https://api.test/v1",
                        "model": "",
                        "mode": "real",
                        "workspace": "D:/work/site",
                        "verbose": True,
                    }
                ),
                encoding="utf-8",
            )

            draft = load_user_shell_config_draft(path=path)

        self.assertIsNotNone(draft)
        assert draft is not None
        self.assertEqual(draft.mode, "real")
        self.assertEqual(draft.workspace, "D:/work/site")
        self.assertTrue(draft.verbose)
        self.assertEqual(draft.provider, "openai-compatible")
        self.assertEqual(draft.base_url, "https://api.test/v1")
        self.assertIsNone(draft.model)

    def test_draft_rejects_payload_with_extra_sensitive_field(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": 2,
                        "provider": "openai-compatible",
                        "base_url": "https://api.test/v1",
                        "model": "model-1",
                        "mode": "real",
                        "workspace": "D:/work/site",
                        "verbose": False,
                        "api_key": "sk-must-not-be-recovered",
                    }
                ),
                encoding="utf-8",
            )

            draft = load_user_shell_config_draft(path=path)

        self.assertIsNone(draft)

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
