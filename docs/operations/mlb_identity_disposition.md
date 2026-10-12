# MLB stale-identity disposition implementation 1.1.0

Successor notice: current development candidate requires exact schema035 and a
V2 executable operator envelope. The frozen034 component described below remains
unchanged; it is not the combined retirement contract. See
[legacy retirement successor](mlb_legacy_identity_retirement.md). No release or
production authority follows from this notice.

DEVELOPMENT / independent review only. No production migration, preview,
activation, provider access, deployment, inference or publication is authorized.
Production operational health is unverified. The approved 1.0.0 design is not
executable; other suspect production pairs are outside this implementation.

## Persistence and active/raw contract

Migration 034 adds immutable MLB cases, append-only ACTIVATE/REVOKE events and
monotonic fences. Migrations 001–033 are unchanged. Distinct positive subject and
fixed survivor have RESTRICT foreign keys; one case per subject, only
STALE_MARKET_ONLY_DUPLICATE / policy 1.0.0. A deferred constraint requires initial
ACTIVATE in the case transaction. Events are contiguous, alternate action, and
use same-case predecessors. Forks, active chains/cycles and retargeting refuse.
DB timestamps reject caller backdating. UPDATE/DELETE/TRUNCATE refuse even for
owners. Runtime roles need SELECT-only ledger/fence grants; isolated tests use
representative restricted grants, not observed production role configuration.

The active view/repository expose subject, fixed survivor, case/latest event,
sequence, policy and ledger fingerprint. Active lookup refuses a stale subject
without redirect. raw_identity returns the physical row, latest action including
REVOKE, RAW_FORENSIC label and explicitly unverified active eligibility. Live
entry verifies exact 001–034 checksums, actual function bodies/attributes and
enabled trigger bindings before providers/reservations. Incompatibility refuses.

## Gate, fences and cross-sport coupling

Transaction advisory gate `(1397574724, 34)` is EXCLUSIVE for disposition and
SHARED for covered writers before eligibility reads/mutations. Promotion refuses.
Order: gate, ascending games/fences, case, dependent rows. Epochs advance in game
order, never reset/delete/overflow. Old SERIALIZABLE/REPEATABLE READ snapshots
conflict with changed fence rows, not certify stale state. Operator execution is
SERIALIZABLE without automatic retry. Gate entry caps lock timeout at 5 seconds
and statement timeout at 30 seconds, retaining shorter settings; CLI connections
set these before their first statement. Multi-statement callers must retain
deterministic order. Serialization/deadlock/timeout errors refuse, never retry.

Shared-table BEFORE STATEMENT guards also gate unrelated writes: games/sources,
teams/MLB sources, sportsbooks/provider identities, ingestion runs, observations,
snapshots, 033 corrections, results/history/statistics and decision tables.
Optional legacy model_predictions/odds_snapshots are guarded if present. No NFL
table guards or NFL code changes. Unrelated rows acquire SHARED but receive no
MLB disposition semantics or fences. EXCLUSIVE can temporarily delay unrelated
writes: this global coupling is intentional. Synthetic evidence measures waiting,
row equality, fence absence and timeout behavior, not production performance.

## H-1 and PIT knowledge

Stale exclusion occurs before the retained 200-game team and 50-start windows.
Survivor and undisposed/source-less games remain required. Incomplete survivor
history still fails H-1. Prohibited stale history is an invariant error, not hidden.
Orientation, feature math, cutoff rules and actual created_at semantics remain.

Once a ledger case exists, readiness requires a committed capture from a fresh,
separate READ ONLY transaction. Its in-process sealed object binds ledger hash,
actual availability and artifact hash; availability must not exceed cutoff.
Current capture cannot certify Oct 8 or any older cutoff. Independent feature
connections install/recheck the same proof; later ACTIVATE/REVOKE invalidates it.
The seal protects ordinary application admission, not hostile owners/arbitrary
SQL settings. It is not an externally signed historical proof; restored
cross-process artifacts are not admitted. Callers without proof fail closed,
not shift cutoff. Existing run metadata remains NULL; 034 adds nullable constrained
knowledge metadata. No old cards/performance are reconstructed. Later repair
retains real insertion time and is unavailable before that time.

## Matching and consumers

Default ACTIVE_EVENT excludes stale subjects before new-candidate counts and
same-date fallback. Existing ambiguity/doubleheader/tolerance checks remain.
Only explicit RAW_ACQUISITION_CONTINUITY for an exact existing Odds ID and
baseball_mlb domain admits a stale subject, checking orientation/source. It returns
subject, never survivor, without refreshing stored time. Stale MLB mappings refuse.
Deadline, retained slate, upcoming, schedule/results, boxscore, completeness and
feature consumers enforce active eligibility. Retained-slate zero-prediction
protection remains. All-conditional ifNecessary dates intentionally fail/defer,
not become successful empty cards. R/F/D/L/W, strict envelope/date and TBD remain.

Reconciliation preview format 2 binds physical competitors, sources, ledger,
fences, schema and code. Only an active clean oriented case whose fixed survivor
equals target permits that specific split exception; other splits refuse.
Recovery successor is format 2 /
final-championship-or-explicit-exclusion-v4-disposition-034. Old preview/recovery-v3
approval bytes refuse, never relabel. Stale targets refuse, never translate;
survivor still needs unique MLB identity plus existing absence/correctness/PIT
checks. No production reconciliation or recovery was executed.

## Betting and raw provenance

Application guards precede authoritative writes; DB guards cover direct game
and indirect prediction/evaluation/snapshot links. Survivor prediction using
stale snapshot evidence refuses. Stale results/history/statistics, predictions,
evaluations and settlements refuse. Retained game/Odds source/observations,
prices/lines/snapshots/ingestion linkage are not merged, retimed or deleted.
Validated future raw appends stay on subject. Case-linked raw identities cannot
retarget even after REVOKE. Ingestion lifecycle counters may complete without
changing identity/time provenance. Migration 033/effective odds remain separate:
no disposition join transfers subject prices to survivor. Synthetic evidence
records raw/effective-033 and betting equality before/after activation.

## Operator and uncertain commit

scripts/mlb_identity_disposition_operator.py exposes preview, activate,
revoke-reviewed and read-only receipt. Explicit target/read acknowledgement and
non-echoing, non-persistent password are required. No .env/argv discovery/provider
calls. Fresh JSON output must be outside both checkouts. Libraries require an
explicit connection factory. No production invocation occurred.

MLB_IDENTITY_DISPOSITION_EXECUTABLE_V1 binds exact pair, official single confirmed
MLB payload, date/start/orientation, source/observation/snapshot IDs, evidence
ZIP/hash, policy, audit identity and current reviewed base commit. DESIGN_ONLY,
unknown fields and unresolved doubleheaders refuse. READ ONLY preview binds full
JSON-text rows (decimal prices included), dependency/FK inventory, competitors,
ledger/fences, schema, source fingerprint and deterministic body hash. Inputs
and row-review scope are bounded; unexpected FK inventory refuses.

Execution requires exact reviewed preview hash and separate write acknowledgement.
Optional exact survivor MLB anchor additionally requires explicit request and
anchor acknowledgement. EXCLUSIVE revalidation precedes one transaction's
optional anchor, case, event and immutable receipt. Pre-commit faults roll back
all state. Exact replay returns original receipt without another event; changed
pair/ledger refuses. Receipt seals full pair and ledger fingerprints; event
post_state_sha256 is the logical transition hash, not a full database-state hash.
Lost commit acknowledgement or output failure after commit is UNKNOWN: inspect
exact receipt read-only before any retry. Inspection never authorizes retry.
REVOKE requires explicit reviewed reversal, fresh evidence and full checks;
survivor history/decisions refuse it. Reactivation needs new evidence. No retarget.

## Remaining review boundary

The package retains frozen hashes, exact offline outputs, isolated PG16 migration
and catalog evidence, concurrency/rollback/PIT checks, raw/033/betting equality
and protected-path checks. Fresh synthetic DB uses host port 55446, never host
5432 or database sportsmodel. No real production authorization was created.
Independent implementation review, production schema/roles verification and
separate operational authority remain required. Production was not modified.
