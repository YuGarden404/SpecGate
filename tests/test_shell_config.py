import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from shell_support import ScriptedTerminal
from specgate.credential_store import CredentialStoreUnavailable
from specgate.shell_config import ShellConfigController
from specgate.user_config import (
    UserConfigError,
    UserLLMConfig,
    UserShellConfig,
    load_user_shell_config,
    save_user_shell_config,
)


class MemoryCredentialStore:
    def __init__(self, existing=None):
        self.existing = existing

    def get(self, provider):
        del provider
        return self.existing

    def set(self, provider, secret):
        del provider
        self.existing = secret

    def clear(self, provider):
        del provider
        self.existing = None


class FailingCredentialStore(MemoryCredentialStore):
    def set(self, provider, secret):
        del provider, secret
        raise CredentialStoreUnavailable("credential store unavailable")


def complete_real_config(root: Path) -> UserShellConfig:
    return UserShellConfig(
        "real",
        str(root.resolve()),
        False,
        UserLLMConfig(
            "openai-compatible",
            "https://api.example.com/v1",
            "model-1",
        ),
    )


def make_controller(
    root: Path,
    terminal: ScriptedTerminal,
    config: UserShellConfig | None,
    *,
    store=None,
    environ=None,
):
    path = root / "user-config.json"
    if config is not None:
        save_user_shell_config(config, path=path)
    return ShellConfigController(
        terminal,
        path=path,
        credential_store=store,
        environ={} if environ is None else environ,
    )


class ShellConfigControllerTests(unittest.TestCase):
    def test_complete_config_skips_setup_and_prints_redacted_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            terminal = ScriptedTerminal([])
            controller = make_controller(
                root,
                terminal,
                complete_real_config(root),
                store=MemoryCredentialStore("sk-test-secret-1234567890"),
            )

            config = controller.ensure_ready()

            self.assertEqual(config.mode, "real")
            self.assertEqual(terminal.read_calls, [])
            self.assertIn("API key: securely configured", terminal.output)
            self.assertIn("Credential source: keyring", terminal.output)
            self.assertNotIn("sk-test-secret", terminal.output)

    def test_api_key_command_uses_secret_input_and_preserves_old_key_on_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            terminal = ScriptedTerminal(["new-secret"])
            store = FailingCredentialStore(existing="old-secret")
            controller = make_controller(
                root,
                terminal,
                complete_real_config(root),
                store=store,
            )

            result = controller.execute("api-key", None)

            self.assertFalse(result.ok)
            self.assertEqual(store.existing, "old-secret")
            self.assertTrue(terminal.read_calls[0].secret)
            self.assertNotIn("new-secret", terminal.output)
            self.assertNotIn("old-secret", terminal.output)

    def test_api_key_success_is_persisted_only_in_credential_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            terminal = ScriptedTerminal(["new-secret"])
            store = MemoryCredentialStore()
            controller = make_controller(
                root,
                terminal,
                complete_real_config(root),
                store=store,
            )

            result = controller.execute("api-key", None)

            self.assertTrue(result.ok)
            self.assertEqual(store.existing, "new-secret")
            self.assertTrue(terminal.read_calls[0].secret)
            self.assertNotIn("new-secret", terminal.output)
            self.assertNotIn("new-secret", (root / "user-config.json").read_text())

    def test_invalid_workspace_does_not_replace_saved_workspace(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            controller = make_controller(
                root,
                ScriptedTerminal([]),
                complete_real_config(root),
                store=MemoryCredentialStore("secret"),
            )
            previous = controller.config.workspace

            result = controller.execute("workspace", str(root / "missing"))

            self.assertFalse(result.ok)
            self.assertEqual(controller.config.workspace, previous)
            self.assertEqual(
                load_user_shell_config(path=root / "user-config.json").workspace,
                previous,
            )

    def test_workspace_command_resolves_and_persists_absolute_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            workspace.mkdir()
            controller = make_controller(
                root,
                ScriptedTerminal([]),
                complete_real_config(root),
                store=MemoryCredentialStore("secret"),
            )

            result = controller.execute("workspace", str(workspace))

            self.assertTrue(result.ok)
            self.assertEqual(result.config.workspace, str(workspace.resolve()))
            self.assertEqual(
                load_user_shell_config(path=root / "user-config.json").workspace,
                str(workspace.resolve()),
            )

    def test_mode_mock_preserves_saved_real_llm_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            original = complete_real_config(root)
            controller = make_controller(
                root,
                ScriptedTerminal([]),
                original,
                store=MemoryCredentialStore("secret"),
            )

            result = controller.execute("mode", "mock")

            self.assertTrue(result.ok)
            self.assertEqual(result.config.mode, "mock")
            self.assertEqual(result.config.llm, original.llm)

    def test_mode_real_collects_missing_llm_fields_and_requests_connection_test(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            terminal = ScriptedTerminal(
                ["https://API.Example.com/v1/", "DeepSeek-V4-Pro", "new-secret"]
            )
            store = MemoryCredentialStore()
            controller = make_controller(
                root,
                terminal,
                UserShellConfig("mock", str(root.resolve()), False, None),
                store=store,
            )

            result = controller.execute("mode", "real")

            self.assertTrue(result.ok)
            self.assertTrue(result.request_connection_test)
            self.assertEqual(result.config.mode, "real")
            self.assertEqual(
                result.config.llm,
                UserLLMConfig(
                    "openai-compatible",
                    "https://api.example.com/v1",
                    "DeepSeek-V4-Pro",
                ),
            )
            self.assertEqual(store.existing, "new-secret")
            self.assertTrue(terminal.read_calls[-1].secret)

    def test_mode_real_rolls_back_new_key_when_config_save_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            terminal = ScriptedTerminal(
                ["https://api.example.com/v1", "model-1", "new-secret"]
            )
            store = MemoryCredentialStore()
            original = UserShellConfig(
                "mock",
                str(root.resolve()),
                False,
                None,
            )
            controller = make_controller(
                root,
                terminal,
                original,
                store=store,
            )

            with patch(
                "specgate.shell_config.save_user_shell_config",
                side_effect=UserConfigError("save failed"),
            ):
                result = controller.execute("mode", "real")

            self.assertFalse(result.ok)
            self.assertEqual(controller.config, original)
            self.assertIsNone(store.existing)

    def test_model_url_and_verbose_commands_validate_then_persist(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            controller = make_controller(
                root,
                ScriptedTerminal([]),
                complete_real_config(root),
                store=MemoryCredentialStore("secret"),
            )

            model = controller.execute("model", "DeepSeek-V4-Pro")
            url = controller.execute("url", "https://API.Example.com:8443/v1/")
            verbose_on = controller.execute("verbose", "on")
            verbose_off = controller.execute("verbose", "off")

            self.assertTrue(all(item.ok for item in (model, url, verbose_on, verbose_off)))
            self.assertEqual(controller.config.llm.model, "DeepSeek-V4-Pro")
            self.assertEqual(
                controller.config.llm.base_url,
                "https://api.example.com:8443/v1",
            )
            self.assertFalse(controller.config.verbose)
            self.assertEqual(
                load_user_shell_config(path=root / "user-config.json"),
                controller.config,
            )

    def test_invalid_url_and_verbose_value_preserve_existing_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            original = complete_real_config(root)
            controller = make_controller(
                root,
                ScriptedTerminal([]),
                original,
                store=MemoryCredentialStore("secret"),
            )

            for value in (
                "http://api.example.com/v1",
                "https://user@api.example.com/v1",
                "https://api.example.com/v1?secret=x",
            ):
                with self.subTest(value=value):
                    self.assertFalse(controller.execute("url", value).ok)
            self.assertFalse(controller.execute("verbose", "maybe").ok)

            self.assertEqual(controller.config, original)

    def test_first_setup_collects_mock_mode_and_workspace_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = root / "workspace"
            workspace.mkdir()
            terminal = ScriptedTerminal(["mock", str(workspace)])
            controller = make_controller(root, terminal, None)

            config = controller.ensure_ready()

            self.assertEqual(
                config,
                UserShellConfig("mock", str(workspace.resolve()), False, None),
            )
            self.assertEqual(load_user_shell_config(path=root / "user-config.json"), config)
            self.assertFalse(any(call.secret for call in terminal.read_calls))

    def test_corrupt_model_recovers_other_fields_and_prompts_only_for_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "user-config.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": 2,
                        "provider": "openai-compatible",
                        "base_url": "https://api.example.com/v1",
                        "model": "",
                        "mode": "real",
                        "workspace": str(root.resolve()),
                        "verbose": True,
                    }
                ),
                encoding="utf-8",
            )
            terminal = ScriptedTerminal(["Recovered-Model"])
            controller = ShellConfigController(
                terminal,
                path=path,
                credential_store=MemoryCredentialStore("secret"),
                environ={},
            )

            config = controller.ensure_ready()

            self.assertEqual(config.mode, "real")
            self.assertEqual(config.workspace, str(root.resolve()))
            self.assertTrue(config.verbose)
            self.assertEqual(config.llm.base_url, "https://api.example.com/v1")
            self.assertEqual(config.llm.model, "Recovered-Model")
            self.assertEqual(len(terminal.read_calls), 1)
            self.assertIn("Model", terminal.read_calls[0].prompt)

    def test_invalid_saved_url_prompts_only_for_url(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "user-config.json"
            save_user_shell_config(
                UserShellConfig(
                    "real",
                    str(root.resolve()),
                    False,
                    UserLLMConfig(
                        "openai-compatible",
                        "http://api.example.com/v1",
                        "Saved-Model",
                    ),
                ),
                path=path,
            )
            terminal = ScriptedTerminal(["https://api.example.com/v1/"])
            controller = ShellConfigController(
                terminal,
                path=path,
                credential_store=MemoryCredentialStore("secret"),
                environ={},
            )

            config = controller.ensure_ready()

            self.assertEqual(config.llm.base_url, "https://api.example.com/v1")
            self.assertEqual(config.llm.model, "Saved-Model")
            self.assertEqual(len(terminal.read_calls), 1)
            self.assertIn("Base URL", terminal.read_calls[0].prompt)

    def test_setup_command_keeps_existing_values_on_empty_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            original = complete_real_config(root)
            terminal = ScriptedTerminal(["", "", "", ""])
            controller = make_controller(
                root,
                terminal,
                original,
                store=MemoryCredentialStore("secret"),
            )

            result = controller.execute("setup", None)

            self.assertTrue(result.ok)
            self.assertTrue(result.request_connection_test)
            self.assertEqual(result.config, original)
            self.assertFalse(any(call.secret for call in terminal.read_calls))

    def test_environment_credential_source_takes_precedence_in_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            terminal = ScriptedTerminal([])
            controller = make_controller(
                root,
                terminal,
                complete_real_config(root),
                store=MemoryCredentialStore("keyring-secret"),
                environ={"OPENAI_COMPATIBLE_API_KEY": "environment-secret"},
            )

            result = controller.execute("status", None)

            self.assertTrue(result.ok)
            self.assertIn("Credential source: environment", terminal.output)
            self.assertNotIn("environment-secret", terminal.output)
            self.assertNotIn("keyring-secret", terminal.output)

    def test_help_and_clear_are_local_and_unknown_command_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            terminal = ScriptedTerminal([])
            controller = make_controller(
                root,
                terminal,
                complete_real_config(root),
                store=MemoryCredentialStore("secret"),
            )

            self.assertTrue(controller.execute("help", None).ok)
            self.assertIn("/workspace", terminal.output)
            self.assertTrue(controller.execute("clear", None).ok)
            self.assertEqual(terminal.clear_calls, 1)
            self.assertFalse(controller.execute("unknown", None).ok)


if __name__ == "__main__":
    unittest.main()
