from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from dataclasses import dataclass
import http.client
import ipaddress
import os
import socket
import ssl
from threading import BoundedSemaphore
import time
from typing import Callable, Mapping
from urllib.parse import unquote, urlsplit


MAX_BASE_URL_CHARS = 2048
MAX_RESPONSE_BYTES = 1024 * 1024


class LLMTransportError(RuntimeError):
    def __init__(
        self,
        code: str,
        *,
        retryable: bool = False,
        status: int | None = None,
    ) -> None:
        self.code = code
        self.retryable = retryable
        self.status = status
        super().__init__(code)


@dataclass(frozen=True)
class NormalizedEndpoint:
    base_url: str
    host: str
    port: int
    chat_path: str
    authority: str


def _canonical_host(raw: str) -> str:
    candidate = raw.rstrip(".")
    if not candidate or any(ord(char) < 33 or ord(char) == 127 for char in candidate):
        raise ValueError("invalid LLM host")
    try:
        host = candidate.encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise ValueError("invalid LLM host") from exc
    if len(host) > 253 or any(
        not label or len(label) > 63 for label in host.split(".")
    ):
        raise ValueError("invalid LLM host")
    return host


def _is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


@dataclass(frozen=True)
class LLMEndpointPolicy:
    allowed: frozenset[tuple[str, int]]

    @classmethod
    def from_csv(cls, raw: str | None) -> LLMEndpointPolicy:
        if raw is None or not raw.strip():
            return cls(frozenset())
        entries: set[tuple[str, int]] = set()
        for item in raw.split(","):
            value = item.strip()
            if not value or "/" in value or "@" in value or "?" in value or "#" in value:
                raise ValueError("invalid SPECGATE_LLM_ALLOWED_HOSTS")
            if value.count(":") > 1:
                raise ValueError("invalid SPECGATE_LLM_ALLOWED_HOSTS")
            if ":" in value:
                host_value, port_value = value.rsplit(":", 1)
                if not port_value.isascii() or not port_value.isdecimal():
                    raise ValueError("invalid SPECGATE_LLM_ALLOWED_HOSTS")
                port = int(port_value)
                if not 1 <= port <= 65535:
                    raise ValueError("invalid SPECGATE_LLM_ALLOWED_HOSTS")
            else:
                host_value = value
                port = 443
            host = _canonical_host(host_value)
            if _is_ip_literal(host):
                raise ValueError("invalid SPECGATE_LLM_ALLOWED_HOSTS")
            entries.add((host, port))
        return cls(frozenset(entries))

    def normalize(self, raw_url: str) -> NormalizedEndpoint:
        if (
            not isinstance(raw_url, str)
            or not raw_url
            or len(raw_url) > MAX_BASE_URL_CHARS
            or any(ord(char) < 32 or ord(char) == 127 for char in raw_url)
        ):
            raise LLMTransportError("llm_url_invalid")
        try:
            parsed = urlsplit(raw_url)
            port = parsed.port or 443
        except ValueError as exc:
            raise LLMTransportError("llm_url_invalid") from exc
        if (
            parsed.scheme.lower() != "https"
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.hostname is None
            or "\\" in parsed.path
        ):
            raise LLMTransportError("llm_url_invalid")
        try:
            host = _canonical_host(parsed.hostname)
        except ValueError as exc:
            raise LLMTransportError("llm_url_invalid") from exc
        if _is_ip_literal(host):
            raise LLMTransportError("llm_url_invalid")
        decoded_path = unquote(parsed.path)
        if "\\" in decoded_path:
            raise LLMTransportError("llm_url_invalid")
        segments = decoded_path.split("/")
        if any(segment in {".", ".."} for segment in segments):
            raise LLMTransportError("llm_url_invalid")
        if (host, port) not in self.allowed:
            raise LLMTransportError("llm_host_not_allowed")
        normalized_segments = [segment for segment in segments if segment]
        normalized_path = (
            "/" + "/".join(normalized_segments) if normalized_segments else ""
        )
        authority = host if port == 443 else f"{host}:{port}"
        base_url = f"https://{authority}{normalized_path}"
        chat_path = f"{normalized_path}/chat/completions"
        return NormalizedEndpoint(base_url, host, port, chat_path, authority)


@dataclass(frozen=True)
class LLMNetworkConfig:
    endpoint_policy: LLMEndpointPolicy
    max_output_tokens: int = 4096
    request_timeout_seconds: int = 30
    max_response_bytes: int = MAX_RESPONSE_BYTES


def _parse_integer(
    source: Mapping[str, str],
    name: str,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    raw = source.get(name)
    if raw is None:
        return default
    if not raw or not raw.isascii() or not raw.isdecimal():
        raise ValueError(f"{name} must be a decimal integer")
    value = int(raw)
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


def load_llm_network_config(
    source: Mapping[str, str] | None = None,
) -> LLMNetworkConfig:
    values = os.environ if source is None else source
    return LLMNetworkConfig(
        endpoint_policy=LLMEndpointPolicy.from_csv(
            values.get("SPECGATE_LLM_ALLOWED_HOSTS")
        ),
        max_output_tokens=_parse_integer(
            values,
            "SPECGATE_LLM_MAX_OUTPUT_TOKENS",
            4096,
            256,
            16384,
        ),
        request_timeout_seconds=_parse_integer(
            values,
            "SPECGATE_LLM_REQUEST_TIMEOUT_SECONDS",
            30,
            1,
            120,
        ),
    )


class PublicDNSResolver:
    def __init__(
        self,
        *,
        getaddrinfo=socket.getaddrinfo,
        executor: ThreadPoolExecutor | None = None,
        max_pending: int = 8,
    ) -> None:
        if isinstance(max_pending, bool) or not isinstance(max_pending, int) or max_pending < 1:
            raise ValueError("max_pending must be a positive integer")
        self._getaddrinfo = getaddrinfo
        self._executor = executor or ThreadPoolExecutor(
            max_workers=4,
            thread_name_prefix="specgate-llm-dns",
        )
        self._owns_executor = executor is None
        self._pending_slots = BoundedSemaphore(max_pending)

    def _release_pending_slot(self, _future) -> None:
        self._pending_slots.release()

    def resolve(
        self,
        host: str,
        port: int,
        *,
        timeout_seconds: float,
        stop_check: Callable[[], None] = lambda: None,
    ) -> tuple[str, ...]:
        stop_check()
        if not self._pending_slots.acquire(blocking=False):
            raise LLMTransportError(
                "llm_dns_resolution_failed",
                retryable=True,
            )
        try:
            future = self._executor.submit(
                self._getaddrinfo,
                host,
                port,
                type=socket.SOCK_STREAM,
            )
        except BaseException as exc:
            self._pending_slots.release()
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            raise LLMTransportError(
                "llm_dns_resolution_failed",
                retryable=True,
            ) from None
        future.add_done_callback(self._release_pending_slot)
        deadline = time.monotonic() + max(0.001, timeout_seconds)
        try:
            while True:
                stop_check()
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise FutureTimeoutError
                try:
                    rows = future.result(timeout=min(0.05, remaining))
                    break
                except FutureTimeoutError:
                    continue
        except FutureTimeoutError as exc:
            future.cancel()
            raise LLMTransportError(
                "llm_dns_resolution_failed",
                retryable=True,
            ) from exc
        except (OSError, socket.gaierror):
            raise LLMTransportError(
                "llm_dns_resolution_failed",
                retryable=True,
            ) from None
        except BaseException:
            future.cancel()
            raise
        stop_check()
        addresses = sorted({row[4][0] for row in rows if row[4]})
        if not addresses:
            raise LLMTransportError(
                "llm_dns_resolution_failed",
                retryable=True,
            )
        try:
            parsed = [ipaddress.ip_address(address) for address in addresses]
        except ValueError as exc:
            raise LLMTransportError("llm_address_not_public") from exc
        if any(not address.is_global for address in parsed):
            raise LLMTransportError("llm_address_not_public")
        return tuple(addresses)

    def shutdown(self) -> None:
        if self._owns_executor:
            self._executor.shutdown(wait=False, cancel_futures=True)


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(
        self,
        host: str,
        port: int,
        connect_ip: str,
        *,
        timeout: float,
        context: ssl.SSLContext,
    ) -> None:
        super().__init__(host, port=port, timeout=timeout, context=context)
        self._connect_ip = connect_ip

    def connect(self) -> None:
        raw_socket = socket.create_connection(
            (self._connect_ip, self.port),
            self.timeout,
            self.source_address,
        )
        try:
            self.sock = self._context.wrap_socket(
                raw_socket,
                server_hostname=self.host,
            )
        except Exception:
            raw_socket.close()
            raise


def _error_for_status(status: int) -> LLMTransportError:
    if status in {301, 302, 303, 307, 308}:
        return LLMTransportError("llm_redirect_forbidden", status=status)
    if status in {401, 403}:
        return LLMTransportError("llm_authentication_failed", status=status)
    if status in {400, 404, 422}:
        return LLMTransportError("llm_request_rejected", status=status)
    if status == 408:
        return LLMTransportError(
            "llm_request_timeout",
            retryable=True,
            status=status,
        )
    if status == 429:
        return LLMTransportError(
            "llm_rate_limited",
            retryable=True,
            status=status,
        )
    if 500 <= status <= 599:
        return LLMTransportError(
            "llm_provider_unavailable",
            retryable=True,
            status=status,
        )
    return LLMTransportError("llm_request_rejected", status=status)


class SafeHTTPSChatTransport:
    def __init__(
        self,
        *,
        resolver: PublicDNSResolver,
        request_timeout_seconds: float = 30.0,
        max_response_bytes: int = MAX_RESPONSE_BYTES,
        max_attempts: int = 3,
        connection_factory=None,
        sleeper: Callable[[float], None] = time.sleep,
        ssl_context: ssl.SSLContext | None = None,
    ) -> None:
        if max_attempts < 1 or max_attempts > 3:
            raise ValueError("max_attempts must be between 1 and 3")
        if max_response_bytes < 1:
            raise ValueError("max_response_bytes must be positive")
        self.resolver = resolver
        self.request_timeout_seconds = request_timeout_seconds
        self.max_response_bytes = max_response_bytes
        self.max_attempts = max_attempts
        self.sleeper = sleeper
        self.ssl_context = ssl_context or ssl.create_default_context()
        self.connection_factory = connection_factory or self._create_connection

    def _create_connection(
        self,
        endpoint: NormalizedEndpoint,
        connect_ip: str,
        timeout: float,
    ) -> _PinnedHTTPSConnection:
        return _PinnedHTTPSConnection(
            endpoint.host,
            endpoint.port,
            connect_ip,
            timeout=timeout,
            context=self.ssl_context,
        )

    def post_json(
        self,
        endpoint: NormalizedEndpoint,
        headers: Mapping[str, str],
        body: bytes,
        *,
        stop_check: Callable[[], None],
        remaining_seconds: Callable[[], float],
    ) -> bytes:
        last_error: LLMTransportError | None = None
        for attempt in range(self.max_attempts):
            stop_check()
            remaining = remaining_seconds()
            if remaining <= 0:
                raise LLMTransportError("llm_request_timeout")
            timeout = min(self.request_timeout_seconds, remaining)
            response = None
            connection = None
            try:
                addresses = self.resolver.resolve(
                    endpoint.host,
                    endpoint.port,
                    timeout_seconds=timeout,
                    stop_check=stop_check,
                )
                connect_ip = addresses[attempt % len(addresses)]
                connection = self.connection_factory(endpoint, connect_ip, timeout)
                request_headers = dict(headers)
                request_headers["Host"] = endpoint.authority
                connection.request(
                    "POST",
                    endpoint.chat_path,
                    body=body,
                    headers=request_headers,
                )
                stop_check()
                response = connection.getresponse()
                if not 200 <= response.status <= 299:
                    raise _error_for_status(response.status)
                return self._read_success_response(response, stop_check)
            except LLMTransportError as exc:
                last_error = exc
            except ssl.SSLError:
                last_error = LLMTransportError("llm_tls_failed")
            except TimeoutError:
                last_error = LLMTransportError(
                    "llm_request_timeout",
                    retryable=True,
                )
            except OSError:
                last_error = LLMTransportError(
                    "llm_provider_unavailable",
                    retryable=True,
                )
            finally:
                if response is not None:
                    response.close()
                if connection is not None:
                    connection.close()

            if not last_error.retryable or attempt + 1 >= self.max_attempts:
                raise last_error
            delay = 0.5 * (2**attempt)
            stop_check()
            if remaining_seconds() <= delay:
                raise LLMTransportError("llm_request_timeout")
            self.sleeper(delay)
            stop_check()
        raise last_error or LLMTransportError("llm_provider_unavailable")

    def _read_success_response(
        self,
        response,
        stop_check: Callable[[], None],
    ) -> bytes:
        content_length = response.getheader("Content-Length")
        if content_length is not None:
            try:
                declared_length = int(content_length)
            except (TypeError, ValueError) as exc:
                raise LLMTransportError("llm_response_invalid") from exc
            if declared_length < 0:
                raise LLMTransportError("llm_response_invalid")
            if declared_length > self.max_response_bytes:
                raise LLMTransportError("llm_response_too_large")
        chunks: list[bytes] = []
        total = 0
        while True:
            stop_check()
            chunk = response.read(64 * 1024)
            stop_check()
            if not chunk:
                break
            total += len(chunk)
            if total > self.max_response_bytes:
                raise LLMTransportError("llm_response_too_large")
            chunks.append(chunk)
        return b"".join(chunks)
