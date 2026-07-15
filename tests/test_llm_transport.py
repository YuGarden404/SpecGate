import socket
import traceback
import unittest
from concurrent.futures import TimeoutError as FutureTimeoutError
from unittest.mock import patch

from specgate.llm_transport import (
    LLMEndpointPolicy,
    LLMTransportError,
    PublicDNSResolver,
    SafeHTTPSChatTransport,
    load_llm_network_config,
)


def address_info(*addresses: str):
    rows = []
    for address in addresses:
        family = socket.AF_INET6 if ":" in address else socket.AF_INET
        sockaddr = (address, 443, 0, 0) if family == socket.AF_INET6 else (address, 443)
        rows.append((family, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", sockaddr))
    return rows


class LLMEndpointPolicyTests(unittest.TestCase):
    def test_empty_allowlist_is_mock_only(self):
        config = load_llm_network_config({})

        with self.assertRaises(LLMTransportError) as raised:
            config.endpoint_policy.normalize("https://api.example.test/v1")

        self.assertEqual(raised.exception.code, "llm_host_not_allowed")

    def test_exact_https_host_and_explicit_port_are_required(self):
        policy = LLMEndpointPolicy.from_csv(
            "api.example.test,alt.example.test:8443"
        )

        endpoint = policy.normalize("https://API.EXAMPLE.TEST/v1/")

        self.assertEqual(endpoint.base_url, "https://api.example.test/v1")
        self.assertEqual(endpoint.chat_path, "/v1/chat/completions")
        self.assertEqual(endpoint.authority, "api.example.test")
        with self.assertRaises(LLMTransportError):
            policy.normalize("http://api.example.test/v1")
        with self.assertRaises(LLMTransportError):
            policy.normalize("https://api.example.test:8443/v1")
        allowed_port = policy.normalize("https://alt.example.test:8443/v1")
        self.assertEqual(allowed_port.authority, "alt.example.test:8443")

    def test_rejects_userinfo_query_fragment_ip_literal_and_dot_segments(self):
        policy = LLMEndpointPolicy.from_csv("api.example.test")
        values = (
            "https://user:pass@api.example.test/v1",
            "https://api.example.test/v1?key=value",
            "https://api.example.test/v1#fragment",
            "https://127.0.0.1/v1",
            "https://api.example.test/v1/../admin",
            "https://api.example.test/v1/%2e%2e/admin",
            "https://api.example.test/v1\\admin",
        )

        for value in values:
            with self.subTest(value=value), self.assertRaises(LLMTransportError):
                policy.normalize(value)

    def test_idna_host_is_canonicalized_before_allowlist_lookup(self):
        policy = LLMEndpointPolicy.from_csv("例子.测试")

        endpoint = policy.normalize("https://例子.测试/v1")

        self.assertEqual(endpoint.host, "xn--fsqu00a.xn--0zwm56d")

    def test_network_integer_limits_are_strict(self):
        config = load_llm_network_config(
            {
                "SPECGATE_LLM_ALLOWED_HOSTS": "api.example.test",
                "SPECGATE_LLM_MAX_OUTPUT_TOKENS": "16384",
                "SPECGATE_LLM_REQUEST_TIMEOUT_SECONDS": "120",
            }
        )
        self.assertEqual(config.max_output_tokens, 16384)
        self.assertEqual(config.request_timeout_seconds, 120)

        for name, value in (
            ("SPECGATE_LLM_MAX_OUTPUT_TOKENS", "255"),
            ("SPECGATE_LLM_MAX_OUTPUT_TOKENS", "16385"),
            ("SPECGATE_LLM_REQUEST_TIMEOUT_SECONDS", "0"),
            ("SPECGATE_LLM_REQUEST_TIMEOUT_SECONDS", "121"),
            ("SPECGATE_LLM_REQUEST_TIMEOUT_SECONDS", "1.5"),
        ):
            with self.subTest(name=name, value=value), self.assertRaises(ValueError):
                load_llm_network_config({name: value})


class PublicDNSResolverTests(unittest.TestCase):
    def test_owned_executor_shutdown_does_not_wait_for_stuck_dns(self):
        class RecordingExecutor:
            def __init__(self):
                self.calls = []

            def shutdown(self, **kwargs):
                self.calls.append(kwargs)

        executor = RecordingExecutor()
        with patch(
            "specgate.llm_transport.ThreadPoolExecutor",
            return_value=executor,
        ):
            resolver = PublicDNSResolver()

        resolver.shutdown()

        self.assertEqual(
            executor.calls,
            [{"wait": False, "cancel_futures": True}],
        )

    def test_all_public_ipv4_and_ipv6_addresses_are_returned(self):
        def fake_getaddrinfo(host, port, *, type):
            self.assertEqual((host, port, type), ("api.example.test", 443, socket.SOCK_STREAM))
            return address_info(
                "93.184.216.34",
                "2606:2800:220:1:248:1893:25c8:1946",
            )

        resolver = PublicDNSResolver(getaddrinfo=fake_getaddrinfo)
        self.addCleanup(resolver.shutdown)

        addresses = resolver.resolve("api.example.test", 443, timeout_seconds=1)

        self.assertEqual(
            addresses,
            (
                "2606:2800:220:1:248:1893:25c8:1946",
                "93.184.216.34",
            ),
        )

    def test_any_non_public_or_mixed_address_fails_closed(self):
        cases = (
            ("127.0.0.1",),
            ("10.0.0.1",),
            ("169.254.169.254",),
            ("::1",),
            ("93.184.216.34", "10.0.0.1"),
        )
        for addresses in cases:
            with self.subTest(addresses=addresses):
                resolver = PublicDNSResolver(
                    getaddrinfo=lambda host, port, *, type, values=addresses: address_info(
                        *values
                    )
                )
                self.addCleanup(resolver.shutdown)
                with self.assertRaises(LLMTransportError) as raised:
                    resolver.resolve("api.example.test", 443, timeout_seconds=1)
                self.assertEqual(raised.exception.code, "llm_address_not_public")

    def test_resolution_failure_uses_stable_retryable_error(self):
        def failing_getaddrinfo(host, port, *, type):
            raise socket.gaierror("SENTINEL resolver detail")

        resolver = PublicDNSResolver(getaddrinfo=failing_getaddrinfo)
        self.addCleanup(resolver.shutdown)

        with self.assertRaises(LLMTransportError) as raised:
            resolver.resolve("api.example.test", 443, timeout_seconds=1)

        self.assertEqual(raised.exception.code, "llm_dns_resolution_failed")
        self.assertTrue(raised.exception.retryable)
        self.assertNotIn("SENTINEL", str(raised.exception))
        rendered = "".join(
            traceback.format_exception(
                raised.exception.__class__,
                raised.exception,
                raised.exception.__traceback__,
            )
        )
        self.assertNotIn("SENTINEL resolver detail", rendered)

    def test_resolution_wait_polls_stop_check_before_timeout(self):
        class PendingFuture:
            def add_done_callback(self, callback):
                self.callback = callback

            def result(self, timeout):
                raise FutureTimeoutError

            def cancel(self):
                return True

        class PendingExecutor:
            def submit(self, function, *args, **kwargs):
                return PendingFuture()

        class Cancelled(RuntimeError):
            pass

        checks = [0]

        def stop_check():
            checks[0] += 1
            if checks[0] >= 2:
                raise Cancelled("cancelled")

        resolver = PublicDNSResolver(
            getaddrinfo=lambda host, port, *, type: [],
            executor=PendingExecutor(),
        )

        with self.assertRaises(Cancelled):
            resolver.resolve(
                "api.example.test",
                443,
                timeout_seconds=1,
                stop_check=stop_check,
            )

    def test_resolution_capacity_is_bounded_while_timed_out_work_is_still_running(self):
        class RunningFuture:
            def __init__(self):
                self.callbacks = []

            def add_done_callback(self, callback):
                self.callbacks.append(callback)

            def result(self, timeout):
                raise FutureTimeoutError

            def cancel(self):
                return False

        class SaturatedExecutor:
            def __init__(self):
                self.submit_calls = 0

            def submit(self, function, *args, **kwargs):
                self.submit_calls += 1
                return RunningFuture()

        executor = SaturatedExecutor()
        resolver = PublicDNSResolver(
            getaddrinfo=lambda host, port, *, type: [],
            executor=executor,
            max_pending=1,
        )

        with self.assertRaises(LLMTransportError) as timed_out:
            resolver.resolve("api.example.test", 443, timeout_seconds=0.001)
        with self.assertRaises(LLMTransportError) as saturated:
            resolver.resolve("api.example.test", 443, timeout_seconds=1)

        self.assertEqual(timed_out.exception.code, "llm_dns_resolution_failed")
        self.assertEqual(saturated.exception.code, "llm_dns_resolution_failed")
        self.assertTrue(saturated.exception.retryable)
        self.assertEqual(executor.submit_calls, 1)


class FakeResolver:
    def __init__(self, addresses=("93.184.216.34",)):
        self.addresses = addresses
        self.calls = []

    def resolve(self, host, port, *, timeout_seconds, stop_check):
        self.calls.append((host, port, timeout_seconds))
        stop_check()
        return self.addresses


class FakeHTTPResponse:
    def __init__(self, status=200, body=b'{"ok":true}', headers=None):
        self.status = status
        self.body = body
        self.headers = headers or {}
        self.offset = 0
        self.read_calls = 0
        self.closed = False

    def getheader(self, name):
        return self.headers.get(name)

    def read(self, size=-1):
        self.read_calls += 1
        if size < 0:
            size = len(self.body) - self.offset
        chunk = self.body[self.offset : self.offset + size]
        self.offset += len(chunk)
        return chunk

    def close(self):
        self.closed = True


class FakeHTTPSConnection:
    def __init__(self, response):
        self.response = response
        self.requests = []
        self.closed = False

    def request(self, method, path, body, headers):
        self.requests.append((method, path, body, headers))

    def getresponse(self):
        return self.response

    def close(self):
        self.closed = True


class ScriptedConnectionFactory:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.connections = []

    def __call__(self, endpoint, connect_ip, timeout):
        self.calls.append((endpoint, connect_ip, timeout))
        response = self.responses.pop(0)
        connection = FakeHTTPSConnection(response)
        self.connections.append(connection)
        return connection


class SafeHTTPSChatTransportTests(unittest.TestCase):
    def endpoint(self):
        return LLMEndpointPolicy.from_csv("api.example.test").normalize(
            "https://api.example.test/v1"
        )

    def make_transport(self, responses, **overrides):
        resolver = FakeResolver()
        factory = ScriptedConnectionFactory(responses)
        sleeps = []
        transport = SafeHTTPSChatTransport(
            resolver=resolver,
            connection_factory=factory,
            sleeper=sleeps.append,
            **overrides,
        )
        return transport, resolver, factory, sleeps

    def test_connects_to_validated_ip_with_original_host_and_path(self):
        response = FakeHTTPResponse(body=b'{"choices":[]}')
        transport, resolver, factory, _sleeps = self.make_transport([response])

        result = transport.post_json(
            self.endpoint(),
            {"Authorization": "Bearer SENTINEL"},
            b"{}",
            stop_check=lambda: None,
            remaining_seconds=lambda: 20.0,
        )

        self.assertEqual(result, b'{"choices":[]}')
        self.assertEqual(resolver.calls[0][:2], ("api.example.test", 443))
        endpoint, connect_ip, timeout = factory.calls[0]
        self.assertEqual(connect_ip, "93.184.216.34")
        self.assertEqual(endpoint.host, "api.example.test")
        self.assertEqual(timeout, 20.0)
        method, path, _body, headers = factory.connections[0].requests[0]
        self.assertEqual((method, path), ("POST", "/v1/chat/completions"))
        self.assertEqual(headers["Host"], "api.example.test")
        self.assertTrue(response.closed)
        self.assertTrue(factory.connections[0].closed)

    def test_injected_transport_never_uses_real_dns_or_socket(self):
        response = FakeHTTPResponse(body=b'{"choices":[]}')
        transport, _resolver, _factory, _sleeps = self.make_transport([response])

        with patch("socket.getaddrinfo", side_effect=AssertionError("real DNS")), patch(
            "socket.create_connection",
            side_effect=AssertionError("real socket"),
        ):
            result = transport.post_json(
                self.endpoint(),
                {},
                b"{}",
                stop_check=lambda: None,
                remaining_seconds=lambda: 20.0,
            )

        self.assertEqual(result, b'{"choices":[]}')

    def test_redirect_is_rejected_without_reading_body(self):
        for status in (301, 302, 303, 307, 308):
            with self.subTest(status=status):
                response = FakeHTTPResponse(
                    status=status,
                    body=b"SENTINEL redirect body",
                    headers={"Location": "https://evil.test"},
                )
                transport, _resolver, _factory, _sleeps = self.make_transport(
                    [response]
                )
                with self.assertRaises(LLMTransportError) as raised:
                    transport.post_json(
                        self.endpoint(),
                        {},
                        b"{}",
                        stop_check=lambda: None,
                        remaining_seconds=lambda: 20.0,
                    )
                self.assertEqual(raised.exception.code, "llm_redirect_forbidden")
                self.assertEqual(response.read_calls, 0)
                self.assertNotIn("SENTINEL", str(raised.exception))

    def test_retryable_statuses_retry_twice_without_reading_error_bodies(self):
        responses = [
            FakeHTTPResponse(503, b"SENTINEL first"),
            FakeHTTPResponse(429, b"SENTINEL second"),
            FakeHTTPResponse(200, b'{"ok":true}'),
        ]
        transport, _resolver, factory, sleeps = self.make_transport(responses)

        result = transport.post_json(
            self.endpoint(),
            {},
            b"{}",
            stop_check=lambda: None,
            remaining_seconds=lambda: 20.0,
        )

        self.assertEqual(result, b'{"ok":true}')
        self.assertEqual(len(factory.calls), 3)
        self.assertEqual(sleeps, [0.5, 1.0])
        self.assertEqual([response.read_calls for response in responses[:2]], [0, 0])

    def test_authentication_failure_is_not_retried_or_read(self):
        response = FakeHTTPResponse(401, b"SENTINEL auth body")
        transport, _resolver, factory, sleeps = self.make_transport([response])

        with self.assertRaises(LLMTransportError) as raised:
            transport.post_json(
                self.endpoint(),
                {},
                b"{}",
                stop_check=lambda: None,
                remaining_seconds=lambda: 20.0,
            )

        self.assertEqual(raised.exception.code, "llm_authentication_failed")
        self.assertEqual(len(factory.calls), 1)
        self.assertEqual(sleeps, [])
        self.assertEqual(response.read_calls, 0)

    def test_content_length_and_streamed_body_are_bounded(self):
        oversized_length = FakeHTTPResponse(
            headers={"Content-Length": str(1024 * 1024 + 1)}
        )
        transport, _resolver, _factory, _sleeps = self.make_transport(
            [oversized_length]
        )
        with self.assertRaises(LLMTransportError) as raised:
            transport.post_json(
                self.endpoint(),
                {},
                b"{}",
                stop_check=lambda: None,
                remaining_seconds=lambda: 20.0,
            )
        self.assertEqual(raised.exception.code, "llm_response_too_large")
        self.assertEqual(oversized_length.read_calls, 0)

        streamed = FakeHTTPResponse(body=b"x" * 17)
        transport, _resolver, _factory, _sleeps = self.make_transport(
            [streamed],
            max_response_bytes=16,
        )
        with self.assertRaises(LLMTransportError) as raised:
            transport.post_json(
                self.endpoint(),
                {},
                b"{}",
                stop_check=lambda: None,
                remaining_seconds=lambda: 20.0,
            )
        self.assertEqual(raised.exception.code, "llm_response_too_large")

    def test_cancel_during_backoff_stops_before_another_request(self):
        response = FakeHTTPResponse(503, b"ignored")
        resolver = FakeResolver()
        factory = ScriptedConnectionFactory([response])
        cancelled = [False]

        class Cancelled(RuntimeError):
            pass

        def stop_check():
            if cancelled[0]:
                raise Cancelled("cancelled")

        def sleeper(_seconds):
            cancelled[0] = True

        transport = SafeHTTPSChatTransport(
            resolver=resolver,
            connection_factory=factory,
            sleeper=sleeper,
        )

        with self.assertRaises(Cancelled):
            transport.post_json(
                self.endpoint(),
                {},
                b"{}",
                stop_check=stop_check,
                remaining_seconds=lambda: 20.0,
            )
        self.assertEqual(len(factory.calls), 1)

    def test_cancel_during_response_read_stops_without_returning_partial_json(self):
        cancelled = [False]

        class CancellingResponse(FakeHTTPResponse):
            def read(self, size=-1):
                chunk = super().read(size)
                cancelled[0] = True
                return chunk

        class Cancelled(RuntimeError):
            pass

        def stop_check():
            if cancelled[0]:
                raise Cancelled("cancelled")

        response = CancellingResponse(body=b'{"choices":[]}')
        transport, _resolver, factory, _sleeps = self.make_transport([response])

        with self.assertRaises(Cancelled):
            transport.post_json(
                self.endpoint(),
                {},
                b"{}",
                stop_check=stop_check,
                remaining_seconds=lambda: 20.0,
            )

        self.assertTrue(response.closed)
        self.assertTrue(factory.connections[0].closed)


if __name__ == "__main__":
    unittest.main()
