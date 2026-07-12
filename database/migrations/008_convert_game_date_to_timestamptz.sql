-- Migration 008
-- Store canonical game start times as timezone-aware timestamps.
-- Existing game_date values represent UTC and must retain the same instant.

ALTER TABLE games
ALTER COLUMN game_date
TYPE TIMESTAMPTZ
USING game_date AT TIME ZONE 'UTC';
