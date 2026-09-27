-- Migration 033
-- Preserve immutable odds acquisition rows while allowing one audited,
-- observation-level correction to their effective canonical MLB identity.

CREATE TABLE odds_provider_event_canonical_corrections (
    odds_provider_event_canonical_correction_id BIGSERIAL PRIMARY KEY,

    odds_provider_event_observation_id BIGINT NOT NULL
        REFERENCES odds_provider_event_observations(
            odds_provider_event_observation_id
        )
        ON DELETE RESTRICT,

    original_game_id INTEGER NOT NULL
        REFERENCES games(game_id)
        ON DELETE RESTRICT,

    corrected_game_id INTEGER NOT NULL
        REFERENCES games(game_id)
        ON DELETE RESTRICT,

    correction_reason TEXT NOT NULL,

    evidence_reference TEXT NOT NULL,

    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT uq_odds_event_canonical_correction_observation
        UNIQUE (odds_provider_event_observation_id),

    CONSTRAINT chk_odds_event_canonical_correction_distinct_games
        CHECK (original_game_id <> corrected_game_id),

    CONSTRAINT chk_odds_event_canonical_correction_audit_text
        CHECK (
            LENGTH(BTRIM(correction_reason)) > 0
            AND LENGTH(BTRIM(evidence_reference)) > 0
        )
);

CREATE FUNCTION validate_odds_event_canonical_correction()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    observation_source_name TEXT;
    observation_sport_key TEXT;
    observation_external_event_id TEXT;
    observation_commence_time TIMESTAMPTZ;
    observation_home_team_name TEXT;
    observation_away_team_name TEXT;
    snapshot_count BIGINT;
    snapshot_game_count BIGINT;
    snapshot_game_id INTEGER;
    original_home_team_name TEXT;
    original_away_team_name TEXT;
    corrected_home_team_name TEXT;
    corrected_away_team_name TEXT;
    event_mapping_count BIGINT;
    event_mapping_game_id INTEGER;
    authoritative_candidate_count BIGINT;
    authoritative_candidate_game_id INTEGER;
BEGIN
    SELECT
        observation.source_name,
        observation.provider_sport_key,
        observation.external_event_id,
        observation.provider_commence_time,
        observation.provider_home_team_name,
        observation.provider_away_team_name
    INTO
        observation_source_name,
        observation_sport_key,
        observation_external_event_id,
        observation_commence_time,
        observation_home_team_name,
        observation_away_team_name
    FROM odds_provider_event_observations AS observation
    WHERE observation.odds_provider_event_observation_id =
        NEW.odds_provider_event_observation_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION
            'odds provider event observation % does not exist',
            NEW.odds_provider_event_observation_id;
    END IF;

    IF observation_source_name IS DISTINCT FROM 'odds_api'
       OR observation_sport_key IS DISTINCT FROM 'baseball_mlb' THEN
        RAISE EXCEPTION
            'canonical odds corrections require an Odds API MLB observation';
    END IF;

    SELECT
        COUNT(*),
        COUNT(DISTINCT snapshot.game_id),
        MIN(snapshot.game_id)
    INTO
        snapshot_count,
        snapshot_game_count,
        snapshot_game_id
    FROM odds_market_snapshots AS snapshot
    WHERE snapshot.odds_provider_event_observation_id =
        NEW.odds_provider_event_observation_id;

    IF snapshot_count = 0 THEN
        RAISE EXCEPTION
            'observation % has no covered odds snapshots',
            NEW.odds_provider_event_observation_id;
    END IF;

    IF snapshot_game_count <> 1
       OR snapshot_game_id IS DISTINCT FROM NEW.original_game_id THEN
        RAISE EXCEPTION
            'original game % does not match the covered raw snapshots',
            NEW.original_game_id;
    END IF;

    SELECT home.team_name, away.team_name
    INTO original_home_team_name, original_away_team_name
    FROM games AS game
    JOIN teams AS home ON home.team_id = game.home_team_id
    JOIN teams AS away ON away.team_id = game.away_team_id
    WHERE game.game_id = NEW.original_game_id;

    IF original_home_team_name IS DISTINCT FROM observation_home_team_name
       OR original_away_team_name IS DISTINCT FROM observation_away_team_name THEN
        RAISE EXCEPTION
            'provider team orientation does not match original game %',
            NEW.original_game_id;
    END IF;

    SELECT home.team_name, away.team_name
    INTO corrected_home_team_name, corrected_away_team_name
    FROM games AS game
    JOIN teams AS home ON home.team_id = game.home_team_id
    JOIN teams AS away ON away.team_id = game.away_team_id
    WHERE game.game_id = NEW.corrected_game_id;

    IF corrected_home_team_name IS DISTINCT FROM observation_home_team_name
       OR corrected_away_team_name IS DISTINCT FROM observation_away_team_name THEN
        RAISE EXCEPTION
            'provider team orientation does not match corrected game %',
            NEW.corrected_game_id;
    END IF;

    SELECT COUNT(*), MIN(source.game_id)
    INTO event_mapping_count, event_mapping_game_id
    FROM game_sources AS source
    WHERE source.source_name = observation_source_name
      AND source.external_game_id = observation_external_event_id;

    IF event_mapping_count <> 1
       OR event_mapping_game_id IS DISTINCT FROM NEW.corrected_game_id THEN
        RAISE EXCEPTION
            'provider event % is not uniquely mapped to corrected game %',
            observation_external_event_id,
            NEW.corrected_game_id;
    END IF;

    SELECT COUNT(*), MIN(candidate.game_id)
    INTO
        authoritative_candidate_count,
        authoritative_candidate_game_id
    FROM games AS candidate
    WHERE candidate.home_team_id = (
            SELECT game.home_team_id
            FROM games AS game
            WHERE game.game_id = NEW.corrected_game_id
        )
      AND candidate.away_team_id = (
            SELECT game.away_team_id
            FROM games AS game
            WHERE game.game_id = NEW.corrected_game_id
        )
      AND candidate.game_date BETWEEN
            observation_commence_time - INTERVAL '15 minutes'
            AND observation_commence_time + INTERVAL '15 minutes'
      AND EXISTS (
            SELECT 1
            FROM game_sources AS authoritative_source
            WHERE authoritative_source.game_id = candidate.game_id
              AND authoritative_source.source_name = 'mlb_stats'
        );

    IF authoritative_candidate_count <> 1
       OR authoritative_candidate_game_id IS DISTINCT FROM
            NEW.corrected_game_id THEN
        RAISE EXCEPTION
            'corrected identity is not the unique nearby MLB-authoritative game';
    END IF;

    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_validate_odds_event_canonical_correction
BEFORE INSERT ON odds_provider_event_canonical_corrections
FOR EACH ROW
EXECUTE FUNCTION validate_odds_event_canonical_correction();

CREATE TRIGGER trg_odds_event_canonical_correction_immutable
BEFORE UPDATE OR DELETE ON odds_provider_event_canonical_corrections
FOR EACH ROW
EXECUTE FUNCTION reject_odds_source_identity_mutation();

CREATE VIEW odds_market_snapshots_effective AS
SELECT
    snapshot.*,
    snapshot.game_id AS raw_acquisition_game_id,
    COALESCE(
        correction.corrected_game_id,
        snapshot.game_id
    ) AS effective_game_id
FROM odds_market_snapshots AS snapshot
LEFT JOIN odds_provider_event_canonical_corrections AS correction
  ON correction.odds_provider_event_observation_id =
     snapshot.odds_provider_event_observation_id;

COMMENT ON TABLE odds_provider_event_canonical_corrections IS
    'Immutable, append-only corrections to the effective canonical identity '
    'of every provenance-bearing odds snapshot in one provider observation.';

COMMENT ON VIEW odds_market_snapshots_effective IS
    'Central read contract exposing immutable raw_acquisition_game_id and '
    'separate effective_game_id for odds snapshot consumers.';
