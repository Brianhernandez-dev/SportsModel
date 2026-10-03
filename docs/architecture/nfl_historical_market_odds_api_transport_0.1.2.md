# NFL Historical-Market Odds API Transport 0.1.2

Status: **IMPLEMENTATION CANDIDATE — REAL NETWORK EXECUTION NOT AUTHORIZED**

## Scope and two-phase API

`nfl_historical_market_odds_api_transport_0.1.2` is a dormant two-phase HTTPS
transport candidate. It is not integrated with the frozen offline executor and
has no CLI, scheduler, authorization artifact, ambient credential lookup,
database access, or production entry point.

The production API structurally requires:

1. `prepared = transport.prepare()`;
2. a future executor-owned live authorization/window gate; and
3. `exchange = prepared.send(request, credential)`.

There is no combined `begin(request, credential)` or other convenience method
that can silently skip the between-phase gate.

## Prepare phase

`prepare()` receives no request, credential, authorization object, clock, or
caller callback. It uses the compile-time-pinned HTTPS endpoint and verified
system TLS context to perform DNS resolution, TCP connection, TLS handshake,
certificate and hostname verification, and read-timeout configuration.

Preparation does not build a request target or call `putrequest`, `putheader`,
or `endheaders`; therefore it sends zero provider HTTP request bytes. DNS, TLS,
timeout, and other connection failures retain the reviewed provable-pre-send
classification.

The returned prepared object is slotted, externally immutable, single-use, and
contains no credential. It exposes `close()` so a failed post-prepare gate can
discard the connection without HTTP transmission. Closing is idempotent, and a
closed or previously consumed object rejects `send()`.

## Send phase and boundary

`send()` receives the exact frozen `ProviderRequest` and explicit
`SecretCredential`. It atomically consumes the prepared object, validates the
request before constructing the credential-bearing target or buffering HTTP,
then calls `putrequest` and `putheader` locally. Local buffering failures remain
provable pre-send.

Entering `endheaders()` remains the first possible-send boundary. Failure from
that point is possible/ambiguous send. Successful send returns the existing
single-use exchange; reset, timeout, incomplete body, and response failures
retain their conservative post-send classifications. Credential data is not
stored on the transport or prepared object beyond unavoidable standard-library
request-transmission internals.

## Endpoint and policy identity

The endpoint remains pinned to HTTPS, `api.the-odds-api.com:443`, and
`/v4/historical/sports/americanfootball_nfl/odds`. There are no host, port, TLS,
proxy, factory, development, or force overrides. Redirects are never followed,
ambient proxies and credentials are not consulted, and timeout configuration is
frozen and identity-bound.

The runtime identity includes the exact module hash and canonical
`PREPARE_THEN_REVALIDATE_THEN_SEND` policy, plus endpoint, TLS, redirect, proxy,
connect/read timeouts, frozen-executor Content-Encoding ownership, and the
accepted transfer-framing policy.

## DNS timeout limitation

Python's standard `socket.create_connection()` path performs platform
`getaddrinfo()` before applying the socket connect timeout. The configured
`connect_seconds` value therefore does not strictly bound DNS resolution
wall-clock time. This revision does not add threads, subprocesses, custom DNS,
or another resolver. A future executor must revalidate authorization and its
execution window after preparation, so delayed DNS cannot authorize a later
HTTP send.

## Preserved response semantics

The transport still performs no Content-Encoding decode. It returns complete
entity bytes and immutable ordered raw headers, including valid, corrupt, or
unsupported Content-Encoding evidence, for the frozen executor's reviewed
`decode_application_body()` path.

No Transfer-Encoding and one exact case-insensitive `chunked` value remain the
only accepted transfer-framing declarations. Unsupported, compound, duplicate,
or ambiguous values fail closed before potentially coded bytes are exposed as
entity bytes. Transfer-decoding metadata distinguishes ordinary framing from
stdlib-decoded chunked framing.

## Test and execution boundary

Tests replace only the module's standard-library connection symbol and arm an
autouse kill switch for socket construction, connection helpers, and DNS. They
use only `TEST_KEY_DO_NOT_SEND`. The frozen executor source is unchanged.

No provider DNS lookup, socket, request, API key, purchase, credit, historical
odds, pilot execution, integration, join, model operation, database change,
migration, or MLB change is authorized or performed by this candidate.
