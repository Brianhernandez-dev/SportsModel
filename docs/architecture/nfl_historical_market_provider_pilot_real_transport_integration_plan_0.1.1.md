# NFL Historical-Market Real-Transport Integration Plan 0.1.1

Status: **DESIGN ONLY — INTEGRATION AND PROVIDER EXECUTION NOT AUTHORIZED**

## Purpose

This record describes the minimum future reviewed change needed to integrate
the candidate `nfl_historical_market_odds_api_transport_0.1.1`. It does not
modify or activate the frozen offline executor 0.1.4 and creates no provider or
execution authority.

## Closed transport admission

A future successor executor must require the exact reviewed concrete
`OddsApiHistoricalTransport` type and exact reviewed runtime identity. It must
reject subclasses, wrappers, generic transport objects, caller-provided
factories, generic transport-injection paths, alternate endpoints, and
configuration not bound by the single-use authorization.

Runtime provenance, run identity, authorization, and the evidence manifest must
pin the transport module SHA-256, implementation identity, endpoint and policy
payload, immutable connect/read timeouts, and resulting runtime identity. The
transport object and nested configuration must remain immutable after
construction.

## Response boundary

The 0.1.1 transport owns HTTP/TLS, response framing, validation of declared
Transfer-Encoding, stdlib chunk removal, immutable raw headers, and complete
entity bytes. It does not decode Content-Encoding.

The frozen executor retains its reviewed `decode_application_body()` function
as the sole gzip/deflate/application-visible decoding boundary. A future
integration should therefore pass the transport response directly into that
reviewed decoder. No already-decoded-body adapter or double-decoding exception
is required. The integration must preserve raw Content-Encoding and
Transfer-Encoding headers plus the transport's explicit transfer-decoding
metadata in retained evidence.

## Preserved execution controls

The successor integration must preserve executor-owned runtime measurement,
clean-source and identity checks, credential fingerprint binding, whole-run
authorization validation, execution windows, durable pre-send reservation,
20/20/40/400 limits, quota reconciliation, retry eligibility, `SENT_UNKNOWN`
handling, recovery provenance, immutable raw evidence, and fail-closed
predecessor accounting.

Failure mapping remains unchanged: proven DNS/TCP/TLS or local buffering
failure is pre-send; entering `endheaders()` begins possible send; reset,
timeout, incomplete response, and unsupported/ambiguous transfer framing remain
conservative post-send outcomes. No retry logic belongs in the transport.

## Required future review and authorization

Before integration, independently review and hash the exact transport source,
tests, configuration, runtime identity, response mapping, and successor
executor diff. Repeat offline and cross-sport regression testing. Any real
provider pilot then requires a separate explicit single-use execution
authorization. This plan authorizes none of those actions.
