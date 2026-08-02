CREATE TABLE moneyline_daily_workflow_runs (
    moneyline_daily_workflow_run_id BIGSERIAL
        PRIMARY KEY,

    target_date DATE NOT NULL
        UNIQUE,

    status VARCHAR(24) NOT NULL
        DEFAULT 'pending',

    current_stage VARCHAR(32) NOT NULL
        DEFAULT 'initialized',

    moneyline_prediction_run_id BIGINT
        REFERENCES moneyline_prediction_runs (
            moneyline_prediction_run_id
        ),

    odds_ingestion_run_id BIGINT
        REFERENCES odds_ingestion_runs (
            odds_ingestion_run_id
        ),

    odds_status_code INTEGER,

    odds_remaining_requests INTEGER,

    odds_used_requests INTEGER,

    attempt_count INTEGER NOT NULL
        DEFAULT 0,

    last_attempt_started_at TIMESTAMPTZ,

    last_attempt_completed_at TIMESTAMPTZ,

    pregame_completed_at TIMESTAMPTZ,

    settlement_completed_at TIMESTAMPTZ,

    error_message TEXT,

    created_at TIMESTAMPTZ NOT NULL
        DEFAULT CURRENT_TIMESTAMP,

    updated_at TIMESTAMPTZ NOT NULL
        DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT chk_moneyline_daily_workflow_status
        CHECK (
            status IN (
                'pending',
                'running',
                'awaiting_results',
                'completed',
                'failed'
            )
        ),

    CONSTRAINT chk_moneyline_daily_workflow_stage
        CHECK (
            current_stage IN (
                'initialized',
                'schedule_sync',
                'prediction',
                'odds_ingestion',
                'evaluation',
                'pregame_audit',
                'results_ingestion',
                'settlement',
                'final_audit',
                'complete'
            )
        ),

    CONSTRAINT chk_moneyline_daily_workflow_attempts
        CHECK (
            attempt_count >= 0
        ),

    CONSTRAINT chk_moneyline_daily_workflow_quota
        CHECK (
            (
                odds_remaining_requests IS NULL
                OR odds_remaining_requests >= 0
            )
            AND (
                odds_used_requests IS NULL
                OR odds_used_requests >= 0
            )
        ),

    CONSTRAINT chk_moneyline_daily_workflow_http_status
        CHECK (
            odds_status_code IS NULL
            OR odds_status_code BETWEEN 100 AND 599
        )
);

CREATE INDEX idx_moneyline_daily_workflow_status
    ON moneyline_daily_workflow_runs (
        status,
        target_date
    );

CREATE INDEX idx_moneyline_daily_workflow_prediction_run
    ON moneyline_daily_workflow_runs (
        moneyline_prediction_run_id
    );

CREATE INDEX idx_moneyline_daily_workflow_odds_run
    ON moneyline_daily_workflow_runs (
        odds_ingestion_run_id
    );
