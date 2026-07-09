import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from specgate.credentials import CredentialStatus, clear_credential, credential_status, set_credential


class CredentialTests(unittest.TestCase):
    def test_mock_mode_needs_no_credentials(self):
        status = credential_status("mock")

        self.assertEqual(
            status,
            CredentialStatus(
                provider="mock",
                configured=True,
                safe_to_run=True,
                message="mock mode does not require credentials",
            ),
        )

    def test_unknown_real_provider_fails_closed(self):
        status = credential_status("localtest")

        self.assertFalse(status.configured)
        self.assertFalse(status.safe_to_run)
        self.assertNotIn("sk-", status.message)

    def test_unknown_provider_fails_closed_even_if_env_var_exists(self):
        with patch.dict("os.environ", {"SPECGATE_LOCALTEST_API_KEY": "secret"}, clear=False):
            status = credential_status("localtest")

        self.assertFalse(status.configured)
        self.assertFalse(status.safe_to_run)

    def test_env_file_credential_lifecycle(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / ".env"

            set_credential("openai", "sk-test-secret-123456", env_file)
            status = credential_status("openai", env_file)

            self.assertTrue(status.configured)
            self.assertTrue(status.safe_to_run)
            self.assertNotIn("sk-test-secret", status.message)
            self.assertIn("OPENAI_API_KEY=", env_file.read_text(encoding="utf-8"))

            clear_credential("openai", env_file)
            cleared = credential_status("openai", env_file)

            self.assertFalse(cleared.configured)
            self.assertFalse(cleared.safe_to_run)

    def test_env_file_updates_preserve_unrelated_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / ".env"
            env_file.write_text("# local settings\nOTHER=value\n\n", encoding="utf-8")

            set_credential("openai", "sk-test-secret-123456", env_file)
            clear_credential("openai", env_file)
            text = env_file.read_text(encoding="utf-8")

            self.assertIn("# local settings", text)
            self.assertIn("OTHER=value", text)
            self.assertNotIn("OPENAI_API_KEY", text)


if __name__ == "__main__":
    unittest.main()
