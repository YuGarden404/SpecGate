import tempfile
import unittest
from pathlib import Path

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

    def test_env_file_credential_lifecycle(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / ".env"

            set_credential("localtest", "sk-test-secret-123456", env_file)
            status = credential_status("localtest", env_file)

            self.assertTrue(status.configured)
            self.assertTrue(status.safe_to_run)
            self.assertNotIn("sk-test-secret", status.message)
            self.assertIn("SPECGATE_LOCALTEST_API_KEY=", env_file.read_text(encoding="utf-8"))

            clear_credential("localtest", env_file)
            cleared = credential_status("localtest", env_file)

            self.assertFalse(cleared.configured)
            self.assertFalse(cleared.safe_to_run)


if __name__ == "__main__":
    unittest.main()
