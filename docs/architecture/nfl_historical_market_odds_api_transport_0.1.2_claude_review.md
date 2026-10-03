# NFL Historical-Market Odds API Transport 0.1.2 — Claude Review

Review date: `2026-10-02`

Reviewer provenance: independent Claude review supplied by project owner.
This record does not claim repository-native Claude provenance.

Reviewed candidate:
`NFL_Historical_Market_Odds_API_Transport_0.1.2_Candidate.zip`

Reviewed ZIP SHA-256:
`3AEE89C0EAF9DB0CC00FFEE588DFDC37D699D4C15D3D180501A26A1472E99092`

Disposition: **REVISION_REQUIRED_BEFORE_ODDS_API_TRANSPORT_FREEZE**

## Verified review results

- Package integrity passed.
- The two-phase prepare/send architecture passed.
- TLS verification, endpoint pinning, proxy isolation, and redirect prohibition
  passed.
- The credential boundary passed.
- Content-Encoding ownership by the frozen executor passed.
- The deterministic transport runtime identity passed.

## MEDIUM M-1 — Transfer-Encoding/parser-state disagreement

The transport normalized a single raw Transfer-Encoding value with
`strip().lower() == "chunked"`. Python's `http.client.HTTPResponse` parser does
not necessarily classify whitespace-altered values such as `chunked ` or
`chunked\t` as chunked. The transport could therefore label still-framed bytes
`STDLIB_HTTP_CLIENT_CHUNKED_DECODED` while `HTTPResponse.chunked` was false.

The required correction is agreement between exact retained raw header evidence
and the actual `HTTPResponse.chunked` parser state. Duplicate, compound,
unsupported, ambiguous, whitespace-altered, or raw/parser-mismatched states must
fail closed as conservative post-send partial-response outcomes.

## Adjacent exchange lifecycle finding

The sent exchange closed during `receive()` but exposed no public close/abort
operation. A future executor that terminalizes after send and before receive
needs an idempotent, non-sending `exchange.close()` path. This should be added
in the same bounded revision while preserving receive-finally cleanup.

## Non-blocking LOW/NOTE observations

The following are carried forward as non-blocking and are not transport-freeze
blockers: credential type validation before `CONSUMED`; explicit
`connection.auto_open = 0`; a response body size cap; a total response deadline;
duplicate/conflicting Content-Length policy; close-delimited truncation
detectability; Unicode `\d` query behavior; bool timeout acceptance; module-SHA
loaded-file semantics; ambient `SSL_CERT_FILE` / `SSL_CERT_DIR`; socket-timeout
naming; and the DNS wall-clock limitation.

## Review boundary

This review did not authorize provider DNS, socket or request activity,
credential use, purchase, credit consumption, historical odds acquisition,
pilot execution, integration, joins, model execution, database or migration
changes, production changes, commit, or push.
