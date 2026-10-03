from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
import gzip
import http.client
import inspect
import io
import json
from pathlib import Path
import socket
import ssl
import zlib

import pytest

from sportsmodel.nfl import historical_market_pilot as core
from sportsmodel.nfl import historical_market_odds_api_transport as transport


ROOT = Path(__file__).resolve().parents[2]
SELECTION = core.load_frozen_selection(
    ROOT
    / "docs"
    / "architecture"
    / "nfl_historical_market_provider_pilot_selection_manifest_0.1.3.json"
)
SECRET = "TEST_KEY_DO_NOT_SEND"


class FakeSocket:
    def __init__(self) -> None:
        self.timeout: float | None = None

    def settimeout(self, value: float) -> None:
        self.timeout = value


class FakeResponse:
    def __init__(
        self,
        status: int = 200,
        headers: list[tuple[str, str]] | None = None,
        body: bytes = b'{"synthetic":true}',
        read_error: BaseException | None = None,
        chunked: bool = False,
    ):
        self.status = status
        self._headers = headers or []
        self._body = body
        self._read_error = read_error
        self.chunked = chunked

    def getheaders(self) -> list[tuple[str, str]]:
        return list(self._headers)

    def read(self) -> bytes:
        if self._read_error is not None:
            raise self._read_error
        return self._body


class FakeConnection:
    def __init__(
        self,
        *,
        response: FakeResponse | http.client.HTTPResponse | None = None,
        connect_error: BaseException | None = None,
        buffer_error: BaseException | None = None,
        send_error: BaseException | None = None,
        receive_error: BaseException | None = None,
    ):
        self.sock = FakeSocket()
        self.response = response or FakeResponse()
        self.connect_error = connect_error
        self.buffer_error = buffer_error
        self.send_error = send_error
        self.receive_error = receive_error
        self.target: str | None = None
        self.headers: list[tuple[str, str]] = []
        self.putrequest_calls = 0
        self.connected = False
        self.sent = False
        self.closed = False
        self.close_calls = 0

    def connect(self) -> None:
        if self.connect_error is not None:
            raise self.connect_error
        self.connected = True

    def putrequest(self, method: str, target: str, **kwargs: object) -> None:
        assert method == "GET"
        assert kwargs == {"skip_host": True, "skip_accept_encoding": True}
        if self.buffer_error is not None:
            raise self.buffer_error
        self.putrequest_calls += 1
        self.target = target

    def putheader(self, name: str, value: str) -> None:
        self.headers.append((name, value))

    def endheaders(self) -> None:
        self.sent = True
        if self.send_error is not None:
            raise self.send_error

    def getresponse(self) -> FakeResponse | http.client.HTTPResponse:
        if self.receive_error is not None:
            raise self.receive_error
        return self.response

    def close(self) -> None:
        self.close_calls += 1
        self.closed = True
        if isinstance(self.response, http.client.HTTPResponse):
            self.response.close()


class InMemorySocket:
    def __init__(self, payload: bytes):
        self._file = io.BytesIO(payload)

    def makefile(self, _mode: str, _buffering: int | None = None) -> io.BytesIO:
        return self._file


def parsed_http_response(payload: bytes) -> http.client.HTTPResponse:
    response = http.client.HTTPResponse(InMemorySocket(payload))  # type: ignore[arg-type]
    response.begin()
    return response


@pytest.fixture(autouse=True)
def deny_real_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def blocked(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("real socket/DNS use is prohibited in transport tests")

    monkeypatch.setattr(socket, "socket", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(socket, "getaddrinfo", blocked)


@pytest.fixture()
def provider_request() -> core.ProviderRequest:
    return core.provider_request(SELECTION.targets[0])


def prepared(
    monkeypatch: pytest.MonkeyPatch, connection: FakeConnection
) -> tuple[transport.OddsApiHistoricalTransport, list[ssl.SSLContext]]:
    instance = transport.OddsApiHistoricalTransport()
    contexts: list[ssl.SSLContext] = []

    def new_connection(
        host: str,
        *,
        port: int,
        timeout: float,
        context: ssl.SSLContext,
    ) -> FakeConnection:
        assert host == transport.PROVIDER_HOST
        assert port == transport.PROVIDER_PORT
        assert timeout == instance.timeouts.connect_seconds
        contexts.append(context)
        return connection

    monkeypatch.setattr(transport.http.client, "HTTPSConnection", new_connection)
    return instance, contexts


def test_exact_endpoint_and_https_identity() -> None:
    instance = transport.OddsApiHistoricalTransport()
    assert instance.identity_payload["scheme"] == "https"
    assert instance.identity_payload["host"] == "api.the-odds-api.com"
    assert instance.identity_payload["port"] == 443


def test_constructor_has_no_host_scheme_tls_or_proxy_override() -> None:
    with pytest.raises(TypeError):
        transport.OddsApiHistoricalTransport(host="evil.example")  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        transport.OddsApiHistoricalTransport(verify=False)  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        transport.OddsApiHistoricalTransport(proxy="http://evil")  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        transport.OddsApiHistoricalTransport(factory=object())  # type: ignore[call-arg]
    assert set(inspect.signature(transport.OddsApiHistoricalTransport).parameters) == {
        "timeouts"
    }


def test_transport_instance_cannot_shadow_connection_boundary() -> None:
    instance = transport.OddsApiHistoricalTransport()
    assert not hasattr(instance, "__dict__")
    assert not hasattr(instance, "_new_connection")
    with pytest.raises((AttributeError, FrozenInstanceError, TypeError)):
        instance._new_connection = object()  # type: ignore[attr-defined]


def test_timeout_configuration_is_structurally_immutable() -> None:
    instance = transport.OddsApiHistoricalTransport()
    with pytest.raises(FrozenInstanceError):
        instance.timeouts = transport.TransportTimeouts(11, 31)
    with pytest.raises(FrozenInstanceError):
        instance.timeouts.connect_seconds = 11


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("method", "POST"),
        ("path", "/v4/other"),
        ("query", "markets=spreads"),
        ("query", "apiKey=secret"),
        ("canonical_sha256", "0" * 64),
    ],
)
def test_request_cannot_change_endpoint_or_frozen_semantics(
    provider_request: core.ProviderRequest, field: str, value: str
) -> None:
    with pytest.raises(ValueError):
        transport._validate_request(replace(provider_request, **{field: value}))


def test_verified_tls_context_and_explicit_timeouts(
    monkeypatch: pytest.MonkeyPatch, provider_request: core.ProviderRequest
) -> None:
    connection = FakeConnection()
    instance, contexts = prepared(monkeypatch, connection)
    prepared_connection = instance.prepare()
    assert contexts[0].verify_mode == ssl.CERT_REQUIRED
    assert contexts[0].check_hostname is True
    assert connection.sock.timeout == 30.0
    assert connection.target is None
    assert connection.headers == []
    assert connection.sent is False
    prepared_connection.send(provider_request, core.SecretCredential(SECRET))
    assert instance.identity_payload["connect_timeout_seconds"] == 10.0
    assert instance.identity_payload["read_timeout_seconds"] == 30.0


def test_prepare_api_has_no_credential_or_combined_send_shortcut() -> None:
    instance = transport.OddsApiHistoricalTransport()
    assert list(inspect.signature(instance.prepare).parameters) == []
    assert not hasattr(instance, "begin")


def test_prepared_connection_is_externally_immutable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = FakeConnection()
    instance, _ = prepared(monkeypatch, connection)
    prepared_connection = instance.prepare()
    assert not hasattr(prepared_connection, "__dict__")
    with pytest.raises((AttributeError, TypeError)):
        prepared_connection.connection = connection  # type: ignore[attr-defined]


def test_abandoned_prepared_connection_closes_without_http_send(
    monkeypatch: pytest.MonkeyPatch, provider_request: core.ProviderRequest
) -> None:
    connection = FakeConnection()
    instance, _ = prepared(monkeypatch, connection)
    prepared_connection = instance.prepare()
    prepared_connection.close()
    prepared_connection.close()
    assert connection.connected is True
    assert connection.closed is True
    assert connection.putrequest_calls == 0
    assert connection.headers == []
    assert connection.sent is False
    with pytest.raises(RuntimeError, match="no longer available"):
        prepared_connection.send(provider_request, core.SecretCredential(SECRET))


def test_prepared_connection_is_single_use(
    monkeypatch: pytest.MonkeyPatch, provider_request: core.ProviderRequest
) -> None:
    connection = FakeConnection()
    instance, _ = prepared(monkeypatch, connection)
    prepared_connection = instance.prepare()
    exchange = prepared_connection.send(
        provider_request, core.SecretCredential(SECRET)
    )
    with pytest.raises(RuntimeError, match="no longer available"):
        prepared_connection.send(provider_request, core.SecretCredential(SECRET))
    assert connection.putrequest_calls == 1
    exchange.receive()


@pytest.mark.parametrize("authorization_active", [True, False])
def test_post_prepare_live_gate_contract(
    monkeypatch: pytest.MonkeyPatch,
    provider_request: core.ProviderRequest,
    authorization_active: bool,
) -> None:
    connection = FakeConnection()
    instance, _ = prepared(monkeypatch, connection)
    prepared_connection = instance.prepare()

    if authorization_active:
        prepared_connection.send(
            provider_request, core.SecretCredential(SECRET)
        ).receive()
        assert connection.putrequest_calls == 1
        assert connection.sent is True
    else:
        prepared_connection.close()
        assert connection.putrequest_calls == 0
        assert connection.headers == []
        assert connection.sent is False


def test_request_validation_precedes_local_http_buffering(
    monkeypatch: pytest.MonkeyPatch, provider_request: core.ProviderRequest
) -> None:
    connection = FakeConnection()
    instance, _ = prepared(monkeypatch, connection)
    prepared_connection = instance.prepare()
    invalid = replace(provider_request, path="/v4/other")
    with pytest.raises(ValueError, match="endpoint mismatch"):
        prepared_connection.send(invalid, core.SecretCredential(SECRET))
    assert connection.putrequest_calls == 0
    assert connection.headers == []
    assert connection.sent is False
    assert connection.closed is True


@pytest.mark.parametrize("value", [0, -1, 121, float("inf"), float("nan")])
def test_invalid_timeouts_rejected(value: float) -> None:
    with pytest.raises(ValueError):
        transport.TransportTimeouts(connect_seconds=value)


def test_timeout_change_changes_transport_identity() -> None:
    first = transport.OddsApiHistoricalTransport()
    second = transport.OddsApiHistoricalTransport(
        timeouts=transport.TransportTimeouts(11, 31)
    )
    assert first.runtime_identity == first.runtime_identity
    assert first.runtime_identity != second.runtime_identity


@pytest.mark.parametrize(
    ("error", "kind"),
    [
        (socket.gaierror("synthetic DNS"), core.PreSendFailureKind.DNS),
        (ConnectionRefusedError("synthetic connect"), core.PreSendFailureKind.CONNECT),
        (ssl.SSLError("synthetic TLS"), core.PreSendFailureKind.TLS),
        (socket.timeout("synthetic timeout"), core.PreSendFailureKind.CONNECT),
    ],
)
def test_connection_failures_are_provably_pre_send(
    monkeypatch: pytest.MonkeyPatch,
    provider_request: core.ProviderRequest,
    error: BaseException,
    kind: core.PreSendFailureKind,
) -> None:
    instance, _ = prepared(monkeypatch, FakeConnection(connect_error=error))
    with pytest.raises(core.ProvablePreSendFailure) as caught:
        instance.prepare()
    assert caught.value.kind is kind
    assert SECRET not in str(caught.value)


def test_local_buffer_failure_is_pre_send(
    monkeypatch: pytest.MonkeyPatch, provider_request: core.ProviderRequest
) -> None:
    connection = FakeConnection(buffer_error=ValueError("synthetic local failure"))
    instance, _ = prepared(monkeypatch, connection)
    prepared_connection = instance.prepare()
    with pytest.raises(core.ProvablePreSendFailure):
        prepared_connection.send(provider_request, core.SecretCredential(SECRET))
    assert connection.sent is False


def test_failure_when_transmission_may_begin_is_ambiguous(
    monkeypatch: pytest.MonkeyPatch, provider_request: core.ProviderRequest
) -> None:
    connection = FakeConnection(send_error=BrokenPipeError("synthetic send"))
    instance, _ = prepared(monkeypatch, connection)
    prepared_connection = instance.prepare()
    with pytest.raises(core.PossibleSendFailure) as caught:
        prepared_connection.send(provider_request, core.SecretCredential(SECRET))
    assert caught.value.kind is core.ReceiveFailureKind.POSSIBLE_SEND
    assert connection.sent is True


@pytest.mark.parametrize(
    ("error", "kind"),
    [
        (ConnectionResetError("synthetic reset"), core.ReceiveFailureKind.RESET_AFTER_SEND),
        (socket.timeout("synthetic read timeout"), core.ReceiveFailureKind.POSSIBLE_SEND),
        (
            http.client.IncompleteRead(b"partial", 10),
            core.ReceiveFailureKind.PARTIAL_RESPONSE,
        ),
    ],
)
def test_post_send_receive_failures_are_conservative(
    monkeypatch: pytest.MonkeyPatch,
    provider_request: core.ProviderRequest,
    error: BaseException,
    kind: core.ReceiveFailureKind,
) -> None:
    connection = FakeConnection(receive_error=error)
    instance, _ = prepared(monkeypatch, connection)
    exchange = instance.prepare().send(
        provider_request, core.SecretCredential(SECRET)
    )
    with pytest.raises(core.PossibleSendFailure) as caught:
        exchange.receive()
    assert caught.value.kind is kind


@pytest.mark.parametrize("status", [200, 204, 301, 302, 307, 308, 400, 408, 429, 500, 599])
def test_status_is_returned_unchanged_and_redirect_never_followed(
    monkeypatch: pytest.MonkeyPatch,
    provider_request: core.ProviderRequest,
    status: int,
) -> None:
    connection = FakeConnection(response=FakeResponse(status=status))
    instance, _ = prepared(monkeypatch, connection)
    response = instance.prepare().send(
        provider_request, core.SecretCredential(SECRET)
    ).receive()
    assert response.status_code == status
    assert connection.closed is True


def test_raw_headers_and_semantic_headers_are_retained(
    monkeypatch: pytest.MonkeyPatch, provider_request: core.ProviderRequest
) -> None:
    raw = [
        ("Date", "Thu, 01 Oct 2026 12:00:00 GMT"),
        ("Content-Type", "application/json"),
        ("Content-Encoding", "identity"),
        ("X-Requests-Used", "10"),
        ("x-requests-remaining", "90"),
        ("X-Requests-Last", "10"),
        ("X-Duplicate", "one"),
        ("X-Duplicate", "two"),
    ]
    connection = FakeConnection(response=FakeResponse(headers=raw))
    instance, _ = prepared(monkeypatch, connection)
    response = instance.prepare().send(
        provider_request, core.SecretCredential(SECRET)
    ).receive()
    assert response.headers.raw_items == tuple(raw)
    assert response.headers["date"] == raw[0][1]
    assert response.headers["CONTENT-TYPE"] == "application/json"
    assert response.headers["x-requests-used"] == "10"
    assert response.headers["X-REQUESTS-REMAINING"] == "90"
    assert response.headers["x-requests-last"] == "10"
    assert response.headers["x-duplicate"] == "one, two"


@pytest.mark.parametrize(
    ("encoding", "encode"),
    [
        ("identity", lambda value: value),
        ("gzip", gzip.compress),
        ("deflate", zlib.compress),
    ],
)
def test_transport_retains_content_encoded_entity_bytes_for_frozen_core(
    monkeypatch: pytest.MonkeyPatch,
    provider_request: core.ProviderRequest,
    encoding: str,
    encode: object,
) -> None:
    entity = b"\x00synthetic-json-bytes\xff"
    encoded = encode(entity)  # type: ignore[operator]
    connection = FakeConnection(
        response=FakeResponse(headers=[("Content-Encoding", encoding)], body=encoded)
    )
    instance, _ = prepared(monkeypatch, connection)
    response = instance.prepare().send(
        provider_request, core.SecretCredential(SECRET)
    ).receive()
    assert response.body == encoded
    assert response.headers["content-encoding"] == encoding
    assert response.content_decoding == "NOT_PERFORMED_CONTENT_ENCODING_RETAINED"
    assert response.transfer_decoding == transport.TRANSFER_DECODING_NONE
    assert core.decode_application_body(response) == entity


@pytest.mark.parametrize(
    ("encoding", "body", "core_error"),
    [
        ("br", b"opaque", "unsupported"),
        ("gzip", b"not-gzip", "undecodable"),
        ("deflate", b"not-deflate", "undecodable"),
    ],
)
def test_complete_unsupported_or_invalid_content_encoding_is_returned(
    monkeypatch: pytest.MonkeyPatch,
    provider_request: core.ProviderRequest,
    encoding: str,
    body: bytes,
    core_error: str,
) -> None:
    connection = FakeConnection(
        response=FakeResponse(headers=[("Content-Encoding", encoding)], body=body)
    )
    instance, _ = prepared(monkeypatch, connection)
    response = instance.prepare().send(
        provider_request, core.SecretCredential(SECRET)
    ).receive()
    assert response.body == body
    assert response.headers["content-encoding"] == encoding
    assert response.content_decoding == "NOT_PERFORMED_CONTENT_ENCODING_RETAINED"
    with pytest.raises(core.TerminalPilotError, match=core_error):
        core.decode_application_body(response)


@pytest.mark.parametrize(
    ("headers", "chunked", "expected"),
    [
        ([], False, transport.TRANSFER_DECODING_NONE),
        (
            [("Transfer-Encoding", "chunked")],
            True,
            transport.TRANSFER_DECODING_CHUNKED,
        ),
        (
            [("transfer-encoding", "CHUNKED")],
            True,
            transport.TRANSFER_DECODING_CHUNKED,
        ),
    ],
)
def test_supported_transfer_framing_metadata(
    monkeypatch: pytest.MonkeyPatch,
    provider_request: core.ProviderRequest,
    headers: list[tuple[str, str]],
    chunked: bool,
    expected: str,
) -> None:
    entity = b"stdlib-already-returned-entity"
    connection = FakeConnection(
        response=FakeResponse(headers=headers, body=entity, chunked=chunked)
    )
    instance, _ = prepared(monkeypatch, connection)
    response = instance.prepare().send(
        provider_request, core.SecretCredential(SECRET)
    ).receive()
    assert response.body == entity
    assert response.transfer_decoding == expected
    assert response.headers.raw_items == tuple(headers)


@pytest.mark.parametrize(
    ("headers", "chunked"),
    [
        ([("Transfer-Encoding", "gzip")], False),
        ([("Transfer-Encoding", "deflate")], False),
        ([("Transfer-Encoding", "gzip, chunked")], False),
        ([("Transfer-Encoding", "chunked, gzip")], False),
        ([("Transfer-Encoding", "chunked")], False),
        ([], True),
        (
            [("Transfer-Encoding", "chunked"), ("Transfer-Encoding", "gzip")],
            False,
        ),
        (
            [("Transfer-Encoding", "chunked"), ("Transfer-Encoding", "chunked")],
            False,
        ),
    ],
)
def test_unsupported_or_ambiguous_transfer_framing_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    provider_request: core.ProviderRequest,
    headers: list[tuple[str, str]],
    chunked: bool,
) -> None:
    connection = FakeConnection(
        response=FakeResponse(headers=headers, chunked=chunked)
    )
    instance, _ = prepared(monkeypatch, connection)
    exchange = instance.prepare().send(
        provider_request, core.SecretCredential(SECRET)
    )
    with pytest.raises(core.PossibleSendFailure) as caught:
        exchange.receive()
    assert caught.value.kind is core.ReceiveFailureKind.PARTIAL_RESPONSE
    assert connection.closed is True


@pytest.mark.parametrize(
    ("raw_response", "expected_chunked", "expected_decoding"),
    [
        (
            b"HTTP/1.1 200 OK\r\nContent-Length: 5\r\n\r\nhello",
            False,
            transport.TRANSFER_DECODING_NONE,
        ),
        (
            b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n"
            b"5\r\nhello\r\n0\r\n\r\n",
            True,
            transport.TRANSFER_DECODING_CHUNKED,
        ),
        (
            b"HTTP/1.1 200 OK\r\nTransfer-Encoding: CHUNKED\r\n\r\n"
            b"5\r\nhello\r\n0\r\n\r\n",
            True,
            transport.TRANSFER_DECODING_CHUNKED,
        ),
    ],
)
def test_real_httpresponse_parser_accepted_transfer_framing(
    monkeypatch: pytest.MonkeyPatch,
    provider_request: core.ProviderRequest,
    raw_response: bytes,
    expected_chunked: bool,
    expected_decoding: str,
) -> None:
    parsed = parsed_http_response(raw_response)
    assert parsed.chunked is expected_chunked
    connection = FakeConnection(response=parsed)
    instance, _ = prepared(monkeypatch, connection)
    response = instance.prepare().send(
        provider_request, core.SecretCredential(SECRET)
    ).receive()
    assert response.body == b"hello"
    assert response.transfer_decoding == expected_decoding
    if response.transfer_decoding == transport.TRANSFER_DECODING_CHUNKED:
        assert parsed.chunked is True


@pytest.mark.parametrize(
    ("raw_response", "expected_chunked"),
    [
        (
            b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked \r\n\r\n"
            b"5\r\nhello\r\n0\r\n\r\n",
            False,
        ),
        (
            b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\t\r\n\r\n"
            b"5\r\nhello\r\n0\r\n\r\n",
            False,
        ),
        (b"HTTP/1.1 200 OK\r\nTransfer-Encoding: gzip\r\n\r\nopaque", False),
        (
            b"HTTP/1.1 200 OK\r\nTransfer-Encoding: gzip, chunked\r\n\r\n"
            b"5\r\nhello\r\n0\r\n\r\n",
            False,
        ),
        (
            b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n"
            b"Transfer-Encoding: chunked\r\n\r\n5\r\nhello\r\n0\r\n\r\n",
            True,
        ),
    ],
)
def test_real_httpresponse_parser_rejects_unmatched_transfer_framing(
    monkeypatch: pytest.MonkeyPatch,
    provider_request: core.ProviderRequest,
    raw_response: bytes,
    expected_chunked: bool,
) -> None:
    parsed = parsed_http_response(raw_response)
    assert parsed.chunked is expected_chunked
    connection = FakeConnection(response=parsed)
    instance, _ = prepared(monkeypatch, connection)
    exchange = instance.prepare().send(
        provider_request, core.SecretCredential(SECRET)
    )
    with pytest.raises(core.PossibleSendFailure) as caught:
        exchange.receive()
    assert caught.value.kind is core.ReceiveFailureKind.PARTIAL_RESPONSE
    assert connection.closed is True


def test_credential_is_added_only_at_final_boundary_and_not_retained(
    monkeypatch: pytest.MonkeyPatch, provider_request: core.ProviderRequest
) -> None:
    connection = FakeConnection()
    instance, _ = prepared(monkeypatch, connection)
    assert SECRET.encode() not in provider_request.canonical_bytes
    assert "apikey" not in provider_request.query.lower()
    prepared_connection = instance.prepare()
    assert connection.target is None
    assert SECRET not in repr(prepared_connection)
    prepared_connection.send(provider_request, core.SecretCredential(SECRET))
    assert connection.target is not None and f"apiKey={SECRET}" in connection.target
    assert SECRET not in provider_request.redacted_as_sent_url
    assert "apiKey=%5BREDACTED%5D" in provider_request.redacted_as_sent_url
    assert not hasattr(instance, "__dict__")
    assert SECRET not in repr(instance)


def test_exception_text_never_contains_credential(
    monkeypatch: pytest.MonkeyPatch, provider_request: core.ProviderRequest
) -> None:
    connection = FakeConnection(send_error=BrokenPipeError(SECRET))
    instance, _ = prepared(monkeypatch, connection)
    prepared_connection = instance.prepare()
    with pytest.raises(core.PossibleSendFailure) as caught:
        prepared_connection.send(provider_request, core.SecretCredential(SECRET))
    assert SECRET not in str(caught.value)
    assert SECRET not in repr(caught.value)
    assert caught.value.__cause__ is None


def test_credential_echo_remains_detectable_by_core(
    monkeypatch: pytest.MonkeyPatch, provider_request: core.ProviderRequest
) -> None:
    connection = FakeConnection(response=FakeResponse(body=SECRET.encode()))
    instance, _ = prepared(monkeypatch, connection)
    response = instance.prepare().send(
        provider_request, core.SecretCredential(SECRET)
    ).receive()
    assert core._response_contains_secret(  # noqa: SLF001 - reviewed integration probe
        response, response.body, core.SecretCredential(SECRET)
    )


def test_proxy_environment_cannot_change_destination(
    monkeypatch: pytest.MonkeyPatch, provider_request: core.ProviderRequest
) -> None:
    monkeypatch.setenv("HTTPS_PROXY", "http://synthetic-proxy.invalid:9999")
    monkeypatch.setenv("ALL_PROXY", "socks5://synthetic-proxy.invalid:9999")
    connection = FakeConnection()
    instance, _ = prepared(monkeypatch, connection)
    instance.prepare().send(provider_request, core.SecretCredential(SECRET))
    assert instance.identity_payload["proxy_policy"] == "AMBIENT_PROXY_DISABLED"
    assert instance.identity_payload["host"] == transport.PROVIDER_HOST


def test_network_kill_switch_remains_armed_without_socket_use(
    monkeypatch: pytest.MonkeyPatch, provider_request: core.ProviderRequest
) -> None:
    connection = FakeConnection()
    instance, _ = prepared(monkeypatch, connection)
    response = instance.prepare().send(
        provider_request, core.SecretCredential(SECRET)
    ).receive()
    assert response.status_code == 200


def test_network_kill_switch_blocks_unmocked_prepare() -> None:
    instance = transport.OddsApiHistoricalTransport()
    with pytest.raises(AssertionError, match="real socket/DNS use is prohibited"):
        instance.prepare()


def test_transport_identity_pins_source_and_policy() -> None:
    instance = transport.OddsApiHistoricalTransport()
    payload = instance.identity_payload
    assert payload["module_sha256"] == transport._digest(  # noqa: SLF001
        Path(transport.__file__).read_bytes()
    )
    assert payload["tls_policy"] == transport.TLS_POLICY
    assert payload["redirect_policy"] == transport.REDIRECT_POLICY
    assert payload["proxy_policy"] == transport.PROXY_POLICY
    assert payload["content_decoding_policy"] == transport.CONTENT_DECODING_POLICY
    assert payload["send_gate_policy"] == transport.SEND_GATE_POLICY
    assert payload["send_gate_policy"] == "PREPARE_THEN_REVALIDATE_THEN_SEND"
    assert payload["transfer_framing_policy"] == transport.TRANSFER_FRAMING_POLICY
    assert transport.TRANSPORT_IMPLEMENTATION_ID in instance.runtime_identity


def test_exchange_close_after_send_is_idempotent_and_sends_nothing_more(
    monkeypatch: pytest.MonkeyPatch, provider_request: core.ProviderRequest
) -> None:
    connection = FakeConnection()
    instance, _ = prepared(monkeypatch, connection)
    exchange = instance.prepare().send(
        provider_request, core.SecretCredential(SECRET)
    )
    assert connection.putrequest_calls == 1
    assert connection.sent is True
    exchange.close()
    exchange.close()
    assert connection.closed is True
    assert connection.close_calls == 1
    assert connection.putrequest_calls == 1
    with pytest.raises(core.PossibleSendFailure):
        exchange.receive()


def test_receive_then_exchange_close_is_harmless(
    monkeypatch: pytest.MonkeyPatch, provider_request: core.ProviderRequest
) -> None:
    connection = FakeConnection()
    instance, _ = prepared(monkeypatch, connection)
    exchange = instance.prepare().send(
        provider_request, core.SecretCredential(SECRET)
    )
    exchange.receive()
    assert connection.close_calls == 1
    exchange.close()
    assert connection.close_calls == 1


def test_receive_failure_then_exchange_close_is_harmless(
    monkeypatch: pytest.MonkeyPatch, provider_request: core.ProviderRequest
) -> None:
    connection = FakeConnection(receive_error=ConnectionResetError("synthetic"))
    instance, _ = prepared(monkeypatch, connection)
    exchange = instance.prepare().send(
        provider_request, core.SecretCredential(SECRET)
    )
    with pytest.raises(core.PossibleSendFailure):
        exchange.receive()
    assert connection.close_calls == 1
    exchange.close()
    assert connection.close_calls == 1


def test_second_receive_is_rejected_as_post_send_ambiguity(
    monkeypatch: pytest.MonkeyPatch, provider_request: core.ProviderRequest
) -> None:
    connection = FakeConnection()
    instance, _ = prepared(monkeypatch, connection)
    exchange = instance.prepare().send(
        provider_request, core.SecretCredential(SECRET)
    )
    exchange.receive()
    with pytest.raises(core.PossibleSendFailure):
        exchange.receive()


def test_no_ambient_credential_lookup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ODDS_API_KEY", "UNUSED_AMBIENT_SECRET")
    instance = transport.OddsApiHistoricalTransport()
    serialized = json.dumps(instance.identity_payload, sort_keys=True)
    assert "UNUSED_AMBIENT_SECRET" not in serialized
