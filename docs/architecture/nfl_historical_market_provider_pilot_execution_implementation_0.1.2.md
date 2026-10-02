# NFL Historical-Market Provider Pilot Execution Implementation 0.1.2

Status: **IMPLEMENTATION CANDIDATE — OFFLINE CORE ONLY — PILOT EXECUTION NOT AUTHORIZED**

## Scope

This candidate closes only the two runtime-provenance findings recorded by the
direct review of implementation 0.1.1. It does not revise the frozen protocol,
pilot specification, selection, request set, retry rules, ceilings, evidence
boundary, or procedural dispositions.

Implementation identity:
`nfl_historical_market_provider_pilot_execution_0.1.2`.

No real provider transport exists in this implementation. The executor still
accepts only the exact deterministic offline fake transport. Nothing in this
candidate authorizes or enables a provider call or pilot execution.

## Frozen identities

| Artifact | SHA-256 |
| --- | --- |
| Protocol 0.2.5 | `09FB79F12FD9B555E4C6A362DA5E459D45F91295DB42F0582E8B1FA7E461DAA7` |
| Pilot specification 0.1.3 | `9D7DF04DF7076C3C0A397BCD1FB3719D37C7434508EA33FA9154A165EEA628E6` |
| Selection manifest 0.1.3 | `01E7D6B32BDE9965EBD7B149DB6B4C5E9085C631830E1F1701D3A31D70BE8530` |
| Freeze record | `B7B47B7E18A8030D11C94F56AB732D510DB7957002E3D42B7579DA6FC0CAAA3E` |
| Eligible population | `38B71B797782DB67DDA9CB5770762618BB99CAAD29FD3E4607B275537052B39F` |

## Executor-owned measurement boundary

The production `PilotExecutor` no longer accepts a runtime-provenance inspector
from its caller. `run()` constructs the reviewed
`LocalRuntimeProvenanceInspector` from the supplied repository root and performs
that measurement before configuration acceptance, evidence-store creation, an
attempt reservation, or the transport boundary. A caller cannot replace the
measurement implementation with a static or synthetic inspector through the
production entry point.

The reviewed measurement implementation has the deterministic identity
`sportsmodel.local_runtime_provenance_inspector.v1`. That identity is pinned by
the authorization-bound configuration, checked during validation, and retained
in the canonical runtime-provenance evidence.

## Recovery-current-runtime provenance

Recovery still has no transport or credential and cannot resume execution.
Before it mutates an existing governed store, it uses the same reviewed local
measurement component to measure the current repository root, Git revision and
clean state, implementation-source SHA-256, Python/runtime identity, dependency
identity, tzdata identity, Windows synchronization evidence, recovery clock,
and monotonic-timer identity.

The current values must match the governed 0.1.2 recovery policy. A dirty
repository, different revision, different implementation source, or different
stable runtime identity fails before the evidence store is modified. The
original execution window is not required to remain active.

After validation and exclusive lease acquisition, recovery writes the immutable
current-runtime artifact `recovery/runtime_provenance.json` before appending any
recovered ledger state. The original `runtime_provenance.json` is retained
byte-for-byte and is never overwritten or reinterpreted.

The recovery record pins the artifact SHA-256 of both original and recovery
runtime provenance. The final evidence manifest separately attributes the
original execution runtime and the recovery runtime, including the path and
SHA-256 of each provenance artifact.

## Preserved safety behavior

Implementation 0.1.2 preserves credential fingerprint binding, exact offline
fake-transport restriction, OS-backed single-flight ownership, the dedicated
initial evidence store, whole-run authorization revalidation, reservation-before-
send ordering, 20/20/40/400 ceilings, retry and quota rules, PIT and timestamp
checks, secret redaction, immutable raw evidence, manifest verification, and the
terminal no-continuation recovery policy.

Incomplete `RESERVED` or `SENT` attempts still become permanent `SENT_UNKNOWN`.
Recovery cannot call a provider, acquire a credential, continue execution, or
restart predecessor accounting.

## Test boundary

Deterministic tests replace the reviewed inspector's local measurement behavior
only inside the test process; the production executor exposes no inspector
selection parameter or validation bypass. Regression coverage verifies the
closed constructor surface, pre-provider measurement ordering, inspector
identity retention, recovery rejection before mutation, separate recovery
provenance, byte preservation of original provenance, explicit dual manifest
attribution, and the prior offline safety behavior.

## Remaining prerequisite

This remains an offline implementation candidate awaiting secondary review. A
real provider adapter, its network/TLS/send-ambiguity behavior, a successor
reviewed implementation identity, and a separate single-use execution
authorization are future prerequisites. None is supplied or authorized here.
