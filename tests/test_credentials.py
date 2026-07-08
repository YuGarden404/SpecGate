import unittest

from specgate.credentials import CredentialStatus, credential_status


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
        status = credential_status("openai")

        self.assertFalse(status.configured)
        self.assertFalse(status.safe_to_run)
        self.assertNotIn("sk-", status.message)


if __name__ == "__main__":
    unittest.main()
