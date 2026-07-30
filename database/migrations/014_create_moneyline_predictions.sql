-- Migration 014
-- Create persistent MLB Moneyline prediction runs and prediction snapshots.

CREATE TABLE moneyline_prediction_runs (
    moneyline_prediction_run_id BIGSERIAL PRIMARY KEY,

    target_date DATE NOT NULL,

    model_version VARCHAR(100) NOT NULL,
    feature_schema_version VARCHAR(50) NOT NULL,

    model_artifact_sha256 CHAR(64) NOT NULL,
    model_training_cutoff TIMESTAMPTZ,

    started_at TIMESTAMPTZ NOT NULL
        DEFAULT CURRENT_TIMESTAMP,

    completed_at TIMESTAMPTZ,

    status VARCHAR(20) NOT NULL
        DEFAULT 'running',

    games_received INTEGER NOT NULL
        DEFAULT 0,

    predictions_created INTEGER NOT NULL
        DEFAULT 0,

    games_skipped INTEGER NOT NULL
        DEFAULT 0,

    error_message TEXT,

    created_at TIMESTAMPTZ NOT NULL
        DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT chk_moneyline_prediction_runs_status
        CHECK (
            status IN (
                'running',
                'completed',
                'failed'
            )
        ),

    CONSTRAINT chk_moneyline_prediction_runs_counts
        CHECK (
            games_received >= 0
            AND predictions_created >= 0
            AND games_skipped >= 0
        ),

    CONSTRAINT chk_moneyline_prediction_runs_completion
        CHECK (
            (
                status = 'running'
                AND completed_at IS NULL
            )
            OR (
                status IN (
                    'completed',
                    'failed'
                )
                AND completed_at IS NOT NULL
            )
        ),

    CONSTRAINT chk_moneyline_prediction_runs_model_hash
        CHECK (
            model_artifact_sha256
            ~ '^[0-9a-f]{64}$'
        )
);


CREATE TABLE moneyline_game_predictions (
    moneyline_game_prediction_id BIGSERIAL PRIMARY KEY,

    moneyline_prediction_run_id BIGINT NOT NULL
        REFERENCES moneyline_prediction_runs (
            moneyline_prediction_run_id
        )
        ON DELETE CASCADE,

    game_id INTEGER NOT NULL
        REFERENCES games (game_id)
        ON DELETE CASCADE,

    mlb_game_id BIGINT,

    game_start_time TIMESTAMPTZ NOT NULL,

    prediction_time TIMESTAMPTZ NOT NULL,

    home_team_id INTEGER NOT NULL
        REFERENCES teams (team_id),

    away_team_id INTEGER NOT NULL
        REFERENCES teams (team_id),

    home_starting_pitcher_id BIGINT
        REFERENCES baseball_players (
            baseball_player_id
        ),

    away_starting_pitcher_id BIGINT
        REFERENCES baseball_players (
            baseball_player_id
        ),

    home_starting_pitcher_mlb_id BIGINT,

    away_starting_pitcher_mlb_id BIGINT,

    home_starter_features_available BOOLEAN NOT NULL,

    away_starter_features_available BOOLEAN NOT NULL,

    starter_coverage VARCHAR(20) NOT NULL,

    missing_raw_value_count INTEGER NOT NULL,

    home_win_probability NUMERIC(12, 10) NOT NULL,

    away_win_probability NUMERIC(12, 10) NOT NULL,

    predicted_team_id INTEGER NOT NULL
        REFERENCES teams (team_id),

    predicted_probability NUMERIC(12, 10) NOT NULL,

    created_at TIMESTAMPTZ NOT NULL
        DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT uq_moneyline_game_prediction_run_game
        UNIQUE (
            moneyline_prediction_run_id,
            game_id
        ),

    CONSTRAINT chk_moneyline_game_predictions_teams
        CHECK (
            home_team_id <> away_team_id
        ),

    CONSTRAINT chk_moneyline_game_predictions_prediction_time
        CHECK (
            prediction_time <= game_start_time
        ),

    CONSTRAINT chk_moneyline_game_predictions_missing_values
        CHECK (
            missing_raw_value_count >= 0
        ),

    CONSTRAINT chk_moneyline_game_predictions_probabilities
        CHECK (
            home_win_probability >= 0
            AND home_win_probability <= 1
            AND away_win_probability >= 0
            AND away_win_probability <= 1
            AND predicted_probability >= 0
            AND predicted_probability <= 1
            AND ABS(
                home_win_probability
                + away_win_probability
                - 1
            ) <= 0.0000001000
        ),

    CONSTRAINT chk_moneyline_game_predictions_predicted_team
        CHECK (
            (
                predicted_team_id = home_team_id
                AND predicted_probability
                    = home_win_probability
            )
            OR (
                predicted_team_id = away_team_id
                AND predicted_probability
                    = away_win_probability
            )
        ),

    CONSTRAINT chk_moneyline_game_predictions_starter_coverage
        CHECK (
            (
                starter_coverage = 'both'
                AND home_starting_pitcher_mlb_id
                    IS NOT NULL
                AND away_starting_pitcher_mlb_id
                    IS NOT NULL
            )
            OR (
                starter_coverage = 'partial'
                AND (
                    (
                        home_starting_pitcher_mlb_id
                            IS NOT NULL
                        AND away_starting_pitcher_mlb_id
                            IS NULL
                    )
                    OR (
                        home_starting_pitcher_mlb_id
                            IS NULL
                        AND away_starting_pitcher_mlb_id
                            IS NOT NULL
                    )
                )
            )
            OR (
                starter_coverage = 'none'
                AND home_starting_pitcher_mlb_id
                    IS NULL
                AND away_starting_pitcher_mlb_id
                    IS NULL
            )
        ),

    CONSTRAINT chk_moneyline_game_predictions_home_starter_mapping
        CHECK (
            (
                home_starting_pitcher_mlb_id IS NULL
                AND home_starting_pitcher_id IS NULL
            )
            OR (
                home_starting_pitcher_mlb_id IS NOT NULL
                AND home_starting_pitcher_id IS NOT NULL
            )
        ),

    CONSTRAINT chk_moneyline_game_predictions_away_starter_mapping
        CHECK (
            (
                away_starting_pitcher_mlb_id IS NULL
                AND away_starting_pitcher_id IS NULL
            )
            OR (
                away_starting_pitcher_mlb_id IS NOT NULL
                AND away_starting_pitcher_id IS NOT NULL
            )
        ),

    CONSTRAINT chk_moneyline_game_predictions_home_feature_availability
        CHECK (
            home_starter_features_available = FALSE
            OR home_starting_pitcher_id IS NOT NULL
        ),

    CONSTRAINT chk_moneyline_game_predictions_away_feature_availability
        CHECK (
            away_starter_features_available = FALSE
            OR away_starting_pitcher_id IS NOT NULL
        )
);


CREATE INDEX idx_moneyline_prediction_runs_target_date
ON moneyline_prediction_runs (
    target_date,
    started_at
);


CREATE INDEX idx_moneyline_prediction_runs_status
ON moneyline_prediction_runs (
    status,
    started_at
);


CREATE INDEX idx_moneyline_game_predictions_game
ON moneyline_game_predictions (
    game_id,
    prediction_time
);


CREATE INDEX idx_moneyline_game_predictions_run
ON moneyline_game_predictions (
    moneyline_prediction_run_id
);


CREATE INDEX idx_moneyline_game_predictions_prediction_time
ON moneyline_game_predictions (
    prediction_time
);
