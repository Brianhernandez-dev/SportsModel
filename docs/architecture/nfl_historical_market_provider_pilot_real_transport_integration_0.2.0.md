# NFL Historical-Market Provider Pilot Real-Transport Integration 0.2.0

Status: `IMPLEMENTATION CANDIDATE — REAL PROVIDER EXECUTION NOT AUTHORIZED`

Implementation identity: `nfl_historical_market_provider_pilot_execution_0.2.0`

## Frozen dependencies and scope

| Dependency | SHA-256 |
| --- | --- |
| Executor `historical_market_pilot.py`, execution 0.1.4 | `E199D0290E45EE611F5D1FBC1C837925343E73528BCA72E7F77A85E2B8313267` |
| Transport `historical_market_odds_api_transport.py`, transport 0.1.3 | `2F7885CFFA02FA4EB72C9C408A76F4A9A742DC705A391A782FFCD02F2789264A` |
| Research protocol 0.2.5 | `09FB79F12FD9B555E4C6A362DA5E459D45F91295DB42F0582E8B1FA7E461DAA7` |
| Pilot specification 0.1.3 | `9D7DF04DF7076C3C0A397BCD1FB3719D37C7434508EA33FA9154A165EEA628E6` |
| Selection manifest 0.1.3 | `01E7D6B32BDE9965EBD7B149DB6B4C5E9085C631830E1F1701D3A31D70BE8530` |
| Population identity | `38B71B797782DB67DDA9CB5770762618BB99CAAD29FD3E4607B275537052B39F` |

The frozen executor and transport remain byte-identical. This successor is a
separate module, `src/sportsmodel/nfl/historical_market_pilot_integrated.py`.
Its source hash is recorded in the candidate package manifest, not embedded in
its own source. There is no CLI, job, schedule, credential discovery, production
wiring, development override, transport factory, or authorization builder.

## Architecture and reuse boundary

`IntegratedPilotExecutor` subclasses the frozen executor and directly reuses
its unchanged `_execute_target` state machine, ledger, counters, request builder,
retry authority, application decoder, quota reconciliation, PIT checks, target
analysis, dispositions, reports, leases, and immutable evidence operations.

`IntegratedConfig` extends the frozen configuration with exact immutable
`TransportTimeouts` and the component bundle. The production constructor creates
the exact frozen `OddsApiHistoricalTransport`; it accepts no transport or factory.
The live gate checks concrete type, runtime identity, credential fingerprint,
all three source hashes, measured runtime, clean Git identity and config binding.

A private `_AttemptBridge` adapts the frozen state machine's internal `begin`
call to the reviewed two-phase API. It cannot be selected by callers and does
not bypass either live gate. The real transport itself still has no combined
prepare/send method. No frozen globals are patched or rebound in production.

The frozen lifecycle functions hard-code offline implementation identities and
have no successor hooks. Their admission, run/report/manifest lifecycle and
recovery identity checks therefore have versioned local counterparts. The
attempt/analysis state machine is not copied. This is an explicit size tradeoff:
the successor is smaller than the executor, but larger than the transport. It
does not satisfy the requested preference to be smaller than both components.
Independent review must assess this glue and drift risk; no frozen component was
refactored to create hooks just to reduce successor line count.

## Attempt sequence and resource ownership

1. Validate immutable authorization, active half-open window, measured runtime,
   exact configuration, component sources, transport and credential identity.
2. The frozen ledger durably reserves one attempt and ten credits under its
   20-primary / 20-retry / 40-attempt / 400-credit limits.
3. Persist the canonical credential-free request and attempt metadata.
4. Repeat the live gate. The bridge also verifies durable RESERVED and request
   artifact presence and repeats the live gate before preparation.
5. Call `transport.prepare()` with neither request nor credential. Only future
   DNS/TCP/TLS capability resides in the frozen transport; preparation transmits
   no HTTP request bytes and adds no ledger attempt.
6. Repeat the live authorization/window/runtime gate after preparation. If it
   fails, `prepared.close()` runs and `send()` is never called. The frozen core's
   unclassified-boundary rule conservatively records SENT_UNKNOWN, even though
   the deterministic integration test establishes zero HTTP bytes. No retry.
7. Reuse the frozen transport request validator before invoking `send()`. Only
   this proven pre-send validation exception is mapped to provable pre-send.
8. Call `prepared.send(request, credential)`. HTTP buffering remains pre-send;
   entering `endheaders()` remains the possible-send boundary.
9. The frozen state machine immediately appends SENT before receive. If this
   write fails, integration ownership closes the exchange and tries to append
   SENT_UNKNOWN. If durable terminal state is impossible, execution hard-fails
   with the retained interrupted store, rather than emitting a normal report.
10. Preserve the frozen post-send authorization-bytes check exactly. Mutation
    produces SENT_UNKNOWN and closes without receive. Window expiry alone after
    send does not introduce a new before-receive rule: response capture remains
    permitted and the next attempt's live gate blocks further sends.
11. `exchange.receive()` closes via the frozen transport's `finally`; integration
    has additional idempotent ownership closure on every return/exception path.
12. Frozen decoding, quota, timestamp/PIT, target matching, retry and reporting
    logic continues unchanged. Whole-run authorization checks remain before
    report, manifest and final acceptance.

Every successful prepare is closed in a `finally` (a consumed prepared object
does not close its owned exchange). Every returned exchange is received or
explicitly closed, including SENT-write and post-send authorization failures.
For an unclassified exception from frozen `send()` after its prepared handle is
consumed but before an exchange is returned, integration closes the exact frozen
private connection slot as a fallback. This private dependency is source-hash
pinned and must be reviewed; its exception remains unknown, never pre-send.

## Failure mapping and recovery

| Boundary | Frozen classification / authority |
| --- | --- |
| DNS preparation | `PROVABLE_PRE_SEND_FAILURE`, DNS |
| TCP or preparation timeout | `PROVABLE_PRE_SEND_FAILURE`, CONNECT |
| TLS preparation | `PROVABLE_PRE_SEND_FAILURE`, TLS |
| Local request validation or buffering | Provable pre-send CONNECT |
| `endheaders()` or unclassified send exception | SENT_UNKNOWN; never ordinary retry |
| Receive reset/timeout | SENT_UNKNOWN / possible-send |
| Partial response or ambiguous transfer framing | SENT_UNKNOWN / partial-response |
| Evidence I/O after transmission | SENT_UNKNOWN if writable; otherwise hard failure |
| Authorization failure after prepare | Conservative terminal SENT_UNKNOWN, zero send |

Only the frozen executor decides whether a documented response or provable
pre-send failure receives its single eligible retry. Preparation is not an extra
attempt and no integration-specific retry policy exists.

`IntegratedPilotRecovery` is recovery-only, has no transport or credential and
cannot resume. It reuses frozen ledger recovery, leases, provenance validation
and integrity verification with successor identity admission. Lingering RESERVED
or SENT becomes SENT_UNKNOWN, including after expiry. Original run attribution
is retained; recovery has separate provenance. Existing evidence stores cannot
be reused as fresh executions.

## Identity, credential and evidence boundaries

Authorization binds the exact successor identity/source hash, executor and
transport identities/source hashes, config hash, measured clean repository HEAD,
credential fingerprint/quota attribution, target IDs, ceilings and all frozen
protocol/spec/selection/kickoff identities. Transport identity includes concrete
class plus its hashed payload: endpoint, TLS, redirect, proxy, connect/read
timeouts, transfer framing, executor-owned content decoding, module source hash
and `PREPARE_THEN_REVALIDATE_THEN_SEND`. A label alone is insufficient.

Only an explicit `SecretCredential` enters execution; the successor discovers
no environment, `.env`, registry, MLB credential or provider account. Tests use
only `TEST_KEY_DO_NOT_SEND`. The fingerprint is the frozen domain-separated
credential identity, not persisted plaintext.

Run identity and manifest include the three-component bundle. Attempts retain
exact encoded entity bytes as `transport_entity.bin`, ordered/raw headers,
status, transfer/content-decoding ownership, receive UTC time and component
bundle as `transport_response.json`, alongside frozen request/response/ledger
artifacts. Frozen `decode_application_body()` alone decodes Content-Encoding;
there is no second decode. Retention occurs at the frozen safe write boundary,
after its secret checks. Corrupt encoded bodies retain frozen terminal behavior.
Body/value secret echoes use the frozen non-retention path; the additional raw
header-name surface fails closed without retention if it echoes the credential.

No score/result/settlement/model/prediction/edge/wager/ROI/training/performance
join capability is added; frozen prohibited-data checks remain in authority.

## Deterministic validation and review prerequisites

`tests/nfl/test_historical_market_pilot_transport_integration.py` contains only
synthetic tmp-path authorization/config/evidence. The exact concrete transport
is exercised with its HTTPS connection construction replaced at the private
module boundary. OS `socket.socket`, `create_connection` and `getaddrinfo` are
blocked, including a direct kill-switch assertion. Runtime provenance is
synthetic at the private measurement boundary; test success is not live-runtime
or authorization readiness.

Coverage includes complete 20-target success, eligible retries, post-prepare
expiry, post-send expiry/mutation, ambiguous sends, evidence/durable-ledger
failures, conservative recovery, encoding/framing, secrets, identity/config
rejection, quota inconsistency, exact ceilings and final authorization gates.
Raw final validation commands/results and artifact hashes belong in the external
candidate ZIP. Nothing in that package is provider data or execution authority.

Real execution still requires independent review of this exact candidate,
resolution of findings, a separately authorized freeze/commit milestone, clean
reviewed source/runtime identities and a separate explicit single-use execution
authorization meeting frozen spec Section 13. Any purchase/account/credential
setup/provider access also requires its own explicit approved scope. This task
creates none of those authorities and must not be used as a pilot runbook.

The draft provider amendment remains `DRAFT — NOT ACTIVE — NOT ACQUISITION
AUTHORITY`. Historical provider acquisition, pilot execution, market/performance
joins, model evaluation/training, predictions/betting outputs, DB mutation,
migrations and MLB production changes remain unauthorized.
