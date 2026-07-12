BEGIN;

CREATE TABLE odds_ingestion_runs (
    odds_ingestion_run_id BIGSERIAL PRIMARY KEY,
    sport VARCHAR(50) NOT NULL,
    source_name VARCHAR(100) NOT NULL,
    started_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMPTZ,
    status VARCHAR(20) NOT NULL DEFAULT 'running',
    games_returned INTEGER,
    games_processed INTEGER,
    selections_inserted INTEGER,
    selections_skipped INTEGER,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT chk_odds_ingestion_runs_status
        CHECK (status IN ('running', 'completed', 'failed'))
);

ALTER TABLE odds_market_snapshots
ADD COLUMN odds_ingestion_run_id BIGINT;

-- Represent odds already collected before ingestion-run tracking existed.
WITH legacy_run AS (
    INSERT INTO odds_ingestion_runs (
        sport,
        source_name,
        started_at,
        completed_at,
        status,
        games_processed,
        selections_inserted,
        selections_skipped
    )
    SELECT
        'baseball_mlb',
        'legacy_backfill',
        MIN(snapshot_time),
        MAX(snapshot_time),
        'completed',
        COUNT(DISTINCT game_id),
        COUNT(*),
        0
    FROM odds_market_snapshots
    RETURNING odds_ingestion_run_id
)
UPDATE odds_market_snapshots
SET odds_ingestion_run_id = (
    SELECT odds_ingestion_run_id
    FROM legacy_run
)
WHERE odds_ingestion_run_id IS NULL;

ALTER TABLE odds_market_snapshots
ALTER COLUMN odds_ingestion_run_id SET NOT NULL;

ALTER TABLE odds_market_snapshots
ADD CONSTRAINT fk_odds_market_snapshots_ingestion_run
FOREIGN KEY (odds_ingestion_run_id)
REFERENCES odds_ingestion_runs (odds_ingestion_run_id);

CREATE INDEX idx_odds_market_snapshots_ingestion_run
ON odds_market_snapshots (odds_ingestion_run_id);

COMMIT;