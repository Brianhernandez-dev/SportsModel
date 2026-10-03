"""Dormant, review-only HTTPS transport for the frozen NFL historical pilot.

The module contains future network capability but has no CLI, credential lookup,
authorization, or executor integration.  Tests replace the connection boundary
before it can create a socket.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from hashlib import sha256
import http.client
import json
from pathlib import Path
import re
import socket
import ssl
from types import MappingProxyType
from typing import Any
from urllib.parse import quote

from sportsmodel.nfl.historical_market_pilot import (
    PossibleSendFailure,
    ProviderRequest,
    ProvablePreSendFailure,
    PreSendFailureKind,
    ReceiveFailureKind,
    SecretCredential,
)


TRANSPORT_IMPLEMENTATION_ID = "nfl_historical_market_odds_api_transport_0.1.3"
PROVIDER_SCHEME = "https"
PROVIDER_HOST = "api.the-odds-api.com"
PROVIDER_PORT = 443
PROVIDER_PATH = "/v4/historical/sports/americanfootball_nfl/odds"
PROXY_POLICY = "AMBIENT_PROXY_DISABLED"
REDIRECT_POLICY = "RETURN_3XX_NEVER_FOLLOW"
TLS_POLICY = "SYSTEM_TRUST_CERT_REQUIRED_HOSTNAME_REQUIRED"
CONTENT_DECODING_POLICY = "FROZEN_EXECUTOR_DECODE_APPLICATION_BODY"
SEND_GATE_POLICY = "PREPARE_THEN_REVALIDATE_THEN_SEND"
TRANSFER_FRAMING_POLICY = "RAW_EXACT_AND_HTTP_RESPONSE_CHUNKED_AGREEMENT"
TRANSFER_DECODING_NONE = "HTTP_CLIENT_NO_TRANSFER_CODING"
TRANSFER_DECODING_CHUNKED = "STDLIB_HTTP_CLIENT_CHUNKED_DECODED"
_QUERY = re.compile(
    r"bookmakers=draftkings%2Cfanduel%2Cbetmgm%2Cbetrivers"
    r"&date=\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z"
    r"&markets=h2h&oddsFormat=decimal"
)


def _canonical_json(value: Mapping[str, Any]) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _digest(value: bytes) -> str:
    return sha256(value).hexdigest().upper()


@dataclass(frozen=True, slots=True)
class TransportTimeouts:
    connect_seconds: float = 10.0
    read_seconds: float = 30.0

    def __post_init__(self) -> None:
        for value in (self.connect_seconds, self.read_seconds):
            if not isinstance(value, (int, float)) or not 0 < float(value) <= 120:
                raise ValueError("transport timeout must be within (0, 120] seconds")


@dataclass(frozen=True, slots=True, init=False)
class RawHeaders(Mapping[str, str]):
    """Case-insensitive semantic lookup with an immutable raw ordered record."""

    raw_items: tuple[tuple[str, str], ...]
    _values: Mapping[str, str]
    _display: Mapping[str, str]
    _raw_values: Mapping[str, tuple[str, ...]]

    def __init__(self, items: list[tuple[str, str]]):
        raw_items = tuple((str(name), str(value)) for name, value in items)
        combined: dict[str, list[str]] = {}
        display: dict[str, str] = {}
        for name, value in raw_items:
            key = name.lower()
            combined.setdefault(key, []).append(value)
            display.setdefault(key, name)
        object.__setattr__(self, "raw_items", raw_items)
        object.__setattr__(
            self,
            "_values",
            MappingProxyType(
                {key: ", ".join(values) for key, values in combined.items()}
            ),
        )
        object.__setattr__(self, "_display", MappingProxyType(display))
        object.__setattr__(
            self,
            "_raw_values",
            MappingProxyType({key: tuple(values) for key, values in combined.items()}),
        )

    def __getitem__(self, key: str) -> str:
        return self._values[key.lower()]

    def __iter__(self) -> Iterator[str]:
        return iter(self._display.values())

    def __len__(self) -> int:
        return len(self._values)

    def get(self, key: str, default: str | None = None) -> str | None:
        return self._values.get(key.lower(), default)

    def get_all(self, key: str) -> tuple[str, ...]:
        return self._raw_values.get(key.lower(), ())


@dataclass(frozen=True, slots=True)
class OddsApiTransportResponse:
    status_code: int
    headers: RawHeaders
    body: bytes
    transfer_decoding: str
    content_decoding: str


def _transfer_decoding(
    headers: RawHeaders, *, response_chunked: bool
) -> str:
    values = headers.get_all("transfer-encoding")
    if not values:
        if response_chunked is False:
            return TRANSFER_DECODING_NONE
        raise PossibleSendFailure(ReceiveFailureKind.PARTIAL_RESPONSE)
    if (
        len(values) == 1
        and values[0].lower() == "chunked"
        and response_chunked is True
    ):
        return TRANSFER_DECODING_CHUNKED
    raise PossibleSendFailure(ReceiveFailureKind.PARTIAL_RESPONSE)


class _OddsApiExchange:
    def __init__(self, connection: http.client.HTTPSConnection):
        self._connection = connection
        self._used = False
        self._closed = False

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            _close_quietly(self._connection)

    def receive(self) -> OddsApiTransportResponse:
        if self._used or self._closed:
            raise PossibleSendFailure(ReceiveFailureKind.POSSIBLE_SEND)
        self._used = True
        try:
            response = self._connection.getresponse()
            status = int(response.status)
            headers = RawHeaders(list(response.getheaders()))
            transfer_decoding = _transfer_decoding(
                headers, response_chunked=response.chunked
            )
            body = response.read()
        except http.client.IncompleteRead:
            raise PossibleSendFailure(ReceiveFailureKind.PARTIAL_RESPONSE) from None
        except (socket.timeout, TimeoutError):
            raise PossibleSendFailure(ReceiveFailureKind.POSSIBLE_SEND) from None
        except (ConnectionResetError, BrokenPipeError):
            raise PossibleSendFailure(ReceiveFailureKind.RESET_AFTER_SEND) from None
        except (OSError, http.client.HTTPException):
            raise PossibleSendFailure(ReceiveFailureKind.POSSIBLE_SEND) from None
        finally:
            self.close()
        return OddsApiTransportResponse(
            status_code=status,
            headers=headers,
            body=body,
            transfer_decoding=transfer_decoding,
            content_decoding="NOT_PERFORMED_CONTENT_ENCODING_RETAINED",
        )


def _close_quietly(connection: http.client.HTTPSConnection) -> None:
    try:
        connection.close()
    except OSError:
        pass


class _PreparedOddsApiConnection:
    """Externally immutable, single-use connection prepared before a live gate."""

    __slots__ = ("__connection", "__state")

    def __init__(self, connection: http.client.HTTPSConnection):
        object.__setattr__(self, "_PreparedOddsApiConnection__connection", connection)
        object.__setattr__(self, "_PreparedOddsApiConnection__state", "PREPARED")

    def __setattr__(self, _name: str, _value: object) -> None:
        raise AttributeError("prepared connection is immutable")

    def close(self) -> None:
        if self.__state == "PREPARED":
            object.__setattr__(self, "_PreparedOddsApiConnection__state", "CLOSED")
            _close_quietly(self.__connection)

    def send(
        self, request: ProviderRequest, credential: SecretCredential
    ) -> _OddsApiExchange:
        if self.__state != "PREPARED":
            raise RuntimeError("prepared connection is no longer available")
        object.__setattr__(self, "_PreparedOddsApiConnection__state", "CONSUMED")
        try:
            _validate_request(request)
        except (TypeError, ValueError):
            _close_quietly(self.__connection)
            raise
        target = (
            f"{request.path}?{request.query}"
            f"&apiKey={quote(credential.value, safe='')}"
        )
        try:
            self.__connection.putrequest(
                "GET", target, skip_host=True, skip_accept_encoding=True
            )
            self.__connection.putheader("Host", PROVIDER_HOST)
            self.__connection.putheader("Accept", "application/json")
            self.__connection.putheader("Accept-Encoding", "gzip, deflate")
        except (OSError, http.client.HTTPException, ValueError):
            _close_quietly(self.__connection)
            raise ProvablePreSendFailure(PreSendFailureKind.CONNECT) from None
        try:
            self.__connection.endheaders()
        except (OSError, http.client.HTTPException):
            _close_quietly(self.__connection)
            raise PossibleSendFailure(ReceiveFailureKind.POSSIBLE_SEND) from None
        return _OddsApiExchange(self.__connection)


@dataclass(frozen=True, slots=True)
class OddsApiHistoricalTransport:
    """Pinned HTTPS transport with no ambient credential or proxy discovery."""

    timeouts: TransportTimeouts = field(default_factory=TransportTimeouts)

    @property
    def identity_payload(self) -> dict[str, Any]:
        return {
            "connect_timeout_seconds": float(self.timeouts.connect_seconds),
            "content_decoding_policy": CONTENT_DECODING_POLICY,
            "host": PROVIDER_HOST,
            "implementation": TRANSPORT_IMPLEMENTATION_ID,
            "module_sha256": _digest(Path(__file__).read_bytes()),
            "port": PROVIDER_PORT,
            "proxy_policy": PROXY_POLICY,
            "read_timeout_seconds": float(self.timeouts.read_seconds),
            "redirect_policy": REDIRECT_POLICY,
            "scheme": PROVIDER_SCHEME,
            "send_gate_policy": SEND_GATE_POLICY,
            "tls_policy": TLS_POLICY,
            "transfer_framing_policy": TRANSFER_FRAMING_POLICY,
        }

    @property
    def runtime_identity(self) -> str:
        return f"{TRANSPORT_IMPLEMENTATION_ID}:{_digest(_canonical_json(self.identity_payload))}"

    def prepare(self) -> _PreparedOddsApiConnection:
        context = ssl.create_default_context()
        if not context.check_hostname or context.verify_mode != ssl.CERT_REQUIRED:
            raise RuntimeError("verified TLS context is unavailable")
        connection = http.client.HTTPSConnection(
            PROVIDER_HOST,
            port=PROVIDER_PORT,
            timeout=float(self.timeouts.connect_seconds),
            context=context,
        )
        try:
            connection.connect()
            if connection.sock is None:
                raise ConnectionError("connection socket is unavailable")
            connection.sock.settimeout(float(self.timeouts.read_seconds))
        except socket.gaierror:
            _close_quietly(connection)
            raise ProvablePreSendFailure(PreSendFailureKind.DNS) from None
        except ssl.SSLError:
            _close_quietly(connection)
            raise ProvablePreSendFailure(PreSendFailureKind.TLS) from None
        except (socket.timeout, TimeoutError, ConnectionRefusedError, OSError):
            _close_quietly(connection)
            raise ProvablePreSendFailure(PreSendFailureKind.CONNECT) from None
        return _PreparedOddsApiConnection(connection)


def _validate_request(request: ProviderRequest) -> None:
    if type(request) is not ProviderRequest:
        raise ValueError("reviewed provider request type is required")
    if request.method != "GET" or request.path != PROVIDER_PATH:
        raise ValueError("provider request endpoint mismatch")
    if not _QUERY.fullmatch(request.query):
        raise ValueError("provider request query mismatch")
    if "apikey" in request.query.lower() or b"apikey" in request.canonical_bytes.lower():
        raise ValueError("canonical request must remain credential-free")
    expected = f"GET\n{PROVIDER_PATH}\n{request.query}".encode()
    if request.canonical_bytes != expected or request.canonical_sha256 != _digest(expected):
        raise ValueError("canonical request identity mismatch")
