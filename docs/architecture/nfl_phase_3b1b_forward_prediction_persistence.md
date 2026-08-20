# NFL Phase 3B1-B: immutable forward prediction persistence

Phase 3B1-B stores pregame NFL Moneyline predictions as durable forward
evidence beginning with the 2026 season. It does not add odds, wagering,
settlement, outcome evaluation, scheduling, or model changes.

## Runs and idempotency

Each invocation uses an explicit UTC half-open slate window and records an
NFL-specific run. A caller-retained UUID `run_key` binds the request, slate,
routing contract, and both frozen artifact identities. Repeating a completed
identical key returns that completed run. A mismatched key is rejected. A
failed key is never silently reused; an intentional retry needs a new key. A
running key is recoverable only when it has no committed children.

The small `running` audit row is committed before prediction work so a failure
can be retained. The authoritative slate selection, all history reads, all
inferences, all child inserts, and completion occur in one `REPEATABLE READ`
transaction. Any target failure rolls back the entire child set; the run is
then marked failed in a separate transaction.

The database permits only an empty `running` row to be inserted. Run request,
slate, and artifact identity is immutable after insertion; source-snapshot
identity is sealed by the one-way completion transition.
Completion counts the actual child rows and requires that count to equal both
the recorded target and prediction counts. A failed run must have no children.
Child rows must repeat their parent's run identity, use the parent's season,
fall inside its half-open slate window, and use the transaction source snapshot
that is recorded on the parent at completion.

Same-key serialization failures and deadlocks are retried by a narrow wrapper
for at most three total attempts. Each attempt starts the full state machine
again and re-reads the durable run state. Other errors are never retried, and a
losing concurrent worker does not mark the winning worker's healthy run failed.

## Official and preview observations

For an evaluation protocol and canonical game, the database permits exactly
one `official` prediction. That first completed observation is the future
scored evidence and is never replaced because data or circumstances change.
Additional intentional observations use `preview`; each remains a separate
append-only row.

An official run must select at least one target. The service rejects an empty
official slate before creating a run, and the database independently rejects
an official run with `target_count = 0`. Preview runs and dry runs may represent
an empty slate; dry runs always write nothing.

Prediction rows reject `UPDATE` and `DELETE`, parent deletion is rejected, and
all evidence foreign keys use `ON DELETE RESTRICT`. There is no prediction
upsert path.

## Pregame and point-in-time proof

The database trigger replaces any caller timestamp with `clock_timestamp()`
and requires `prediction_created_at < target_kickoff`. It locks and verifies
the canonical game still exists, is unplayed, and has the exact persisted
kickoff, participants, season, and neutral-site identity. Service preflight
also checks every selected target with database time; the trigger remains the
final authority.

The canonical NFL row and its game row are held with PostgreSQL `FOR SHARE`
locks until the prediction transaction commits. This is the minimum row-level
lock used here that conflicts with ordinary `UPDATE` (`FOR NO KEY UPDATE`), so
kickoff, participant, neutral-site, and status changes cannot pass between
verification and commit.

Feature history is read through the same transaction cursor as slate and
prediction persistence. Each row stores the exact ordered feature names and
values, Phase A feature-vector hash, route and routing counts, selected frozen
model/specification/schema identity, probability, frozen route baseline,
threshold, and predicted side.

The exact source trace distinguishes early current-season routing history,
early prior-season regular-season model history, and mature combined routing
and model history. It retains canonical source game IDs, UTC kickoffs,
season/type identity, deterministic newest-first order, a per-game trace hash,
and latest source kickoff. Aggregate slate, source snapshot, and completed
prediction-set hashes use deterministic UTC JSON serialization.

Probability-like values are canonicalized at the persistence boundary as
decimal values quantized to exactly 16 fractional places with decimal
`ROUND_HALF_EVEN`. The persisted `NUMERIC(18,16)` value, predicted side, and
prediction-set fingerprint all use that same canonical value. Fingerprints
serialize it as a fixed-width decimal string (for example,
`0.0523316383502806`), so an audit can reproduce the hash from persisted rows
without access to the original binary float.

## Operation

Use `scripts/predict_nfl_moneyline.py` with `--season`, explicit UTC
`--slate-start` and `--slate-end`, exactly one of `--official` or `--preview`,
and a UUID `--run-key`. Add `--dry-run` to select, route, infer, and display the
slate while performing zero writes; a dry run does not require a run key.

The public service entry point and CLI always use the committed artifact
loaders and inference implementation. Dependency injection remains available
only through an explicitly internal service entry point used by tests. The
database additionally pins the current protocol to the exact routing,
specification, schema, and model fingerprints.

This phase intentionally contains no result or outcome columns. The immutable
2026+ observations are the evidence base for a later, separately designed
forward-evaluation phase.
