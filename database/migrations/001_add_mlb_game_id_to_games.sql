-- Migration 001
-- Purpose:
-- Add MLB's official game identifier to the canonical games table.
-- This allows odds, results, predictions, and future features to connect
-- through one stable game identity.

ALTER TABLE games
ADD COLUMN IF NOT EXISTS mlb_game_id BIGINT;

CREATE UNIQUE INDEX IF NOT EXISTS idx_games_mlb_game_id
ON games (mlb_game_id)
WHERE mlb_game_id IS NOT NULL;