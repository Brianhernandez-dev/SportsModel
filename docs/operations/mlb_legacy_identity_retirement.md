# MLB legacy retirement successor candidate (schema 035)

Implementation candidate only. No production migration, activation, recovery,
inference or publication is authorized. Independent implementation review and
the complete approved 1.6.0 verification matrix remain release gates. Do not mix
034-only and 035-aware application code.

## Scope and identity

Migration 034 and its original functions, view, constraints and component
fingerprint retain their reviewed bytes and meanings. Migration 035 adds a
separate immutable case/event namespace for only
`LEGACY_MARKET_DUPLICATE_WITHOUT_OBSERVATION_PROVENANCE` and
`IDENTITY_ONLY_DUPLICATE`. Both are lifetime ACTIVATE-only: no reversal,
retargeting, reactivation, generic nonplayed disposition or history repair.

The hypothetical reviewed pairs 29→586 and 584→26 are not authorized by this
document. Tests use wholly synthetic identities, provider bytes and prices.

## Admission and raw state

The byte-bound offline operator accepts an explicit exact schema-035 target,
retained raw MLB payload bytes, reviewed affirmative duplicate/publication
absence findings, and a separately approved preview hash. A source-less row
alone cannot qualify. Survivor authority, oriented canonical clubs, unique
MLB anchor, final single played event, result/team/pitching completeness and
subject dependency absence are independently checked against current state.

The preview binds full price-inclusive pair state, history, raw evidence, catalog
and combined ledger/topology state. The narrow SQL activation entry revalidates
inside one transaction. No providers, fabricated source/observations, price
transfer, automatic survivor redirection or ambient credentials are used.
Evidence hashes identify bytes; they do not authenticate provider truth or human
approval. Unknown attribution must block independent approval.

Legacy subjects are sealed against subsequent sources, observations, prices,
snapshots, identity/time mutation, deletion and targeted truncate bypasses.
The original observation-backed 034 raw-continuity exception is unchanged.
The combined active predicate excludes both ledgers before H-1 ranking.
`mlb_retirement_effective_markets()` preserves the original 033 projection but
excludes a retired raw OR effective identity; it never moves a market to its
survivor. RAW_FORENSIC reads continue to expose original physical evidence.

## Committed knowledge and concurrency

V2 binds the code/migration profile, complete deterministic 034 case/event
history, complete deterministic legacy history and monotonic topology epoch.
Self-derived receipt/post-hash fields are excluded to avoid a hash cycle.
One dedicated read-only repeatable-read capture uses the DB clock and produces
an in-process sealed object. The v1 child uses that same capture, never a second
independent capture. External JSON cannot supply the seal.

Installation holds the existing SHARED advisory gate while a fresh dedicated
read-only probe rechecks current composite state. Writer/ledger operations reuse
the existing gate `(1397574724,34)` and topology/per-game fences; they do not
create another lock hierarchy. Available time must not exceed the unchanged
feature cutoff; the cutoff must not exceed execution DB time. October knowledge
does not certify a July/August/Oct8 historical betting run.

New runs use a separate immutable v2 metadata column. Historical v1/NULL values
are not rewritten. Old executable 034 envelopes refuse exact schema035. Lost
commit acknowledgment yields inspect-only uncertainty, never an automatic retry.

## Deployment and verification gates

Runtime has no direct new-ledger/topology mutation. The executor is separately
granted only the reviewed narrow entry; production role names/grants are not
assumed. Schema owners/DDL administrators remain outside the application seal
boundary. Production role compatibility, operational health and performance are
not certified by disposable tests.

The 1.7.0 evidence package records the initial T01–T28 coverage gaps. The 1.7.1
rereview package retains the exact approved matrix, added isolated verification,
five demonstrated defects and their bounded corrections: positive unambiguous
MLB player-source validation, full function arguments including defaults, an
additive unknown-FK and semantic-column dependency inventories, and literal
`nfl_` namespace matching (including misleading names without an FK).
Migration 034 remains byte-identical. Only the current package's final disposition
may claim rereview readiness; this never grants production execution authority. If a
critical coverage or consumer/capability gap remains, keep inference/publication
held and report REVISION_REQUIRED; do not weaken admission to obtain green tests.

Conservative postseason `ifNecessary=Y`/TBD and R/F/D/L/W policy is unchanged.
An all-conditional date intentionally fails/defer rather than producing a
successful empty preview/card. Retained-canonical-slate zero-prediction,
historical PIT, recovery and separate authority protections remain mandatory.
