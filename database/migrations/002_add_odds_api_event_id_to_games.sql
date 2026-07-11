-- Migration 002
-- Purpose:
-- Store The Odds API event identifier separately from MLB's official gamePk.

ALTER TABLE games
ADD COLUMN IF NOT EXISTS odds_api_event_id TEXT;

CREATE UNIQUE INDEX IF NOT EXISTS idx_games_odds_api_event_id
ON games (odds_api_event_id)
WHERE odds_api_event_id IS NOT NULL;