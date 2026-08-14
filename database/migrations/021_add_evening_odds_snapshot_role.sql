-- Add the 8:30 PM supplemental snapshot for the next MLB slate.
--
-- Snapshot sequence:
--   opening    = 6:30 PM
--   evening    = 8:30 PM
--   late_night = 11:00 PM

ALTER TABLE odds_ingestion_runs
DROP CONSTRAINT chk_odds_ingestion_runs_snapshot_role;

ALTER TABLE odds_ingestion_runs
ADD CONSTRAINT chk_odds_ingestion_runs_snapshot_role
CHECK (
    snapshot_role IN (
        'legacy',
        'manual',
        'opening',
        'evening',
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
        'evening',
        'late_night',
        'morning',
        'entry',
        'afternoon',
        'near_close'
    )
    OR target_date IS NOT NULL
);

DROP INDEX uq_odds_ingestion_runs_active_scheduled_snapshot;

CREATE UNIQUE INDEX
    uq_odds_ingestion_runs_active_scheduled_snapshot
ON odds_ingestion_runs (
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

COMMENT ON COLUMN odds_ingestion_runs.snapshot_role IS
    'Logical market capture role. evening is the 8:30 PM '
    'supplemental next-slate snapshot between opening and '
    'late_night.';
