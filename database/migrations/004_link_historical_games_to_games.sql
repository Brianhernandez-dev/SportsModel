-- Migration 004
-- Link each historical MLB result to the canonical games table.

ALTER TABLE historical_games
ADD COLUMN IF NOT EXISTS game_id INTEGER;

ALTER TABLE historical_games
ADD CONSTRAINT fk_historical_games_game
FOREIGN KEY (game_id)
REFERENCES games(game_id)
ON DELETE CASCADE;

CREATE UNIQUE INDEX IF NOT EXISTS idx_historical_games_game_id
ON historical_games (game_id)
WHERE game_id IS NOT NULL;