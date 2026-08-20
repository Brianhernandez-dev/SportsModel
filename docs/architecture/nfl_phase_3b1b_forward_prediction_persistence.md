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

## Official and preview observations

For an evaluation protocol and canonical game, the database permits exactly
one `official` prediction. That first completed observation is the future
scored evidence and is never replaced because data or circumstances change.
Additional intentional observations use `preview`; each remains a separate
append-only row.

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

## Operation

Use `scripts/predict_nfl_moneyline.py` with `--season`, explicit UTC
`--slate-start` and `--slate-end`, exactly one of `--official` or `--preview`,
and a UUID `--run-key`. Add `--dry-run` to select, route, infer, and display the
slate while performing zero writes; a dry run does not require a run key.

This phase intentionally contains no result or outcome columns. The immutable
2026+ observations are the evidence base for a later, separately designed
forward-evaluation phase.
