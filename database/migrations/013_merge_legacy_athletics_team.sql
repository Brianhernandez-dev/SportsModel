-- Migration 013
-- Merge the legacy Oakland Athletics canonical team into Athletics.
--
-- Historical MLB schedule ingestion used the exact source display name,
-- which created team 41311 ("Oakland Athletics"). Current MLB data and
-- baseball statistics use team 5 ("Athletics").

DO $migration$
DECLARE
    canonical_team_name TEXT;
    legacy_team_name TEXT;
BEGIN
    SELECT team_name
    INTO canonical_team_name
    FROM teams
    WHERE team_id = 5;

    IF canonical_team_name IS DISTINCT FROM 'Athletics' THEN
        RAISE EXCEPTION
            'Expected team 5 to be Athletics; found %',
            canonical_team_name;
    END IF;

    SELECT team_name
    INTO legacy_team_name
    FROM teams
    WHERE team_id = 41311;

    IF legacy_team_name IS NULL THEN
        RAISE NOTICE
            'Legacy Athletics team 41311 is already absent.';
        RETURN;
    END IF;

    IF legacy_team_name IS DISTINCT FROM 'Oakland Athletics' THEN
        RAISE EXCEPTION
            'Expected team 41311 to be Oakland Athletics; found %',
            legacy_team_name;
    END IF;

    IF EXISTS (
        SELECT 1
        FROM baseball_team_sources
        WHERE team_id = 41311
    ) THEN
        RAISE EXCEPTION
            'Legacy team 41311 still has source mappings.';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM baseball_player_team_assignments
        WHERE team_id = 41311
    ) THEN
        RAISE EXCEPTION
            'Legacy team 41311 still has player assignments.';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM team_game_statistics
        WHERE team_id = 41311
    ) THEN
        RAISE EXCEPTION
            'Legacy team 41311 still has team-game statistics.';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM player_game_pitching_statistics
        WHERE team_id = 41311
    ) THEN
        RAISE EXCEPTION
            'Legacy team 41311 still has pitching statistics.';
    END IF;

    UPDATE games
    SET home_team_id = 5
    WHERE home_team_id = 41311;

    UPDATE games
    SET away_team_id = 5
    WHERE away_team_id = 41311;

    DELETE FROM teams
    WHERE team_id = 41311;
END;
$migration$;
