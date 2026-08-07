-- Migration 018
-- Add logical snapshot identity and API quota metadata to odds runs.

ALTER TABLE odds_ingestion_runs
ADD COLUMN target_date DATE;

ALTER TABLE odds_ingestion_runs
ADD COLUMN snapshot_role VARCHAR(24);

ALTER TABLE odds_ingestion_runs
ADD COLUMN status_code INTEGER;

ALTER TABLE odds_ingestion_runs
ADD COLUMN remaining_requests INTEGER;

ALTER TABLE odds_ingestion_runs
ADD COLUMN used_requests INTEGER;

UPDATE odds_ingestion_runs
SET snapshot_role = 'legacy'
WHERE snapshot_role IS NULL;

-- Existing odds runs owned by the daily Moneyline workflow are the
-- official entry snapshots for their target dates. Preserve the quota
-- response metadata already stored by that workflow.
UPDATE odds_ingestion_runs AS ingestion
SET target_date = workflow.target_date,
    snapshot_role = 'entry',
    status_code = workflow.odds_status_code,
    remaining_requests = workflow.odds_remaining_requests,
    used_requests = workflow.odds_used_requests
FROM moneyline_daily_workflow_runs AS workflow
WHERE workflow.odds_ingestion_run_id
    = ingestion.odds_ingestion_run_id;

ALTER TABLE odds_ingestion_runs
ALTER COLUMN snapshot_role SET NOT NULL;

ALTER TABLE odds_ingestion_runs
ADD CONSTRAINT chk_odds_ingestion_runs_snapshot_role
CHECK (
    snapshot_role IN (
        'legacy',
        'manual',
        'opening',
        'morning',
        'entry',
        'afternoon',
        'near_close'
    )
);

ALTER TABLE odds_ingestion_runs
ADD CONSTRAINT chk_odds_ingestion_runs_scheduled_target_date
CHECK (
    snapshot_role NOT IN (
        'opening',
        'morning',
        'entry',
        'afternoon',
        'near_close'
    )
    OR target_date IS NOT NULL
);

ALTER TABLE odds_ingestion_runs
ADD CONSTRAINT chk_odds_ingestion_runs_status_code
CHECK (
    status_code IS NULL
    OR status_code BETWEEN 100 AND 599
);

ALTER TABLE odds_ingestion_runs
ADD CONSTRAINT chk_odds_ingestion_runs_quota
CHECK (
    (
        remaining_requests IS NULL
        OR remaining_requests >= 0
    )
    AND (
        used_requests IS NULL
        OR used_requests >= 0
    )
);

-- Reserve each scheduled logical snapshot before making the API call.
-- Failed attempts are excluded so they can be retried.
CREATE UNIQUE INDEX uq_odds_ingestion_runs_active_scheduled_snapshot
ON odds_ingestion_runs (
    target_date,
    snapshot_role
)
WHERE snapshot_role IN (
    'opening',
    'morning',
    'entry',
    'afternoon',
    'near_close'
)
AND status IN (
    'running',
    'completed'
);

CREATE INDEX idx_odds_ingestion_runs_snapshot_lookup
ON odds_ingestion_runs (
    target_date,
    snapshot_role,
    status,
    started_at
);
