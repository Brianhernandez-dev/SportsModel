-- Migration 010
-- Create external team source mappings and historical player-team assignments.

CREATE TABLE baseball_team_sources (
    baseball_team_source_id BIGSERIAL PRIMARY KEY,

    team_id INTEGER NOT NULL
        REFERENCES teams (team_id)
        ON DELETE CASCADE,

    source_name VARCHAR(50) NOT NULL,

    external_team_id VARCHAR(100) NOT NULL,

    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT uq_baseball_team_source
        UNIQUE (source_name, external_team_id),

    CONSTRAINT uq_baseball_team_source_per_team
        UNIQUE (team_id, source_name)
);

CREATE TABLE baseball_player_team_assignments (
    baseball_player_team_assignment_id BIGSERIAL PRIMARY KEY,

    baseball_player_id BIGINT NOT NULL
        REFERENCES baseball_players (baseball_player_id)
        ON DELETE CASCADE,

    team_id INTEGER NOT NULL
        REFERENCES teams (team_id)
        ON DELETE CASCADE,

    roster_status_code VARCHAR(10),
    roster_status_description VARCHAR(50),

    jersey_number VARCHAR(10),

    position_code VARCHAR(10),
    position_name VARCHAR(50),

    valid_from DATE NOT NULL DEFAULT CURRENT_DATE,
    valid_through DATE,

    is_current BOOLEAN NOT NULL DEFAULT TRUE,

    last_synced_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT chk_baseball_player_team_assignment_dates
        CHECK (
            valid_through IS NULL
            OR valid_through >= valid_from
        ),

    CONSTRAINT chk_baseball_player_team_assignment_current
        CHECK (
            is_current = TRUE
            OR valid_through IS NOT NULL
        )
);

CREATE INDEX idx_baseball_team_sources_team_id
ON baseball_team_sources (team_id);

CREATE INDEX idx_baseball_player_team_assignments_player_id
ON baseball_player_team_assignments (baseball_player_id);

CREATE INDEX idx_baseball_player_team_assignments_team_id
ON baseball_player_team_assignments (team_id);

CREATE INDEX idx_baseball_player_team_assignments_current_team
ON baseball_player_team_assignments (team_id, is_current);

CREATE UNIQUE INDEX uq_baseball_player_current_team_assignment
ON baseball_player_team_assignments (baseball_player_id)
WHERE is_current = TRUE;