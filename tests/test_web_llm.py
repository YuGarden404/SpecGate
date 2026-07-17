import base64
from contextlib import closing
import json
from pathlib import Path
import tempfile
import unittest

from specgate.llm_config import LLMRunConfig
from specgate.llm_transport import load_llm_network_config
from specgate.web_auth import create_user
from specgate.web_credentials import WebCredentialService
from specgate.web_db import connect_db, init_db
from specgate.web_llm import (
    LLMConnectionTestLimiter,
    LLMConnectionTestService,
    WebLLMError,
    WebLLMFactory,
    describe_llm_settings,
)


TEST_KEY = base64.urlsafe_b64encode(bytes(range(32))).decode("ascii")


class RecordingTransport:
    def __init__(self):
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
        self.calls.append((endpoint, headers, json.loads(body), remaining_seconds()))
        return b'{"choices":[{"message":{"content":"{\\"schema_version\\":\\"1\\",\\"action\\":\\"finish\\",\\"args\\":{\\"summary\\":\\"ok\\"}}"}}]}'


class WebLLMFactoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = Path(self.tmp.name) / "web.sqlite3"
        init_db(self.db_path)
        user = create_user(self.db_path, "alice", "correct-password")
        self.user_id = int(user["id"])
        self.credentials = WebCredentialService.from_key_value(
            self.db_path,
            TEST_KEY,
        )
        self.transport = RecordingTransport()
        self.network = load_llm_network_config(
            {"SPECGATE_LLM_ALLOWED_HOSTS": "api.example.test"}
        )
        self.factory = WebLLMFactory(
            self.db_path,
            self.credentials,
            self.network,
            transport_factory=lambda max_attempts: self.transport,
        )

    def save_llm_settings(self, base_url=None, model=None):
        with closing(connect_db(self.db_path)) as conn:
            conn.execute(
                """
                update user_settings
                set llm_base_url = ?, llm_model = ?
                where user_id = ?
                """,
                (base_url, model, self.user_id),
            )
            conn.commit()

    def freeze(self):
        with closing(connect_db(self.db_path)) as conn:
            return self.factory.freeze_config(conn, self.user_id)

    def test_freeze_defaults_to_mock_without_credential(self):
        self.assertEqual(self.freeze(), LLMRunConfig.mock())

        self.save_llm_settings("https://api.example.test/v1", "test-model")
        self.assertEqual(self.freeze(), LLMRunConfig.mock())

    def test_freeze_uses_real_mode_when_all_fields_exist(self):
        self.save_llm_settings("https://API.EXAMPLE.TEST/v1/", " test-model ")
        self.credentials.put(self.user_id, "SENTINEL-secret")

        config = self.freeze()

        self.assertEqual(config.mode, "openai-compatible")
        self.assertEqual(config.base_url, "https://api.example.test/v1")
        self.assertEqual(config.model, "test-model")
        self.assertEqual(len(config.credential_fingerprint), 64)
        self.assertNotIn("SENTINEL-secret", config.to_json())

    def test_present_key_with_incomplete_or_disallowed_settings_fails_closed(self):
        self.credentials.put(self.user_id, "SENTINEL-secret")

        with self.assertRaises(WebLLMError) as missing:
            self.freeze()
        self.assertEqual(missing.exception.code, "llm_configuration_required")

        self.save_llm_settings("https://not-allowed.example/v1", "test-model")
        with self.assertRaises(WebLLMError) as disallowed:
            self.freeze()
        self.assertEqual(disallowed.exception.code, "llm_host_not_allowed")

    def test_real_client_rechecks_fingerprint_before_each_call(self):
        self.save_llm_settings("https://api.example.test/v1", "test-model")
        self.credentials.put(self.user_id, "SENTINEL-secret")
        config = self.freeze()
        llm = self.factory.build(
            config,
            self.user_id,
            mock_responses=[],
            stop_check=lambda: None,
            remaining_seconds=lambda: 20.0,
        )

        first = llm.complete("context")
        self.assertIn('"action":"finish"', first)
        self.assertEqual(len(self.transport.calls), 1)

        self.credentials.put(self.user_id, "SENTINEL-secret")
        with self.assertRaises(WebLLMError) as changed:
            llm.complete("context")
        self.assertEqual(changed.exception.code, "credential_changed")
        self.assertEqual(len(self.transport.calls), 1)
        self.assertNotIn("SENTINEL-secret", str(changed.exception))

    def test_real_client_fails_when_credential_is_cleared(self):
        self.save_llm_settings("https://api.example.test/v1", "test-model")
        self.credentials.put(self.user_id, "SENTINEL-secret")
        config = self.freeze()
        llm = self.factory.build(
            config,
            self.user_id,
            mock_responses=[],
            stop_check=lambda: None,
            remaining_seconds=lambda: 20.0,
        )
        self.credentials.clear(self.user_id)

        with self.assertRaises(WebLLMError) as missing:
            llm.complete("context")

        self.assertEqual(missing.exception.code, "credential_missing")
        self.assertEqual(self.transport.calls, [])

    def test_resume_preflight_accepts_matching_credential_without_transport(self):
        self.save_llm_settings("https://api.example.test/v1", "test-model")
        self.credentials.put(self.user_id, "SENTINEL-secret")
        config = self.freeze()

        self.factory.preflight_resume(config, self.user_id)

        self.assertEqual(self.transport.calls, [])

    def test_resume_preflight_rejects_cleared_credential_without_transport(self):
        self.save_llm_settings("https://api.example.test/v1", "test-model")
        self.credentials.put(self.user_id, "SENTINEL-secret")
        config = self.freeze()
        self.credentials.clear(self.user_id)

        with self.assertRaises(WebLLMError) as missing:
            self.factory.preflight_resume(config, self.user_id)

        self.assertEqual(missing.exception.code, "credential_missing")
        self.assertEqual(self.transport.calls, [])
        self.assertNotIn("SENTINEL-secret", str(missing.exception))

    def test_mock_factory_never_accepts_a_real_snapshot(self):
        real = LLMRunConfig.real(
            "https://api.example.test/v1",
            "test-model",
            "a" * 64,
        )

        with self.assertRaises(WebLLMError) as raised:
            WebLLMFactory.mock_only().build(
                real,
                self.user_id,
                mock_responses=[],
                stop_check=lambda: None,
                remaining_seconds=lambda: 20.0,
            )

        self.assertEqual(raised.exception.code, "llm_configuration_required")

    def test_describe_settings_never_exposes_fingerprint(self):
        snapshot = self.credentials.snapshot(self.user_id)
        state = describe_llm_settings(
            None,
            None,
            snapshot,
            self.network.endpoint_policy,
        )
        self.assertEqual(state["llm_mode"], "mock")
        self.assertTrue(state["llm_configuration_complete"])
        self.assertNotIn("fingerprint", repr(state))

    def test_connection_test_uses_one_attempt_and_creates_no_run(self):
        self.save_llm_settings("https://api.example.test/v1", "test-model")
        self.credentials.put(self.user_id, "SENTINEL-secret")
        attempts = []
        factory = WebLLMFactory(
            self.db_path,
            self.credentials,
            self.network,
            transport_factory=lambda max_attempts: (
                attempts.append(max_attempts) or self.transport
            ),
        )
        service = LLMConnectionTestService(
            factory,
            LLMConnectionTestLimiter(cooldown_seconds=0),
        )

        result = service.test(self.user_id)

        self.assertEqual(
            result,
            {
                "ok": True,
                "mode": "openai-compatible",
                "message": "连接成功，模型服务可用。",
            },
        )
        self.assertEqual(attempts, [1])
        with closing(connect_db(self.db_path)) as conn:
            self.assertEqual(conn.execute("select count(*) from runs").fetchone()[0], 0)

    def test_connection_test_uses_configured_request_timeout(self):
        self.save_llm_settings("https://api.example.test/v1", "test-model")
        self.credentials.put(self.user_id, "SENTINEL-secret")
        network = load_llm_network_config(
            {
                "SPECGATE_LLM_ALLOWED_HOSTS": "api.example.test",
                "SPECGATE_LLM_REQUEST_TIMEOUT_SECONDS": "47",
            }
        )
        transport = RecordingTransport()
        factory = WebLLMFactory(
            self.db_path,
            self.credentials,
            network,
            transport_factory=lambda _max_attempts: transport,
            monotonic_clock=lambda: 100.0,
        )
        service = LLMConnectionTestService(
            factory,
            LLMConnectionTestLimiter(cooldown_seconds=0),
        )

        service.test(self.user_id)

        self.assertEqual(transport.calls[0][3], 47.0)

    def test_connection_test_requires_real_configuration_and_enforces_cooldown(self):
        clock = [10.0]
        limiter = LLMConnectionTestLimiter(
            cooldown_seconds=5,
            monotonic_clock=lambda: clock[0],
        )
        service = LLMConnectionTestService(self.factory, limiter)

        with self.assertRaises(WebLLMError) as missing:
            service.test(self.user_id)
        self.assertEqual(missing.exception.code, "llm_configuration_required")

        clock[0] += 5
        self.save_llm_settings("https://api.example.test/v1", "test-model")
        self.credentials.put(self.user_id, "SENTINEL-secret")
        first = service.test(self.user_id)
        self.assertTrue(first["ok"])
        with self.assertRaises(WebLLMError) as limited:
            service.test(self.user_id)
        self.assertEqual(limited.exception.code, "llm_test_rate_limited")
        clock[0] += 5
        self.assertTrue(service.test(self.user_id)["ok"])


if __name__ == "__main__":
    unittest.main()
