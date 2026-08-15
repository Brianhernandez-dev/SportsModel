-- Migration 023
-- Canonical NFL schedule/result persistence with immutable provider evidence.

CREATE TABLE nfl_ingestion_runs (
    nfl_ingestion_run_id BIGSERIAL PRIMARY KEY,
    source_name VARCHAR(50) NOT NULL,
    source_asset TEXT NOT NULL,
    retrieved_at TIMESTAMPTZ NOT NULL,
    source_sha256 CHAR(64) NOT NULL,
    started_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMPTZ,
    status VARCHAR(20) NOT NULL DEFAULT 'running',
    rows_received INTEGER NOT NULL DEFAULT 0,
    rows_processed INTEGER NOT NULL DEFAULT 0,
    rows_inserted INTEGER NOT NULL DEFAULT 0,
    rows_updated INTEGER NOT NULL DEFAULT 0,
    rows_quarantined INTEGER NOT NULL DEFAULT 0,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT chk_nfl_ingestion_runs_status
        CHECK (status IN ('running', 'completed', 'failed')),
    CONSTRAINT chk_nfl_ingestion_runs_sha256
        CHECK (source_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT chk_nfl_ingestion_runs_counts CHECK (
        rows_received >= 0 AND rows_processed >= 0
        AND rows_inserted >= 0 AND rows_updated >= 0
        AND rows_quarantined >= 0
    )
);

CREATE TABLE nfl_games (
    game_id INTEGER PRIMARY KEY
        REFERENCES games(game_id) ON DELETE CASCADE,
    season INTEGER NOT NULL,
    season_type VARCHAR(20) NOT NULL,
    week SMALLINT NOT NULL,
    week_label VARCHAR(50) NOT NULL,
    scheduled_start_time TIMESTAMPTZ NOT NULL,
    neutral_site BOOLEAN NOT NULL DEFAULT FALSE,
    status VARCHAR(20) NOT NULL,
    home_score SMALLINT,
    away_score SMALLINT,
    overtime BOOLEAN,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT chk_nfl_games_season CHECK (season BETWEEN 1920 AND 2100),
    CONSTRAINT chk_nfl_games_season_type
        CHECK (season_type IN ('preseason', 'regular', 'postseason')),
    CONSTRAINT chk_nfl_games_week CHECK (week > 0),
    CONSTRAINT chk_nfl_games_status CHECK (status IN ('final', 'unplayed')),
    CONSTRAINT chk_nfl_games_scores CHECK (
        (status = 'final' AND home_score IS NOT NULL
            AND away_score IS NOT NULL AND overtime IS NOT NULL)
        OR
        (status = 'unplayed' AND home_score IS NULL
            AND away_score IS NULL AND overtime IS NULL)
    ),
    CONSTRAINT chk_nfl_games_nonnegative_scores CHECK (
        (home_score IS NULL OR home_score >= 0)
        AND (away_score IS NULL OR away_score >= 0)
    ),
    CONSTRAINT chk_nfl_games_postseason_tie CHECK (
        NOT (season_type = 'postseason' AND status = 'final'
            AND home_score = away_score)
    ),
    CONSTRAINT uq_nfl_games_identity
        UNIQUE (season, season_type, week, game_id)
);

CREATE INDEX idx_nfl_games_season
    ON nfl_games(season, season_type, week, scheduled_start_time);

CREATE TABLE nfl_game_source_observations (
    nfl_game_source_observation_id BIGSERIAL PRIMARY KEY,
    nfl_ingestion_run_id BIGINT NOT NULL
        REFERENCES nfl_ingestion_runs(nfl_ingestion_run_id) ON DELETE RESTRICT,
    game_id INTEGER
        REFERENCES nfl_games(game_id) ON DELETE RESTRICT,
    source_name VARCHAR(50) NOT NULL,
    external_game_id VARCHAR(100) NOT NULL,
    provider_home_external_team_id VARCHAR(100),
    provider_away_external_team_id VARCHAR(100),
    provider_gameday VARCHAR(20),
    provider_gametime VARCHAR(20),
    provider_game_type VARCHAR(20),
    provider_week VARCHAR(20),
    raw_payload JSONB NOT NULL,
    raw_row_sha256 CHAR(64) NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL,
    provider_updated_at TIMESTAMPTZ,
    anomaly_state VARCHAR(20) NOT NULL DEFAULT 'none',
    anomaly_reason TEXT,
    override_provenance TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT chk_nfl_observations_sha256
        CHECK (raw_row_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT chk_nfl_observations_anomaly_state
        CHECK (anomaly_state IN ('none', 'overridden', 'quarantined')),
    CONSTRAINT chk_nfl_observations_mapping CHECK (
        (anomaly_state = 'quarantined' AND game_id IS NULL)
        OR (anomaly_state <> 'quarantined' AND game_id IS NOT NULL)
    ),
    CONSTRAINT uq_nfl_observation_per_run
        UNIQUE (nfl_ingestion_run_id, source_name, external_game_id,
                raw_row_sha256)
);

CREATE INDEX idx_nfl_observations_source_identity
    ON nfl_game_source_observations(source_name, external_game_id);
CREATE INDEX idx_nfl_observations_game
    ON nfl_game_source_observations(game_id);
