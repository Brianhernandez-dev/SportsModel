# NFL Historical-Market Odds API Transport 0.1.0

Status: **IMPLEMENTATION CANDIDATE — REAL NETWORK EXECUTION NOT AUTHORIZED**

## Scope and relationship to the offline executor

`nfl_historical_market_odds_api_transport_0.1.0` is a dormant HTTPS transport
candidate for the frozen NFL historical featured-market pilot. It consumes the
validated `ProviderRequest` and explicitly injected `SecretCredential` types
from the pristine offline executor 0.1.4 candidate.

It has no CLI, scheduler, ambient credential lookup, authorization artifact,
database access, or production entry point. Offline executor 0.1.4 still rejects
every transport except its exact deterministic fake. No real network request was
made while implementing or testing this candidate.

## Endpoint boundary

The destination is compile-time pinned to:

- scheme: `https`;
- host: `api.the-odds-api.com`;
- port: `443`;
- path: `/v4/historical/sports/americanfootball_nfl/odds`.

The constructor exposes no host, scheme, port, TLS-verification, redirect, or
proxy override. The request validator requires the exact secret-free canonical
NFL query: `americanfootball_nfl`, `h2h`, decimal odds, the frozen DraftKings /
FanDuel / BetMGM / BetRivers set, and the frozen historical timestamp. It cannot
select a target or substitute another request.

## TLS, redirect, proxy, and timeout policy

The transport uses `ssl.create_default_context()` and verifies at runtime that
certificate verification is `CERT_REQUIRED` and hostname verification is
enabled. There is no insecure or trust-all option and no HTTP downgrade.

It uses `http.client.HTTPSConnection` directly with the pinned host. No redirect
code exists; every 3xx response is returned unchanged. Ambient proxy variables
are never consulted. Connect and read timeouts are explicit, positive, bounded
to 120 seconds, and included in transport identity. Defaults are 10 seconds to
connect and 30 seconds to read.

## Credential boundary

The transport accepts only an explicitly supplied reviewed `SecretCredential`.
It does not inspect environment variables, `.env`, registry, credential manager,
or configuration files. The canonical request and its hash remain secret-free.
The key is URL-encoded and appended only when the pinned HTTP request target is
handed to the connection. Retained redacted request evidence continues to use
`apiKey=%5BREDACTED%5D`.

Transport exceptions suppress underlying exception chaining so provider or
socket messages cannot surface credential-bearing request text.

## Send-boundary state model

1. Validate the frozen request with no socket activity.
2. Create the verified TLS context and pinned HTTPS connection.
3. Complete DNS, TCP connection, and TLS handshake before any HTTP request bytes.
   DNS, connection, or TLS failure here is classified as the corresponding
   `ProvablePreSendFailure`.
4. Buffer the request line and headers locally. A local buffering failure is
   classified conservatively as pre-send.
5. Enter possible-send state immediately before `endheaders()`, the first call
   that may hand request bytes to the network stack. Any failure from that point
   is a `PossibleSendFailure`.
6. Connection reset, read timeout, partial response, and other response failures
   remain possible/ambiguous send outcomes. Retry policy remains executor-owned.

## Response and content-encoding boundary

Python `http.client` removes HTTP transfer framing. The transport then retains
the ordered raw response-header pairs in an immutable case-insensitive mapping
and reads bytes without text decoding. It supports only identity, gzip, and
deflate content encoding. The returned `body` is the exact application-visible
entity after that explicitly recorded content decode and before JSON parsing or
normalization. Unsupported or corrupt content encoding fails closed as a
post-send partial-response condition.

Status, Date, Content-Type, Content-Encoding, quota headers, duplicate raw
headers, transfer-decoding identity, content-decoding identity, and entity bytes
remain available to the future integration layer.

## Transport identity

The deterministic runtime identity hashes a canonical payload containing:

- transport implementation version and module SHA-256;
- scheme, host, and port;
- verified-TLS policy;
- never-follow redirect policy;
- ambient-proxy-disabled policy;
- connect and read timeouts; and
- supported content encodings.

Changing the module or pinned configuration changes the identity.

## Tests and network isolation

The transport suite uses deterministic fake connection/response objects. An
autouse kill-switch replaces socket construction, DNS lookup, and connection
helpers with immediate failures. Coverage includes endpoint pinning, TLS,
redirects, proxies, timeouts, failure classification, status families, raw and
semantic headers, quota metadata, exact entity bytes, encoding failures,
credential redaction, deterministic identity, and accidental-network denial.

No provider DNS lookup, socket connection, request, credential, or credit was
used.

## Integration state

Integration is deliberately unimplemented. The pristine offline executor 0.1.4
requires the exact deterministic fake transport and its existing response path
performs content decoding. A future independently reviewed core revision must
authorize this exact transport identity and accept its already content-decoded
entity body without double decoding while retaining raw Content-Encoding
evidence. The minimum change is specified separately in the integration plan.
