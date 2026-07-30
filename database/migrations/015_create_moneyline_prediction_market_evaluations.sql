CREATE TABLE moneyline_prediction_market_evaluations (
    moneyline_prediction_market_evaluation_id BIGSERIAL
        PRIMARY KEY,

    moneyline_game_prediction_id BIGINT NOT NULL
        REFERENCES moneyline_game_predictions (
            moneyline_game_prediction_id
        )
        ON DELETE CASCADE,

    odds_ingestion_run_id BIGINT NOT NULL
        REFERENCES odds_ingestion_runs (
            odds_ingestion_run_id
        )
        ON DELETE CASCADE,

    odds_market_snapshot_id BIGINT NOT NULL
        REFERENCES odds_market_snapshots (
            odds_market_snapshot_id
        )
        ON DELETE CASCADE,

    sportsbook_id INTEGER NOT NULL
        REFERENCES sportsbooks (
            sportsbook_id
        ),

    snapshot_time TIMESTAMPTZ NOT NULL,

    selection_name VARCHAR(255) NOT NULL,

    price INTEGER NOT NULL,

    model_probability NUMERIC(12, 10) NOT NULL,

    market_no_vig_probability NUMERIC(12, 10) NOT NULL,

    sportsbook_count INTEGER NOT NULL,

    implied_probability NUMERIC(12, 10) NOT NULL,

    model_market_edge NUMERIC(12, 10) NOT NULL,

    model_price_edge NUMERIC(12, 10) NOT NULL,

    model_expected_value NUMERIC(12, 10) NOT NULL,

    starter_coverage VARCHAR(16) NOT NULL,

    home_starter_features_available BOOLEAN NOT NULL,

    away_starter_features_available BOOLEAN NOT NULL,

    policy_version VARCHAR(50) NOT NULL,

    qualifies_as_paper_candidate BOOLEAN NOT NULL,

    disqualification_reasons TEXT[] NOT NULL
        DEFAULT ARRAY[]::TEXT[],

    evaluated_at TIMESTAMPTZ NOT NULL
        DEFAULT NOW(),

    created_at TIMESTAMPTZ NOT NULL
        DEFAULT NOW(),

    CONSTRAINT uq_moneyline_prediction_market_evaluation
        UNIQUE (
            moneyline_game_prediction_id,
            odds_ingestion_run_id,
            policy_version
        ),

    CONSTRAINT chk_moneyline_evaluation_selection_name
        CHECK (
            BTRIM(selection_name) <> ''
        ),

    CONSTRAINT chk_moneyline_evaluation_price
        CHECK (
            price <> 0
        ),

    CONSTRAINT chk_moneyline_evaluation_model_probability
        CHECK (
            model_probability >= 0
            AND model_probability <= 1
        ),

    CONSTRAINT chk_moneyline_evaluation_market_probability
        CHECK (
            market_no_vig_probability >= 0
            AND market_no_vig_probability <= 1
        ),

    CONSTRAINT chk_moneyline_evaluation_implied_probability
        CHECK (
            implied_probability >= 0
            AND implied_probability <= 1
        ),

    CONSTRAINT chk_moneyline_evaluation_model_market_edge
        CHECK (
            model_market_edge >= -1
            AND model_market_edge <= 1
        ),

    CONSTRAINT chk_moneyline_evaluation_model_price_edge
        CHECK (
            model_price_edge >= -1
            AND model_price_edge <= 1
        ),

    CONSTRAINT chk_moneyline_evaluation_expected_value
        CHECK (
            model_expected_value >= -1
        ),

    CONSTRAINT chk_moneyline_evaluation_sportsbook_count
        CHECK (
            sportsbook_count > 0
        ),

    CONSTRAINT chk_moneyline_evaluation_starter_coverage
        CHECK (
            starter_coverage IN (
                'both',
                'partial',
                'none'
            )
        ),

    CONSTRAINT chk_moneyline_evaluation_policy_version
        CHECK (
            BTRIM(policy_version) <> ''
        ),

    CONSTRAINT chk_moneyline_evaluation_qualification
        CHECK (
            qualifies_as_paper_candidate
            =
            (
                CARDINALITY(
                    disqualification_reasons
                ) = 0
            )
        )
);

CREATE INDEX idx_moneyline_evaluations_prediction
    ON moneyline_prediction_market_evaluations (
        moneyline_game_prediction_id
    );

CREATE INDEX idx_moneyline_evaluations_odds_run
    ON moneyline_prediction_market_evaluations (
        odds_ingestion_run_id
    );

CREATE INDEX idx_moneyline_evaluations_snapshot
    ON moneyline_prediction_market_evaluations (
        odds_market_snapshot_id
    );

CREATE INDEX idx_moneyline_evaluations_snapshot_time
    ON moneyline_prediction_market_evaluations (
        snapshot_time
    );

CREATE INDEX idx_moneyline_evaluations_paper_candidates
    ON moneyline_prediction_market_evaluations (
        snapshot_time,
        moneyline_game_prediction_id
    )
    WHERE qualifies_as_paper_candidate = TRUE;
