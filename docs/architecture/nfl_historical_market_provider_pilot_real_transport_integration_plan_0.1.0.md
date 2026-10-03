# NFL Historical-Market Real-Transport Integration Plan 0.1.0

Status: **DESIGN ONLY — INTEGRATION AND PROVIDER EXECUTION NOT AUTHORIZED**

## Purpose

This record describes the minimum future reviewed change needed to integrate
`nfl_historical_market_odds_api_transport_0.1.0` after offline executor 0.1.4 is
independently approved and frozen. It does not modify the pristine 0.1.4 core.

## Minimum reviewed core revision

The future revision should replace the exact fake-only check with an explicit
closed allowlist of separately reviewed transport implementation identities. It
must bind the selected transport module SHA-256 and canonical configuration hash
through runtime provenance, configuration, single-use authorization, run
identity, and the evidence manifest. It must not accept a generic caller label,
arbitrary hostname, arbitrary transport object, or validation bypass.

The revision must preserve:

- executor-owned local runtime measurement;
- inspector identity and clean Git/source checks;
- credential fingerprint binding before the transport boundary;
- whole-run authorization revalidation and execution-window gates;
- durable reservation before possible request transmission;
- 20/20/40/400 limits and quota reconciliation;
- pre-send retry eligibility and possible-send `SENT_UNKNOWN` handling;
- original/recovery provenance separation and post-lease recovery validation;
- secret-free canonical request evidence and immutable raw evidence; and
- no continuation or automatic restart of predecessor accounting.

## Response-boundary adaptation

The transport returns transfer-decoded and explicitly content-decoded entity
bytes together with immutable raw headers and decoding identities. The future
executor revision must persist the raw Content-Encoding header but must not pass
the already decoded body through the existing core content decoder a second
time. The adapter must make this state explicit and fail closed if decoding
identity, raw headers, or body provenance is missing or inconsistent.

## Failure mapping

The future adapter should map the transport's reviewed state machine without
reinterpretation:

- DNS/TCP/TLS or local buffering failure proven before request-byte handoff →
  the matching `ProvablePreSendFailure` and existing single-retry rules;
- any failure beginning with `endheaders()` → `PossibleSendFailure`;
- reset after possible send → `RESET_AFTER_SEND`;
- partial or undecodable response → `PARTIAL_RESPONSE`;
- read timeout or otherwise ambiguous post-send failure → `POSSIBLE_SEND`.

No retry logic belongs in the transport.

## Required future review

Before integration, independently review and hash the transport source,
configuration, tests, dependency/runtime identity, and this mapping. Then create
a successor executor identity, repeat offline and cross-sport regression testing,
and only afterward consider a separate single-use execution authorization. This
plan grants none of those authorities.
