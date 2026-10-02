# NFL Historical-Market Provider Pilot Execution Implementation 0.1.3

Status: **IMPLEMENTATION CANDIDATE — OFFLINE CORE ONLY — PILOT EXECUTION NOT AUTHORIZED**

## Scope

This candidate remediates only MEDIUM A and MEDIUM C from the independent review
of implementation 0.1.2. It does not revise the frozen protocol, pilot design,
selection, request set, execution ceilings, evidence boundary, or procedural
dispositions.

Implementation identity:
`nfl_historical_market_provider_pilot_execution_0.1.3`.

No real provider transport exists. The executor still accepts only the exact
deterministic offline fake transport. This candidate supplies no authority or
capability for provider access or pilot execution.

## Frozen identities

| Artifact | SHA-256 |
| --- | --- |
| Protocol 0.2.5 | `09FB79F12FD9B555E4C6A362DA5E459D45F91295DB42F0582E8B1FA7E461DAA7` |
| Pilot specification 0.1.3 | `9D7DF04DF7076C3C0A397BCD1FB3719D37C7434508EA33FA9154A165EEA628E6` |
| Selection manifest 0.1.3 | `01E7D6B32BDE9965EBD7B149DB6B4C5E9085C631830E1F1701D3A31D70BE8530` |
| Pilot-design freeze record | `B7B47B7E18A8030D11C94F56AB732D510DB7957002E3D42B7579DA6FC0CAAA3E` |
| Eligible population | `38B71B797782DB67DDA9CB5770762618BB99CAAD29FD3E4607B275537052B39F` |

## Post-lease recovery revalidation

Recovery performs an initial read-only governed-store check before waiting for
the OS-owned lease. After exclusive ownership is acquired, it repeats the
complete recoverability check before its first evidence write:

1. validate the governed recovery-root shape and absence of a final manifest;
2. reload and validate retained authorization bytes without requiring the
   original execution window to remain active;
3. revalidate configuration, implementation, original provenance, and run
   identities;
4. reload and validate the complete ledger hash chain and transitions; and
5. confirm at least one current `RESERVED` or `SENT` attempt remains incomplete.

If the executor completed or a terminal manifest appeared while recovery waited,
the post-lease check fails without writing recovery provenance, ledger entries,
records, reports, or a replacement manifest. Existing completed evidence remains
unchanged and verifiable.

## Stable clock identity

Authorization and configuration equality continue to bind the clock and
monotonic implementation identities, the reviewed provenance-inspector identity,
the Windows synchronization source/provider, and the required synchronization
health category. Missing, changed, unsupported, or unhealthy stable identities
remain fail-closed.

## Dynamic clock evidence

Phase offset and last-successful-sync time are dynamic observations, not stable
identity. They are no longer included in the authorization-bound configuration
payload or its SHA-256. Each execution and recovery measurement must nevertheless
provide both values. Phase offset must parse as a finite duration with a supported
unit, and last-sync evidence must parse as a supported timestamp.

The independently measured values are retained in the respective canonical
artifacts:

- original execution: `runtime_provenance.json`;
- recovery: `recovery/runtime_provenance.json`.

Recovery does not compare its fresh dynamic values byte-for-byte with the
original observations. The final manifest continues to hash and distinguish the
two complete provenance artifacts.

## Preserved safety boundary

Implementation 0.1.3 preserves executor-owned provenance measurement, pinned
inspector identity, credential fingerprint binding, exact offline fake-transport
restriction, OS-owned locking, dedicated initial evidence storage, original and
recovery provenance separation, no continuation, terminal recovery,
authorization immutability, immutable evidence, reservation-before-send,
`SENT_UNKNOWN`, 20/20/40/400 ceilings, quota reconciliation, timestamp and PIT
rules, lexical decimal preservation, prohibited-data rejection, and manifest
tamper detection.

The independent review's non-blocking LOW/NOTE observations remain unchanged.

## Remaining prerequisite

This is an offline implementation candidate awaiting independent review and
freeze. A real provider adapter and a separate single-use execution authorization
remain future prerequisites. Neither is included or authorized here.
