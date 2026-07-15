from __future__ import annotations

from contextlib import closing, contextmanager
from pathlib import Path
from threading import BoundedSemaphore, Lock
from time import monotonic
from typing import Callable

from specgate.llm import LLMClient, MockLLM, OpenAICompatibleLLM
from specgate.llm_config import LLMRunConfig
from specgate.llm_transport import (
    LLMEndpointPolicy,
    LLMNetworkConfig,
    LLMTransportError,
    NormalizedEndpoint,
    PublicDNSResolver,
    SafeHTTPSChatTransport,
    load_llm_network_config,
)
from specgate.web_credentials import (
    CredentialSnapshot,
    WebCredentialError,
    WebCredentialService,
)
from specgate.web_db import connect_db


class WebLLMError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _get_matching_api_key(
    credentials: WebCredentialService,
    user_id: int,
    fingerprint: str,
) -> str:
    try:
        return credentials.get_matching(user_id, fingerprint)
    except WebCredentialError as exc:
        code = exc.code
        if code in {
            "credential_store_unavailable",
            "invalid_credential_key",
            "credential_decryption_failed",
        }:
            code = "credential_unavailable"
        raise WebLLMError(code) from exc


def validate_llm_model(raw: object) -> str:
    if not isinstance(raw, str):
        raise WebLLMError("llm_configuration_required")
    model = raw.strip()
    if (
        not model
        or len(model) > 256
        or any(ord(char) < 32 or ord(char) == 127 for char in model)
    ):
        raise WebLLMError("llm_configuration_required")
    return model


def _configuration_error_for_snapshot(snapshot: CredentialSnapshot) -> str:
    if snapshot.requires_reentry:
        return "credential_requires_reentry"
    if not snapshot.store_available:
        return "credential_unavailable"
    return "llm_configuration_required"


def describe_llm_settings(
    base_url: object,
    model: object,
    credential: CredentialSnapshot,
    endpoint_policy: LLMEndpointPolicy,
) -> dict[str, object]:
    if not credential.exists:
        return {
            "llm_mode": "mock",
            "llm_configuration_complete": True,
        }
    if not credential.configured:
        return {
            "llm_mode": "configuration_required",
            "llm_configuration_complete": False,
        }
    if not base_url or not model:
        return {
            "llm_mode": "configuration_required",
            "llm_configuration_complete": False,
        }
    try:
        endpoint_policy.normalize(base_url)
        validate_llm_model(model)
    except (LLMTransportError, WebLLMError):
        return {
            "llm_mode": "configuration_required",
            "llm_configuration_complete": False,
        }
    return {
        "llm_mode": "openai-compatible",
        "llm_configuration_complete": True,
    }


class CredentialBoundLLM:
    def __init__(
        self,
        *,
        user_id: int,
        config: LLMRunConfig,
        endpoint: NormalizedEndpoint,
        credentials: WebCredentialService,
        transport,
        max_output_tokens: int,
        stop_check: Callable[[], None],
        remaining_seconds: Callable[[], float],
    ) -> None:
        self.user_id = user_id
        self.config = config
        self.endpoint = endpoint
        self.credentials = credentials
        self.transport = transport
        self.max_output_tokens = max_output_tokens
        self.stop_check = stop_check
        self.remaining_seconds = remaining_seconds

    def complete(self, context: str) -> str:
        self.stop_check()
        fingerprint = self.config.credential_fingerprint
        model = self.config.model
        if fingerprint is None or model is None:
            raise WebLLMError("invalid_llm_config")
        api_key = _get_matching_api_key(
            self.credentials,
            self.user_id,
            fingerprint,
        )
        try:
            client = OpenAICompatibleLLM(
                self.endpoint.base_url,
                api_key,
                model,
                max_tokens=self.max_output_tokens,
                endpoint=self.endpoint,
                transport=self.transport,
                stop_check=self.stop_check,
                remaining_seconds=self.remaining_seconds,
            )
            return client.complete(context)
        finally:
            del api_key


class WebLLMFactory:
    def __init__(
        self,
        db_path: Path | None,
        credentials: WebCredentialService | None,
        network_config: LLMNetworkConfig,
        *,
        transport_factory: Callable[[int], object] | None = None,
        monotonic_clock: Callable[[], float] = monotonic,
        mock_factory=MockLLM,
    ) -> None:
        self.db_path = db_path
        self.credentials = credentials
        self.network_config = network_config
        self.endpoint_policy = network_config.endpoint_policy
        self.monotonic_clock = monotonic_clock
        self.mock_factory = mock_factory
        self._resolver: PublicDNSResolver | None = None
        if transport_factory is None and credentials is not None:
            self._resolver = PublicDNSResolver()

            def default_transport(max_attempts: int):
                return SafeHTTPSChatTransport(
                    resolver=self._resolver,
                    request_timeout_seconds=network_config.request_timeout_seconds,
                    max_response_bytes=network_config.max_response_bytes,
                    max_attempts=max_attempts,
                )

            self.transport_factory = default_transport
        else:
            self.transport_factory = transport_factory

    @classmethod
    def mock_only(cls, *, mock_factory=MockLLM) -> WebLLMFactory:
        return cls(
            None,
            None,
            load_llm_network_config({}),
            mock_factory=mock_factory,
        )

    def freeze_config(self, conn, user_id: int) -> LLMRunConfig:
        if self.credentials is None:
            return LLMRunConfig.mock()
        row = conn.execute(
            """
            select llm_base_url, llm_model
            from user_settings where user_id = ?
            """,
            (user_id,),
        ).fetchone()
        if row is None:
            raise WebLLMError("llm_configuration_required")
        snapshot = self.credentials.snapshot(user_id, conn=conn)
        if not snapshot.exists:
            return LLMRunConfig.mock()
        if not snapshot.configured or snapshot.fingerprint is None:
            raise WebLLMError(_configuration_error_for_snapshot(snapshot))
        if not row["llm_base_url"] or not row["llm_model"]:
            raise WebLLMError("llm_configuration_required")
        try:
            endpoint = self.endpoint_policy.normalize(row["llm_base_url"])
        except LLMTransportError as exc:
            raise WebLLMError(exc.code) from exc
        model = validate_llm_model(row["llm_model"])
        return LLMRunConfig.real(
            endpoint.base_url,
            model,
            snapshot.fingerprint,
        )

    def preflight_resume(self, config: LLMRunConfig, user_id: int) -> None:
        if config.mode == "mock":
            return
        if self.credentials is None:
            raise WebLLMError("llm_configuration_required")
        fingerprint = config.credential_fingerprint
        if fingerprint is None:
            raise WebLLMError("invalid_llm_config")
        api_key = _get_matching_api_key(self.credentials, user_id, fingerprint)
        del api_key

    def build(
        self,
        config: LLMRunConfig,
        user_id: int,
        *,
        mock_responses: list[dict],
        stop_check: Callable[[], None],
        remaining_seconds: Callable[[], float],
    ) -> LLMClient:
        if config.mode == "mock":
            return self.mock_factory(mock_responses)
        if self.credentials is None or self.transport_factory is None:
            raise WebLLMError("llm_configuration_required")
        return self._build_real(
            config,
            user_id,
            stop_check=stop_check,
            remaining_seconds=remaining_seconds,
            max_attempts=3,
            max_output_tokens=self.network_config.max_output_tokens,
        )

    def _build_real(
        self,
        config: LLMRunConfig,
        user_id: int,
        *,
        stop_check: Callable[[], None],
        remaining_seconds: Callable[[], float],
        max_attempts: int,
        max_output_tokens: int,
    ) -> LLMClient:
        if self.credentials is None or self.transport_factory is None:
            raise WebLLMError("llm_configuration_required")
        try:
            endpoint = self.endpoint_policy.normalize(config.base_url)
        except LLMTransportError as exc:
            raise WebLLMError(exc.code) from exc
        return CredentialBoundLLM(
            user_id=user_id,
            config=config,
            endpoint=endpoint,
            credentials=self.credentials,
            transport=self.transport_factory(max_attempts),
            max_output_tokens=max_output_tokens,
            stop_check=stop_check,
            remaining_seconds=remaining_seconds,
        )

    def test_connection(self, user_id: int, *, timeout_seconds: float = 10.0) -> None:
        if self.db_path is None:
            raise WebLLMError("llm_configuration_required")
        with closing(connect_db(self.db_path)) as conn:
            config = self.freeze_config(conn, user_id)
        if config.mode != "openai-compatible":
            raise WebLLMError("llm_configuration_required")
        deadline = self.monotonic_clock() + timeout_seconds
        llm = self._build_real(
            config,
            user_id,
            stop_check=lambda: None,
            remaining_seconds=lambda: max(
                0.0,
                deadline - self.monotonic_clock(),
            ),
            max_attempts=1,
            max_output_tokens=8,
        )
        llm.complete("连接测试：请只返回 OK。")

    def shutdown(self) -> None:
        if self._resolver is not None:
            self._resolver.shutdown()


class LLMConnectionTestLimiter:
    def __init__(
        self,
        max_concurrent: int = 4,
        cooldown_seconds: float = 5.0,
        monotonic_clock: Callable[[], float] = monotonic,
    ) -> None:
        if max_concurrent < 1:
            raise ValueError("max_concurrent must be positive")
        if cooldown_seconds < 0:
            raise ValueError("cooldown_seconds must be non-negative")
        self._slots = BoundedSemaphore(max_concurrent)
        self._cooldown = cooldown_seconds
        self._clock = monotonic_clock
        self._lock = Lock()
        self._active: set[int] = set()
        self._last_finished: dict[int, float] = {}

    @contextmanager
    def acquire(self, user_id: int):
        if not self._slots.acquire(blocking=False):
            raise WebLLMError("llm_test_rate_limited")
        admitted = False
        try:
            with self._lock:
                now = self._clock()
                last = self._last_finished.get(user_id)
                if user_id in self._active or (
                    last is not None and now - last < self._cooldown
                ):
                    raise WebLLMError("llm_test_rate_limited")
                self._active.add(user_id)
                admitted = True
            yield
        finally:
            if admitted:
                with self._lock:
                    self._active.discard(user_id)
                    self._last_finished[user_id] = self._clock()
            self._slots.release()


class LLMConnectionTestService:
    def __init__(
        self,
        factory: WebLLMFactory,
        limiter: LLMConnectionTestLimiter,
    ) -> None:
        self.factory = factory
        self.limiter = limiter

    def test(self, user_id: int) -> dict[str, object]:
        with self.limiter.acquire(user_id):
            self.factory.test_connection(user_id, timeout_seconds=10.0)
        return {
            "ok": True,
            "mode": "openai-compatible",
            "message": "连接成功，模型服务可用。",
        }
