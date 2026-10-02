# NFL Historical-Market Provider Pilot Specification 0.1.0 - Independent Review Record

Review date: `2026-09-29`

Reviewed package: `NFL_Historical_Market_Provider_Pilot_Design_Candidate.zip`

Reviewed package SHA-256: `4A6C402D29F5B927A3846FA7AD9CC5C455C07E73329E3F5B7A945B8802373118`

Reviewer provenance: independent Claude review supplied by the project owner. The original review was not repository-native evidence; this file is the project-owner-directed repository record of its disposition and findings.

Disposition: `REVISION_REQUIRED_BEFORE_PILOT_DESIGN_FREEZE`

The review reported no CRITICAL finding and no conflict with frozen protocol 0.2.5.

## Findings and 0.1.1 remediation

| Finding | Review issue | Remediation in 0.1.1 |
| --- | --- | --- |
| H-1 | Selection inputs and kickoff version authority were not fully frozen. | Sections 2-3 pin the reconciliation ZIP/ledger, a single kickoff field, version ordering, T-60, population semantics, ID ordering, timezone/tzdata, and immutable selection manifest. |
| H-2 | Attempt reservation/accounting was not durable across send, crash, restart, concurrency, and stop states. | Section 5 freezes an append-only durable ledger, pre-send reservation, single flight, crash ambiguity, restart reconstruction, and no automatic resume. |
| M-1 | Retry classes overlapped and ambiguous-send behavior was incomplete. | Section 6 provides a mutually exclusive condition/action table. |
| M-2 | Actual provider charge was not reconciled to the assumed 10 credits. | Section 7 freezes per-response quota-header reconciliation and unexpected-cost stops. |
| M-3 | Timestamp anomalies lacked deterministic stop-versus-continue treatment. | Section 8 freezes equations, equality/null rules, descriptive bins, and anomaly dispositions. |
| M-4 | Raw serialization, schema, decimal, and clock contracts were incomplete. | Section 9 freezes the byte boundary, canonical serialization, required types, lexical decimal retention, clock evidence, and predecessor kinds. |
| M-5 | Some proposed pilot claims could not be established by the bounded sample. | Section 10 limits claims to observed mechanics and sampled coverage. |
| M-6 | Evidentiary limits and `SUFFICIENT` were not procedural. | Section 11 defines a procedural evidence-completeness meaning and deterministic precedence. |
| M-7 | Provider-document authority and precedence were incomplete. | Section 12 freezes capture requirements and evidence precedence. |
| M-8 | The future execution authorization record was underspecified. | Section 13 enumerates every required identity, hash, ceiling, window, authorizer, and single-use rule. |

LOW/NOTE findings were incorporated by limiting the four sportsbooks to pilot scope, retaining but analytically excluding non-target events, defining SportsModel chain-of-custody start, limiting what `last_update` can prove, identifying the mixed OTHER stratum limitation, refusing to freeze a final book universe from pilot success, and noting that a later outcome-blind coverage census may be required.

This record is review evidence only. It does not approve 0.1.1, authorize provider access, activate an amendment, or authorize acquisition or joining.
