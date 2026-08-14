ALTER TABLE moneyline_prediction_runs
    ADD COLUMN run_type VARCHAR(16);

UPDATE moneyline_prediction_runs
SET run_type = 'official'
WHERE run_type IS NULL;

ALTER TABLE moneyline_prediction_runs
    ALTER COLUMN run_type SET DEFAULT 'official';

ALTER TABLE moneyline_prediction_runs
    ALTER COLUMN run_type SET NOT NULL;

ALTER TABLE moneyline_prediction_runs
    ADD CONSTRAINT chk_moneyline_prediction_runs_run_type
    CHECK (
        run_type IN (
            'official',
            'preview'
        )
    );

CREATE INDEX idx_moneyline_prediction_runs_type_date
    ON moneyline_prediction_runs (
        run_type,
        target_date,
        started_at
    );

COMMENT ON COLUMN moneyline_prediction_runs.run_type IS
    'official = scored forward-validation run; '
    'preview = informational early look only.';
