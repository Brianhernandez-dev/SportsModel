-- Migration 012
-- Prevent one source from mapping multiple external events to the same
-- canonical game.

CREATE UNIQUE INDEX IF NOT EXISTS
    idx_game_sources_game_id_source_name
ON game_sources (
    game_id,
    source_name
);
