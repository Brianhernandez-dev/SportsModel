-- Migration 032
-- Retain multiple immutable Odds API event IDs for one canonical MLB game
-- when a provider replaces an event after an authoritative reschedule.

DROP INDEX idx_game_sources_game_id_source_name;

CREATE UNIQUE INDEX uq_game_sources_game_id_non_odds_source
ON game_sources (
    game_id,
    source_name
)
WHERE source_name <> 'odds_api';

CREATE INDEX idx_game_sources_game_id_source_name
ON game_sources (
    game_id,
    source_name
);

COMMENT ON INDEX idx_game_sources_game_id_source_name IS
    'Lookup index; multiple immutable event IDs from one source may reference '
    'one canonical game after a provider event replacement.';

COMMENT ON INDEX uq_game_sources_game_id_non_odds_source IS
    'Retains one-event-per-source protection for sources other than Odds API.';
