# MLB canonical-time arbitration: schema036 candidate boundary

This is a development implementation of the reviewed exact-case design, not a
production cutover runbook or execution authorization. Do not apply, activate,
correct, retire, reconcile, recover, publish or enable a workflow from this file.
Readiness requires all 72 approved scenarios and the six authoritative final
suites against one frozen candidate, followed by independent review.

## Scope and state

The native policy admits only duplicate584, survivor26, MLB gamePk823842 and the
change 2026-07-12T17:41:00Z to 17:40:00Z (-60 seconds). Migration036 is additive;
migrations001–035, matcher semantics and exact035 retirement admission remain
unchanged. No retirement is a side effect. All source/history/market attribution,
prices, metrics, availability and physical584 remain unchanged.

The correction uses a dedicated SERIALIZABLE transaction, the existing exclusive
identity gate, topology and ascending game/fence locks, a separate nonlocking fresh
committed probe, exact request/evidence/preview approval and one atomic commit.
Files/evidence/profile identities are loaded before locks. Lock and statement waits
are bounded. Errors, serialization failures and uncertain acknowledgements do not
authorize automatic retry. Exact replay refuses; read-only inspection can identify
the committed operation. An absent receipt is not proof of rollback.

## Protected knowledge and readers

Transaction Y is a dedicated READ COMMITTED read-write issuer. It derives state,
top-level xid8 and availability from the server after observing committed state,
then commits the protected append-only receipt. A provisional locator is unusable.
No HMAC, key, pgcrypto, caller timestamp or commit-timestamp dependency exists.
SHA-256 identifies canonical bytes; protected privileges establish authenticity.

Transaction Z is a dedicated READ COMMITTED read-only typed gateway, under the
shared identity gate. It verifies the committed receipt, endpoint/system/database/
boot/authority/software/catalog identity, current correction/034/035/topology/fences,
body integrity and `available_at <= original cutoff <= DB current time`. Data and
proof state are materialized in one internal snapshot, including empty results.
RR/SERIALIZABLE, v2-only GUCs, arbitrary SQL, raw joins and receipt swapping refuse.
Compatible v1/v2 children are derived from the protected receipt, not supplied by
the caller. No historical as-of reconstruction is implemented.

A cutoff before receipt availability refuses current corrected-time features,
H-1, markets and training. Never silently substitute either old or new time into
a historical run. Stored historical NULL/v1/v2 metadata retain their meanings.

The schema/table owner, read-definer owner and write-definer owner must be distinct
restricted non-login principals. Four explicit client principals have separate
reader, issuer, operator and raw scopes. No production role names are provisioned.
Registration blocks unsafe memberships, raw/auxiliary namespace privileges,
creation/shadowing, privileged built-ins and unknown privileged callables. The
catalog pin includes non-temp schema/function metadata and parameter ACLs.
Namespace isolation is separately provisioned; registration does not silently
revoke shared/NFL permissions. Unsafe effective isolation blocks cutover.

## Application boundaries

`CertifiedReader` supplies fixed-cutoff game, next-game, slate/deadline, team200,
starter50, bullpen, independent H-1, completeness, market and audit adapters.
Legacy time-sensitive MLB repositories reject schema036 before business reads.
Generic empty legacy no-data helpers are not schema036 run/time certification.

The canonical earliest-start/deadline reader retains the existing requirement for
an `mlb_stats` game-source mapping. An earlier unmapped physical/provider row cannot
set that deadline, including in an otherwise empty window. This does not change
the existing physical-row semantics of game, next-game or slate reads.

The explicit certified moneyline adapter accepts precollected schedule evidence,
prepared canonical starter claims and an already loaded model package. It does
not call providers, discover credentials/models, synchronize identities, repair
history or activate the old workflow. It requires exact retained-slate agreement,
both uniquely mapped starters and independent H-1 PASS before model invocation or
run reservation. All reads, prediction admission and completion use the same
original receipt/cutoff. A later ordinary failure retains immutable partial
evidence under a failed run; an uncertain commit requires inspection only.
No successful empty card may hide a retained canonical slate.

Run reservation also binds the canonical target-date slate, exact participant/source
rows and monotonic game fences into the immutable server-derived companion.
Prediction admission and successful completion revalidate that same companion at
the original cutoff. The unchanged034 guard advances a target fence once for each
prediction INSERT; only this run's own persisted inserts are accounted for. Any
other advance invalidates admission even when a changed timestamp is restored.
Target identities/fences remain locked through finalization. Neither completion
nor another status writer may replace the receipt, move the cutoff, rewrite inputs
or adopt a later target state. Failed/held outcomes remain separately recordable.
Every certified prediction must already belong to that immutable admitted slate.
An empty bound slate permits no predictions. Insertion never adds a target or
adopts later evidence, and successful finalization independently refuses any
persisted prediction outside the bound slate.
Prediction insertion and completion serialize on the same run-row lock before
target/fence locks. A waiting insertion reads the latest locked run state and
refuses a terminal run; it cannot rely on a pre-wait `running` observation.

Arbitration evidence includes `origin_metadata.json` and `source_chain.zip` beside
the raw schedule. Raw metadata identity, exact endpoint/payload/byte count,
acquisition fields and every source-chain manifest entry are validated and bound
into the private audit request. Isolated metadata is explicitly synthetic and
cannot be used natively. The fixed native case admits only the retained reviewed
July payload/acquisition-chain identities. These checks prove byte identity and
consistency, not cryptographic provider authenticity or fresh native approval;
the separate pre-cutover acquisition/approval gates remain mandatory. Every
surrounding schedule record is validated, and sub-microsecond timestamp text
refuses rather than being truncated into the exact policy.

R/F/D/L/W and deliberate S/E/A/I exclusions are preserved. Unknown/malformed game
types fail closed. An all-conditional/unconfirmed postseason date deliberately
fails/defer rather than becoming a successful empty preview/card.

Old prediction/ingestion/recovery/reconciliation workflows remain exact035 clients
and refuse schema036. Historical completed-game extraction refuses036 because it
cannot certify earlier historical cutoffs. Legacy market evaluation also refuses
before reads/providers/writes; a successor certified analysis writer is not yet
implemented. Remaining default market/explanation/movement/preview analysis paths
must not be treated as certified036 inputs. Restricted client ACLs deny their raw
public reads; consumer closure remains an acceptance gate, not a waived requirement.

Raw operator/forensic inspection is explicitly `RAW_FORENSIC` /
`NOT_HISTORICALLY_CERTIFIED`. It cannot certify feature completeness, authorize a
retry or publish a run. Four scoped certified feature-audit checks do not assert
full training readiness.

## Canonical identity and business preservation

Fixed-case admission rejects known doubleheader/non-first-game metadata on either
physical row. Previously admitted legacy NULL metadata remains allowed only under
the unchanged affirmative single-event proof and full identity checks. The exact
reviewed case requires all twelve survivor pitching appearances in addition to
unchanged035's individual player/source, starter, sequential-appearance, metric
and availability checks; this is not a general pitching-count policy for MLB.

The version1 codec uses typed length-framed binary values, raw UTF8 key sorting,
signed timestamp microseconds, unsigned xid8 and raw32-byte digests. Floats,
duplicate/unknown schemas, malformed dates/timestamps, overflow and excess
depth/body/cardinality refuse. Correction-state and receipt-body hashes have
distinct domains and exclude their own computed fields.

Business pre/post digests are framed with the BUSINESS_STATE:v1 domain and bind
complete fixed-case identity/history/stats/market/legacy/observation, team/player,
ingestion-run/book/source and033 correction provenance. NUMERIC line values are
exact decimal strings; legacy timestamp semantics are explicit UTC. Historical
`game_date` is framed as an official DATE rather than an instant, without changing
the retained audit field or business row. Deferred completeness independently
recomputes hashes and verifies the sole permitted business diff.

After the audit, subject-source ingress is sealed for both new INSERTs and UPDATE
remaps from unrelated sources. Original source anchors retain their existing exact
update/delete seals; no new retirement/disposition is activated by these seals.

## Remaining acceptance work

Component/unit successes are not full scenario PASS or final-suite evidence.
Concurrency barriers, fault/uncertain-commit adverses, restart/physical-clone/
restore/HA, all dependency and privilege mutations, complete consumer closure,
frozen034/035 and full shared/NFL regressions, and performance measurements remain
mandatory. No production health, deployment readiness or performance is inferred
from an isolated fixture or source inspection. Inference/publication stay held.
