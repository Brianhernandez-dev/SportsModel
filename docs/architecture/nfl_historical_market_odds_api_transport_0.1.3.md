# NFL Historical-Market Odds API Transport 0.1.3

Status: **IMPLEMENTATION CANDIDATE — REAL NETWORK EXECUTION NOT AUTHORIZED**

## Scope

`nfl_historical_market_odds_api_transport_0.1.3` is a dormant HTTPS transport
candidate. This revision is limited to exact agreement between raw
Transfer-Encoding evidence and Python's actual response-parser state, plus an
idempotent exchange cleanup API. It is not integrated with the frozen offline
executor and has no provider execution entry point.

## Transfer-Encoding/parser-state agreement

After `getresponse()`, the transport now examines both the immutable ordered raw
Transfer-Encoding fields and `http.client.HTTPResponse.chunked`:

- with no Transfer-Encoding field, ordinary framing is accepted only when
  `response.chunked is False`;
- one raw value is accepted as chunked only when its exact value compares
  case-insensitively equal to `chunked` without trimming and
  `response.chunked is True`; and
- every duplicate, compound, unsupported, ambiguous, whitespace-altered, or
  raw/parser-mismatched state fails closed as
  `PossibleSendFailure(PARTIAL_RESPONSE)`.

The transport can therefore never report
`STDLIB_HTTP_CLIENT_CHUNKED_DECODED` unless the stdlib parser actually reports a
chunked response. Potentially transfer-coded bytes are not exposed upward as
clean entity bytes after a mismatch.

## Real HTTPResponse parser coverage

The deterministic suite parses complete synthetic HTTP response bytes through
real `http.client.HTTPResponse` objects backed by in-memory fake sockets. It
covers ordinary Content-Length framing, exact lowercase and uppercase chunked
framing with real dechunking, trailing-space and trailing-tab values, gzip,
compound gzip/chunked values, duplicate fields, and deliberate raw/parser-state
mismatches. No operating-system socket or network is used.

## Exchange close API

The exchange now exposes idempotent `close()`. It closes the underlying
connection without sending more bytes, retrying, receiving, or resuming the
exchange. It is safe immediately after send, after successful receive, after a
receive failure, and when called repeatedly. Calling `receive()` continues to
close deterministically in `finally`; a closed exchange cannot later resume.
The exchange stores no credential.

## Preserved boundaries

The production API remains structurally two-phase:
`transport.prepare() → future executor live authorization/window gate →
prepared.send(request, credential)`. Preparation receives no request or
credential and sends no HTTP request bytes. A prepared connection remains
single-use and abortable. Request validation and local buffering remain
pre-send; entering `endheaders()` remains possible send.

Endpoint, verified TLS and hostname policy, redirect prohibition, ambient proxy
and credential isolation, immutable timeouts, and deterministic identity remain
unchanged. Identity advances to 0.1.3 and pins the exact raw-header plus
`HTTPResponse.chunked` agreement policy.

Content-Encoding decoding remains exclusively owned by the frozen executor.
Complete encoded response bytes and raw Content-Encoding headers remain intact.

## Review boundary

Tests retain the socket/DNS kill switch and use only `TEST_KEY_DO_NOT_SEND`. No
provider DNS lookup, socket, request, real credential, purchase, credit,
historical odds, integration, join, model operation, database change,
migration, MLB change, commit, or push is authorized or performed.

The non-blocking LOW/NOTE observations recorded in the 0.1.2 Claude review are
carried forward without expansion.
