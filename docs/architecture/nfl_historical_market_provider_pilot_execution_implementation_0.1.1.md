# NFL Historical-Market Provider Pilot Execution Implementation 0.1.1

Status: **IMPLEMENTATION CANDIDATE — OFFLINE CORE ONLY — PILOT EXECUTION NOT AUTHORIZED**

## Scope and frozen boundary

This candidate remediates runtime-integrity findings from direct review of the
0.1.0 candidate. It does not revise the frozen base protocol, pilot design,
selection, target population, request set, retry rules, quota ceilings, timestamp
semantics, evidence boundary, or procedural dispositions.

Implementation identity:
`nfl_historical_market_provider_pilot_execution_0.1.1`.

The candidate cannot execute a real pilot. It contains no reviewed real HTTP or
provider transport and explicitly accepts only the deterministic offline
transport implementation. A real provider adapter remains a future separately
reviewed implementation milestone.

## Frozen identities

| Artifact | SHA-256 |
| --- | --- |
| Protocol 0.2.5 | `09FB79F12FD9B555E4C6A362DA5E459D45F91295DB42F0582E8B1FA7E461DAA7` |
| Pilot specification 0.1.3 | `9D7DF04DF7076C3C0A397BCD1FB3719D37C7434508EA33FA9154A165EEA628E6` |
| Selection manifest 0.1.3 | `01E7D6B32BDE9965EBD7B149DB6B4C5E9085C631830E1F1701D3A31D70BE8530` |
| Freeze record | `B7B47B7E18A8030D11C94F56AB732D510DB7957002E3D42B7579DA6FC0CAAA3E` |
| Eligible population | `38B71B797782DB67DDA9CB5770762618BB99CAAD29FD3E4607B275537052B39F` |

## Measured runtime identity

Before an authorization claim or attempt reservation, an injected provenance
inspector must establish the actual repository root, Git HEAD and dirty state,
implementation-source SHA-256, configuration SHA-256, Python runtime identity,
dependency/lock identity, timezone/tzdata identity, evidence-store identity,
Windows synchronization source/status and offset evidence, monotonic-timer
identity, clock class/declared identity, transport class/declared identity, and
`OFFLINE_ONLY` mode.

Every measured value is compared with the authorization-bound configuration.
Caller assertions are not sufficient. The local inspector performs only local
Git, filesystem, Python metadata, and Windows `w32tm /query /status /verbose`
inspection; it makes no network request. Missing or ambiguous clock-
synchronization evidence fails readiness.

The complete canonical provenance is durably written as
`runtime_provenance.json` before the first reservation and its SHA-256 is linked
from `run_identity.json`.

## Credential, transport, and clock binding

The injected high-entropy credential is bound through:

```text
SHA256("SPORTSMODEL_ODDS_CREDENTIAL_V1\0" || credential_bytes)
```

Only the uppercase fingerprint and a separate account/subscription label are
authorized and persisted. The secret is neither stored nor hashed into review
artifact identities other than this explicit domain-separated credential
fingerprint. A wrong credential under the same label fails before the transport
boundary.

Transport and clock identities combine their concrete Python module/class with
their declared runtime identity. The monotonic timer has a separate pinned
identity. Implementation 0.1.1 rejects every transport class except the offline
deterministic fake, preventing an arbitrary or premature HTTP adapter from
satisfying this candidate's authorization boundary.

The clock is a single abstraction supplying UTC wall time, monotonic readings,
and deterministic sleep. Tests inject a deterministic clock; the runtime class
and both clock identities are authorization-bound.

## Authorization immutability

The authorization artifact is checked:

- at initial validation;
- before each reservation and immediately before transport invocation;
- immediately after send and response/ambiguous provider boundaries;
- before retry;
- before final report construction;
- before evidence-manifest creation; and
- immediately before and after final manifest verification.

Mutation fails closed, prevents further calls, and cannot be returned as
`PILOT_PROVIDER_EVIDENCE_SUFFICIENT`. If mutation or manifest failure occurs
after a report or candidate manifest write, a separate terminal integrity record
is retained and that manifest is deliberately not accepted.

## Dedicated initial evidence store

A new execution root must be outside the Git repository and either absent or an
empty directory. Any unexpected pre-existing item fails before authorization
claim or provider invocation. Authorization claim, provenance, run identity,
request, response, ledger, report, and manifest artifacts remain immutable and
collision-failing.

Only the explicit recovery-only lifecycle may open an existing evidence store.
It validates the expected top-level shape, authorization bytes and claim hash,
configuration and implementation identity, provenance hash, evidence-store
identity, and ledger sequence/hash chain before any mutation.

## OS-owned lease and recovery-only lifecycle

The fixed `.pilot.lock` path now uses a nonblocking OS byte-range/file lock.
Ownership is released by the OS when a process exits, including a hard crash;
the persistent lock artifact is not treated as ownership and is not deleted to
guess staleness. A second live owner cannot acquire the lease.

`PilotRecovery` has no transport or credential. It can only:

1. validate an existing governed store;
2. acquire exclusive recovery ownership;
3. reconstruct durable counters from the hash-chained ledger;
4. convert incomplete `RESERVED` or `SENT` attempts to permanent
   `SENT_UNKNOWN`;
5. retain counters and recovered attempt IDs in a deterministic recovery record;
6. issue a failed terminal procedural report and verified evidence manifest.

Recovery never calls a provider and never resumes execution.

## Prior-accounting and continuation policy

Implementation 0.1.1 supports only authorization policy
`INITIAL_ONLY_NO_CONTINUATION` with a JSON `null` predecessor manifest. Any
declared continuation or predecessor evidence is rejected. A crashed, recovered,
completed, or terminal store cannot be reopened by the execution entry point,
and the recovery record states `continuation_supported:false`.

Accordingly, no further provider calls after a crash or terminal run are
supported by 0.1.1. A future continuation requires a new reviewed implementation
that cryptographically pins predecessor manifests and carries cumulative
attempt/reserved-credit accounting. This candidate intentionally does not
implement that larger scope.

## Fail-closed I/O

Immutable writes and ledger appends translate unexpected filesystem failures to
non-secret evidence errors. A pre-send request-evidence failure prevents the
transport boundary. If response evidence fails after a possible send, the
attempt is conservatively transitioned to `SENT_UNKNOWN` when the ledger remains
writable. If durable terminal evidence itself cannot be written, execution fails
hard and performs no further provider call.

## Preserved behavior

The remediation preserves frozen target/request verification, secret-free
canonical requests, 20/20/40 attempt ceilings, 400-credit ceiling, 10-credit
reservation, reservation-before-send ordering, `SENT_UNKNOWN` no-retry behavior,
HTTP retry taxonomy, quota reconciliation, zero-credit empty responses, exact
application-visible body retention, lexical decimal tokens, market-level
`last_update` semantics, bookmaker timestamp non-authority, PIT invariants,
prohibited-data detection, immutable evidence, and manifest verification.

It adds no database, migration, model, prediction, market-join, MLB, production,
or provider-access path.

## Deterministic tests

The original 82 tests remain present. Added regression coverage verifies actual
HEAD/dirty/source mismatches, credential fingerprint mismatch and non-disclosure,
transport and clock identity binding, incomplete provenance, nonempty initial
stores, governed-store recovery, `RESERVED` and `SENT` recovery, stale-artifact
lease reuse without concurrent ownership, zero-transport recovery, no
continuation, authorization mutation during first/final boundaries and final
report/manifest stages, and I/O failure before and after possible send.

All provider responses, credentials, provenance, clocks, quota headers, and
filesystem stores used by tests are synthetic. No test contains or exercises a
real network transport.

## Remaining prerequisite

This is an offline core candidate awaiting secondary review. Before any real
pilot could be considered, a separately versioned real transport adapter would
need hostname pinning, TLS verification, redirect prohibition, timeout/send-
ambiguity behavior, as-sent request and credential boundaries, dependency
identity, tests, independent review, a new implementation identity, and a new
single-use execution authorization. None is authorized or supplied here.
