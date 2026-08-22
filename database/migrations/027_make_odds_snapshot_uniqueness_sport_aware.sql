-- Migration 027
-- Make scheduled odds-ingestion identity sport-safe without changing
-- existing MLB role or manual-run semantics.

DROP INDEX uq_odds_ingestion_runs_active_scheduled_snapshot;

CREATE UNIQUE INDEX
    uq_odds_ingestion_runs_active_scheduled_snapshot
ON odds_ingestion_runs (
    sport,
    target_date,
    snapshot_role
)
WHERE snapshot_role IN (
    'opening',
    'evening',
    'late_night',
    'morning',
    'entry',
    'afternoon',
    'near_close'
)
AND status IN (
    'running',
    'completed'
);

COMMENT ON INDEX
    uq_odds_ingestion_runs_active_scheduled_snapshot IS
    'At most one running or completed scheduled odds capture per '
    'sport, target date, and snapshot role. Manual and failed runs '
    'remain repeatable.';
