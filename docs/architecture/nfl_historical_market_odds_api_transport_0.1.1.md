# NFL Historical-Market Odds API Transport 0.1.1

Status: **IMPLEMENTATION CANDIDATE — REAL NETWORK EXECUTION NOT AUTHORIZED**

## Scope

`nfl_historical_market_odds_api_transport_0.1.1` is a dormant HTTPS transport
candidate for the frozen NFL historical-market pilot. It consumes the frozen
executor's validated `ProviderRequest` and explicitly supplied
`SecretCredential` types, but it has no CLI, scheduler, ambient credential
lookup, authorization artifact, database access, or production entry point.

The frozen offline executor remains unchanged and does not authorize this
transport. No real network operation or provider execution occurred while
developing or validating this candidate.

## Immutable transport identity and configuration

The production transport and timeout configuration are frozen, slotted objects.
They have no instance `__dict__`, connection-factory field, host/TLS/proxy
override, or development/force/test constructor parameter. The production path
constructs the pinned standard-library `HTTPSConnection` directly. Tests obtain
determinism only by monkeypatching that module symbol under an autouse socket and
DNS kill switch; callers receive no injection surface.

Runtime identity hashes the exact module bytes and canonical pinned policy,
including implementation version, endpoint, TLS, redirect and proxy policy,
connect/read timeouts, and the content-decoding ownership boundary. Constructing
a distinct transport with different valid timeouts therefore produces a
different identity.

## Endpoint, TLS, credential, and send boundary

The endpoint remains compile-time pinned to HTTPS,
`api.the-odds-api.com:443`, and
`/v4/historical/sports/americanfootball_nfl/odds`. The exact frozen secret-free
query is required. Verified system trust and hostname validation remain
mandatory; redirects are returned and never followed; ambient proxy and
credential discovery are absent.

DNS, TCP/connect, TLS, and local request-buffering failures remain provable
pre-send failures. `putrequest()` and `putheader()` buffer locally. Entering
`endheaders()` remains the possible-send boundary, and all failures from that
point retain the conservative reviewed post-send classification.

## Transfer-Encoding boundary

Before exposing returned entity bytes, the transport inspects every raw
Transfer-Encoding field:

- no Transfer-Encoding is accepted as ordinary HTTP framing and recorded as
  `HTTP_CLIENT_NO_TRANSFER_CODING`;
- one exact, case-insensitive `chunked` value is accepted because
  `http.client` removes chunk framing, and is recorded as
  `STDLIB_HTTP_CLIENT_CHUNKED_DECODED`; and
- unsupported, compound, duplicate, or ambiguous transfer coding fails closed
  as `PossibleSendFailure(PARTIAL_RESPONSE)`.

The immutable ordered raw headers remain available on accepted responses,
including the raw Transfer-Encoding spelling and value.

## Content-Encoding boundary

The transport performs no gzip, deflate, text, or application decoding. It
returns the complete entity bytes produced by `http.client` after accepted HTTP
framing, preserving the raw Content-Encoding header unchanged. Valid gzip and
deflate remain encoded. Corrupt gzip/deflate and unsupported Content-Encoding
responses are also returned intact when the HTTP response is otherwise
complete; they are not transport-level partial responses.

The response records `NOT_PERFORMED_CONTENT_ENCODING_RETAINED`. The frozen
executor's reviewed `decode_application_body()` remains the sole owner of
Content-Encoding decoding and terminal integrity classification. This boundary
avoids double decoding.

## Validation and isolation

Deterministic tests cover structural immutability, absence of constructor and
instance factory seams, identity changes for intentionally different timeout
configuration, endpoint/TLS/send-state preservation, encoded-byte retention,
frozen-core decoding, corrupt and unsupported content encoding, transfer-coding
validation and metadata, raw headers, and credential redaction. Tests arm a
socket/DNS kill switch and use only `TEST_KEY_DO_NOT_SEND`.

No provider DNS lookup, socket, request, API key, purchase, credit, historical
odds, pilot execution, join, model operation, database change, migration, or MLB
change is authorized or performed by this candidate.
