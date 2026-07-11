-- Migration 003
-- Create canonical external game ID mapping table.

CREATE TABLE game_sources (
    game_source_id SERIAL PRIMARY KEY,

    game_id INTEGER NOT NULL
        REFERENCES games(game_id)
        ON DELETE CASCADE,

    source_name VARCHAR(50) NOT NULL,

    external_game_id VARCHAR(100) NOT NULL,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT uq_game_source
        UNIQUE (source_name, external_game_id)
);