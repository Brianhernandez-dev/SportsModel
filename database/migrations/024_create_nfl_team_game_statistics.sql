-- Migration 024
-- Canonical per-team, per-game NFL statistics and immutable source evidence.

CREATE TABLE nfl_team_game_statistics (
    nfl_team_game_statistics_id BIGSERIAL PRIMARY KEY,
    game_id INTEGER NOT NULL REFERENCES nfl_games(game_id) ON DELETE CASCADE,
    team_id INTEGER NOT NULL REFERENCES teams(team_id) ON DELETE RESTRICT,
    completions SMALLINT NOT NULL CHECK (completions >= 0),
    pass_attempts SMALLINT NOT NULL CHECK (pass_attempts >= 0),
    passing_yards SMALLINT NOT NULL,
    passing_touchdowns SMALLINT NOT NULL CHECK (passing_touchdowns >= 0),
    passing_interceptions SMALLINT NOT NULL CHECK (passing_interceptions >= 0),
    sacks_suffered SMALLINT NOT NULL CHECK (sacks_suffered >= 0),
    carries SMALLINT NOT NULL CHECK (carries >= 0),
    rushing_yards SMALLINT NOT NULL,
    rushing_touchdowns SMALLINT NOT NULL CHECK (rushing_touchdowns >= 0),
    fumbles_lost SMALLINT NOT NULL CHECK (fumbles_lost >= 0),
    penalties SMALLINT CHECK (penalties >= 0),
    penalty_yards SMALLINT CHECK (penalty_yards >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_nfl_team_game_statistics UNIQUE (game_id, team_id),
    CONSTRAINT uq_nfl_team_game_statistics_observation_reference
        UNIQUE (nfl_team_game_statistics_id, game_id, team_id),
    CONSTRAINT chk_nfl_team_game_statistics_completions
        CHECK (completions <= pass_attempts)
);

CREATE INDEX idx_nfl_team_game_statistics_team
    ON nfl_team_game_statistics(team_id, game_id);
CREATE INDEX idx_nfl_team_game_statistics_game
    ON nfl_team_game_statistics(game_id);

CREATE TABLE nfl_team_game_statistics_source_observations (
    nfl_team_game_statistics_source_observation_id BIGSERIAL PRIMARY KEY,
    nfl_ingestion_run_id BIGINT NOT NULL
        REFERENCES nfl_ingestion_runs(nfl_ingestion_run_id) ON DELETE RESTRICT,
    nfl_team_game_statistics_id BIGINT NOT NULL,
    game_id INTEGER NOT NULL REFERENCES nfl_games(game_id) ON DELETE RESTRICT,
    team_id INTEGER NOT NULL REFERENCES teams(team_id) ON DELETE RESTRICT,
    source_name VARCHAR(50) NOT NULL,
    external_game_id VARCHAR(100) NOT NULL,
    provider_team_external_id VARCHAR(100) NOT NULL,
    provider_opponent_external_id VARCHAR(100) NOT NULL,
    raw_payload JSONB NOT NULL,
    raw_row_sha256 CHAR(64) NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL,
    provider_updated_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT chk_nfl_team_stats_observation_sha256
        CHECK (raw_row_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT uq_nfl_team_stats_observation_per_run
        UNIQUE (nfl_ingestion_run_id, source_name, external_game_id,
                provider_team_external_id, raw_row_sha256),
    CONSTRAINT fk_nfl_team_stats_observation_canonical
        FOREIGN KEY (nfl_team_game_statistics_id, game_id, team_id)
        REFERENCES nfl_team_game_statistics (
            nfl_team_game_statistics_id, game_id, team_id) ON DELETE RESTRICT
);

CREATE INDEX idx_nfl_team_stats_observations_source
    ON nfl_team_game_statistics_source_observations(
        source_name, external_game_id, provider_team_external_id);
CREATE INDEX idx_nfl_team_stats_observations_canonical
    ON nfl_team_game_statistics_source_observations(game_id, team_id);
