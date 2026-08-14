-- Add an explicit previous-night market refresh for the next MLB slate.
--
-- late_night is intentionally distinct from near_close:
--   late_night = previous evening actionable market refresh
--   near_close = same-day market used toward closing-line analysis

ALTER TABLE odds_ingestion_runs
DROP CONSTRAINT chk_odds_ingestion_runs_snapshot_role;

ALTER TABLE odds_ingestion_runs
ADD CONSTRAINT chk_odds_ingestion_runs_snapshot_role
CHECK (
    snapshot_role IN (
        'legacy',
        'manual',
        'opening',
        'late_night',
        'morning',
        'entry',
        'afternoon',
        'near_close'
    )
);

ALTER TABLE odds_ingestion_runs
DROP CONSTRAINT chk_odds_ingestion_runs_scheduled_target_date;

ALTER TABLE odds_ingestion_runs
ADD CONSTRAINT chk_odds_ingestion_runs_scheduled_target_date
CHECK (
    snapshot_role NOT IN (
        'opening',
        'late_night',
        'morning',
        'entry',
        'afternoon',
        'near_close'
    )
    OR target_date IS NOT NULL
);

DROP INDEX uq_odds_ingestion_runs_active_scheduled_snapshot;

CREATE UNIQUE INDEX uq_odds_ingestion_runs_active_scheduled_snapshot
ON odds_ingestion_runs (
    target_date,
    snapshot_role
)
WHERE snapshot_role IN (
    'opening',
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

COMMENT ON COLUMN odds_ingestion_runs.snapshot_role IS
    'Logical market capture role. late_night is the previous-evening '
    'refresh for the next slate and is distinct from near_close.';
