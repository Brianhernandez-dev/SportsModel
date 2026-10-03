# NFL Historical-Market Odds API Transport 0.1.0 — ChatGPT Review

Review date: `2026-10-02`

Reviewer provenance: ChatGPT PM/technical review supplied by project owner.
This record does not claim repository-native ChatGPT provenance.

Reviewed candidate:
`NFL_Historical_Market_Odds_API_Transport_0.1.0_Candidate.zip`

Reviewed ZIP SHA-256:
`A725C1140B2BE413DB2DA1F20C62DDBBD62FFF0FE7AE1EA6DE97C40B98FC007B`

Disposition: **REVISION_REQUIRED_BEFORE_TRANSPORT_FREEZE**

## Verified review results

- Package integrity passed.
- The independently rerun transport suite passed: 49 tests.
- The send boundary around `http.client.HTTPSConnection.endheaders()` passed.
  `putrequest()` and `putheader()` buffer locally; entering `endheaders()` is
  the reviewed transition to possible send and must not be moved later.

## MEDIUM findings

### Mutable production transport and replaceable connection factory

The production transport exposed `_new_connection()` as an overridable instance
method and retained mutable instance state. A caller could replace that method
after capturing `runtime_identity`, causing actual connection behavior to differ
from the behavior represented by the reviewed identity. The production object
must be structurally immutable, expose no instance connection-factory seam, and
permit tests to replace only a private module-level boundary.

### Content decoding and complete-response classification

The transport performed gzip/deflate Content-Encoding decoding and mapped a
complete but undecodable response to `PossibleSendFailure(PARTIAL_RESPONSE)`.
Content-Encoding decoding belongs to the frozen executor's reviewed
`decode_application_body()` boundary. The transport must return complete entity
bytes with the raw Content-Encoding header intact, including corrupt or
unsupported encodings, so the frozen core can retain and classify the evidence.

## Related response-framing issue

The transport declared every returned body
`stdlib_http_client_transfer_decoded` without validating Transfer-Encoding.
Before exposing entity bytes, it must distinguish no declared transfer coding
from exact chunked framing decoded by `http.client`, and fail closed on
unsupported, compound, duplicate, or otherwise ambiguous transfer codings.

## Review boundary

This review did not authorize DNS lookup, socket creation, provider access,
credential use, purchase, credit consumption, historical odds acquisition,
pilot execution, joins, model execution, database or migration changes,
production changes, commit, or push.
