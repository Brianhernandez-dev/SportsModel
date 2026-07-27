-- Migration 009
-- Create canonical baseball player identities and external source mappings.

CREATE TABLE baseball_players (
    baseball_player_id BIGSERIAL PRIMARY KEY,

    full_name VARCHAR(150) NOT NULL,

    bats VARCHAR(10),
    throws VARCHAR(10),

    primary_position VARCHAR(50),

    active_from DATE,
    active_through DATE,

    is_active BOOLEAN NOT NULL DEFAULT TRUE,

    last_synced_at TIMESTAMPTZ,

    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT chk_baseball_players_bats
        CHECK (bats IS NULL OR bats IN ('L', 'R', 'S')),

    CONSTRAINT chk_baseball_players_throws
        CHECK (throws IS NULL OR throws IN ('L', 'R')),

    CONSTRAINT chk_baseball_players_active_dates
        CHECK (
            active_from IS NULL
            OR active_through IS NULL
            OR active_through >= active_from
        )
);

CREATE TABLE baseball_player_sources (
    baseball_player_source_id BIGSERIAL PRIMARY KEY,

    baseball_player_id BIGINT NOT NULL
        REFERENCES baseball_players (baseball_player_id)
        ON DELETE CASCADE,

    source_name VARCHAR(50) NOT NULL,

    external_player_id VARCHAR(100) NOT NULL,

    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT uq_baseball_player_source
        UNIQUE (source_name, external_player_id),

    CONSTRAINT uq_baseball_player_source_per_player
        UNIQUE (baseball_player_id, source_name)
);

CREATE INDEX idx_baseball_player_sources_player_id
ON baseball_player_sources (baseball_player_id);

CREATE INDEX idx_baseball_players_full_name
ON baseball_players (full_name);

CREATE INDEX idx_baseball_players_is_active
ON baseball_players (is_active);