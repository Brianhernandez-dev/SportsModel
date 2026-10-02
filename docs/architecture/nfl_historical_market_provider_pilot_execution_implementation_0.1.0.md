# NFL Historical-Market Provider Pilot Execution Implementation 0.1.0

Status: **IMPLEMENTATION CANDIDATE — PILOT EXECUTION NOT AUTHORIZED**

## Scope

This candidate implements the offline-testable execution and evidence machinery
required by the frozen NFL historical-market provider pilot design 0.1.3. It
does not implement a concrete HTTP client, contain an execution authorization,
read an API key, acquire provider data, or permit a pilot run without a future
single-use authorization and explicitly injected credential.

The implementation is isolated to the NFL package. It does not change MLB,
database, migration, model, prediction, joining, or production paths.

## Frozen identities

| Artifact | Identity | SHA-256 |
| --- | --- | --- |
| Base protocol | `nfl_historical_market_research_0.2.5` | `09FB79F12FD9B555E4C6A362DA5E459D45F91295DB42F0582E8B1FA7E461DAA7` |
| Pilot specification | `nfl_historical_market_provider_pilot_spec_0.1.3` | `9D7DF04DF7076C3C0A397BCD1FB3719D37C7434508EA33FA9154A165EEA628E6` |
| Selection manifest | `nfl_historical_market_provider_pilot_selection_manifest_0.1.3` | `01E7D6B32BDE9965EBD7B149DB6B4C5E9085C631830E1F1701D3A31D70BE8530` |
| Eligible population | 1,359 games | `38B71B797782DB67DDA9CB5770762618BB99CAAD29FD3E4607B275537052B39F` |

The loader verifies the frozen document identities, population identity, 20
targets, 20 distinct canonical requests, exact request grammar, and each
canonical request hash. Selection is loaded, not recomputed.

## Components

`src/sportsmodel/nfl/historical_market_pilot.py` provides:

- typed execution configuration and single-use authorization models;
- frozen selection-manifest verification;
- an authorization gate bound to design, implementation, repository,
  credential, clock, evidence-store, target, window, and ceiling identities;
- an injected provider transport protocol and deterministic offline fake;
- a durable hash-chained append-only attempt ledger;
- strict sequential execution, single-flight locking, restart reconstruction,
  and conservative attempt/credit accounting;
- immutable request, raw-response, analysis, run-identity, report, and manifest
  artifacts;
- lexical JSON-number preservation, point-in-time validation, event matching,
  quota reconciliation, retry classification, disposition logic, and prohibited-
  data detection.

`tests/nfl/test_historical_market_pilot.py` supplies synthetic authorization,
transport, response, quota, crash, and filesystem fixtures. It contains no
provider data and makes no network request.

## Authorization gate

The entry point requires an external JSON authorization artifact whose content
matches the exact runtime configuration hash and frozen identities. It verifies
the implementation revision/hash, clean repository identity, secret-free
credential identity and quota-attribution mode, evidence-store path, clock
identity, exact targets, execution window, and fixed 20/20/40/400/10 ceilings.

The artifact bytes are rechecked during execution. Exclusive creation of the
authorization claim makes the authorization single-use for that evidence store.
There is no force flag, development override, or environment-variable bypass.
A real authorization artifact is intentionally absent.

## Transport and no-network boundary

Only a `ProviderTransport` protocol is defined. The candidate contains no
socket, HTTP-library, or provider-client implementation. A credential value is
accepted only as an explicitly injected `SecretCredential`; it is not loaded
from the environment, configuration files, credential stores, logs, databases,
or production tasks. The included deterministic fake is in-memory and discards
the credential argument.

Canonical request bytes omit the API key. The evidence form of the as-sent URL
contains only `[REDACTED]`. Complete headers are retained with credential header
names redacted.

## Ledger, crash, and retry semantics

The attempt ledger is canonical JSON Lines with a monotonically increasing
sequence and SHA-256 chain. Each append flushes the file and invokes an
fsync-equivalent directory flush, including the Windows directory-handle path.
`RESERVED` is durable before `ProviderTransport.begin` can be invoked.

The implemented states are `RESERVED`, `PROVABLE_PRE_SEND_FAILURE`, `SENT`,
`RESPONSE_CAPTURED`, `SENT_UNKNOWN`, and `TERMINAL_STOP`. Counters are rebuilt
from durable reservations. Recovery changes incomplete `RESERVED` or `SENT`
attempts to permanent `SENT_UNKNOWN`; it neither retries nor resumes.

The mutually exclusive taxonomy covers proven DNS/connect/TLS pre-send
failures, ambiguous-send failures, resets, partial responses, 1xx, 3xx, 204,
ordinary 4xx, 408, 429 with required `Retry-After`, 5xx, provider-error 200,
empty/no-data 200, window expiration, undecodable content encoding, and
unparsable top-level JSON. A retry must link to an eligible predecessor, use the
same canonical request hash, fit the authorization window, and remain the only
retry for the target.

## Quota and evidence contracts

Each reservation consumes one attempt and conservatively reserves 10 credits.
The ledger rejects more than 20 primaries, 20 retries, 40 attempts, or 400
reserved credits. Every complete final response requires integer, nonnegative
`x-requests-used`, `x-requests-remaining`, and `x-requests-last` evidence.
Reconciliation checks used/remaining deltas and fails closed above 10 credits.
A consistent zero-credit response is accepted only for valid empty/no-data.

The immutable evidence store retains authorization and run identities,
canonical and redacted request forms, request/receipt timestamps, status,
redacted headers, server and content metadata, quota headers, exact decoded
application-visible body bytes and hash, derived analysis, predecessor links,
ledger, and final procedural report. Undecodable bodies are retained separately
as transport bytes with an explicit warning and terminal disposition.

The deterministic evidence manifest records byte size and uppercase SHA-256 for
every artifact and detects missing, extra, modified, duplicated, or size/hash-
mismatched evidence.

## Timestamp, identity, and disposition behavior

Provider decimal odds are parsed as their original lexical JSON tokens. Wrapper
and market timestamps are strict timezone-aware RFC3339 values. The code enforces
wrapper/request, market/request, market/wrapper, and adjacent-wrapper ordering;
computes ages in integer milliseconds; and applies the frozen descriptive bins.

A missing, null, empty, non-string, malformed, or timezone-less selected-market
`last_update` is localized as
`MARKET_TIMESTAMP_FIELD_MISSING_OR_INVALID`. The bookmaker timestamp is retained
only as context and is never substituted. This condition remains nonterminal
but floors the report at `PILOT_PROVIDER_EVIDENCE_REVISION_REQUIRED`.

Target matching uses only frozen sport, participant orientation, kickoff-version,
and provider-event identity fields. Non-target events remain in raw evidence but
are excluded from target analysis. Ambiguity or conflict fails closed. Recursive
guards reject score, outcome, settlement, model probability, prediction, edge,
wager, ROI, performance, and training-data fields.

The report can produce `PILOT_PROVIDER_EVIDENCE_SUFFICIENT`,
`PILOT_PROVIDER_EVIDENCE_REVISION_REQUIRED`, or
`PILOT_PROVIDER_FEASIBILITY_FAILED`. `SUFFICIENT` is procedural only and does
not freeze or authorize any downstream provider, market, settlement, joining,
modeling, prediction, or production policy.

## Test coverage and no-network validation

The focused deterministic suite covers the frozen identities, manifest tamper,
authorization absence/mismatch/window/use/mutation, credential redaction,
reservation-before-send, crash recovery, `SENT_UNKNOWN`, retry eligibility and
limits, the full HTTP taxonomy, `Retry-After`, quota cases and ceilings, raw-body
hashes and collisions, timestamp invariants and localized market timestamp
deficiencies, lexical prices, event matching, prohibited data, dispositions,
evidence-manifest tampering, single-flight, outside-repository storage, and the
offline fake execution path.

No test imports or patches a network library because the implementation has no
real-network transport to invoke. Test data use the visibly synthetic credential
`TEST_KEY_DO_NOT_SEND` and synthetic provider responses only.

## Unresolved operational prerequisite

An actual provider credential/quota-isolation mode remains unresolved and is not
implemented or selected here. A future pilot would require independent review
of this candidate plus a separate explicit, single-use execution authorization
that pins the final credential identity, attribution mode, implementation and
configuration hashes, clean repository state, evidence store, trusted clock,
and execution window. That later authorization must not be inferred from this
candidate document.
