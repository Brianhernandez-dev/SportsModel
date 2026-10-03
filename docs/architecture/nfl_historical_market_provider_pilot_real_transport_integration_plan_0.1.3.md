# NFL Historical-Market Real-Transport Integration Plan 0.1.3

Status: **DESIGN ONLY — INTEGRATION AND PROVIDER EXECUTION NOT AUTHORIZED**

## Required two-phase sequence

A separately reviewed successor executor must retain the exact sequence:

1. live authorization/window gate;
2. durable attempt reservation;
3. immutable request evidence;
4. repeated live authorization gate;
5. `transport.prepare()` with no request or credential;
6. another live authorization/window gate after preparation;
7. close the prepared connection and terminalize with zero HTTP request bytes if
   that gate fails;
8. otherwise call `prepared.send(request, credential)`;
9. append `SENT` immediately after successful send-boundary completion; and
10. continue the existing receive, evidence, and quota logic.

The successor executor owns authorization and clock semantics. The transport
accepts neither, exposes no callback, and provides no combined prepare/send
shortcut.

## Post-send exchange lifecycle

After `prepared.send()` returns an exchange, the successor executor must
deterministically choose one of two paths:

- call `exchange.receive()`, which closes the connection in `finally`; or
- call `exchange.close()` if authorization or other reviewed terminalization
  occurs after send but before receive.

No exchange may be abandoned to garbage-collection-dependent socket cleanup.
`close()` does not retry, receive, send additional bytes, or resume the exchange.

## Response boundary

The transport admits chunked entity bytes only when exact raw
Transfer-Encoding evidence agrees with `HTTPResponse.chunked is True`.
Duplicate, compound, unsupported, whitespace-altered, ambiguous, and
raw/parser-mismatched states remain conservative post-send failures.

Content-Encoding decoding remains in the frozen executor's reviewed
`decode_application_body()` path. The future integration must preserve ordered
raw headers and transfer-decoding metadata without adding a double-decoding
adapter.

## Identity and future review

Authorization, runtime provenance, run identity, and the evidence manifest must
pin the exact concrete transport type, 0.1.3 module SHA-256, endpoint, immutable
timeouts, TLS/redirect/proxy policies, two-phase send-gate policy, and the raw
header/parser-state transfer-framing policy.

Before integration, independently review the transport candidate and successor
executor diff and repeat offline and cross-sport regressions. Real execution
requires a separate explicit single-use authorization. This plan creates no
such authority.
