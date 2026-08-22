-- Migration 030
-- Create the immutable official NFL pregame quote boundary. Eligibility is
-- based on the database-recorded SportsModel observation time, strictly before
-- the current canonical NFL kickoff. Provider timestamps remain provenance.

CREATE TABLE nfl_official_pregame_evidence (
    nfl_official_pregame_evidence_id BIGSERIAL PRIMARY KEY,

    odds_market_snapshot_id BIGINT NOT NULL UNIQUE
        REFERENCES odds_market_snapshots(odds_market_snapshot_id)
        ON DELETE RESTRICT,

    odds_provider_event_observation_id BIGINT NOT NULL
        REFERENCES odds_provider_event_observations(
            odds_provider_event_observation_id
        )
        ON DELETE RESTRICT,

    nfl_odds_provider_event_mapping_id BIGINT NOT NULL
        REFERENCES nfl_odds_provider_event_mappings(
            nfl_odds_provider_event_mapping_id
        )
        ON DELETE RESTRICT,

    odds_ingestion_run_id BIGINT NOT NULL
        REFERENCES odds_ingestion_runs(odds_ingestion_run_id)
        ON DELETE RESTRICT,

    sportsbook_provider_identity_id BIGINT NOT NULL
        REFERENCES sportsbook_provider_identities(
            sportsbook_provider_identity_id
        )
        ON DELETE RESTRICT,

    sportsbook_id INTEGER NOT NULL
        REFERENCES sportsbooks(sportsbook_id)
        ON DELETE RESTRICT,

    game_id INTEGER NOT NULL
        REFERENCES nfl_games(game_id)
        ON DELETE RESTRICT,

    canonical_selection_team_id INTEGER NOT NULL
        REFERENCES nfl_team_profiles(team_id)
        ON DELETE RESTRICT,

    provider_selection_name VARCHAR(150) NOT NULL,

    market_type VARCHAR(50) NOT NULL,

    american_price INTEGER NOT NULL,

    line_value NUMERIC(10, 3),

    trusted_observed_at TIMESTAMPTZ NOT NULL,

    canonical_kickoff_at_qualification TIMESTAMPTZ NOT NULL,

    provider_commence_time TIMESTAMPTZ NOT NULL,

    bookmaker_updated_at TIMESTAMPTZ,

    market_updated_at TIMESTAMPTZ,

    qualified_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),

    CONSTRAINT chk_nfl_official_pregame_market
        CHECK (market_type = 'h2h'),

    CONSTRAINT chk_nfl_official_pregame_selection_text
        CHECK (LENGTH(BTRIM(provider_selection_name)) > 0),

    CONSTRAINT chk_nfl_official_pregame_time
        CHECK (
            trusted_observed_at
                < canonical_kickoff_at_qualification
        )
);

CREATE FUNCTION validate_nfl_official_pregame_evidence_insert()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    source_row RECORD;
    expected_selection_team_id INTEGER;
BEGIN
    SELECT
        snapshot.odds_provider_event_observation_id,
        snapshot.odds_ingestion_run_id,
        snapshot.sportsbook_provider_identity_id,
        snapshot.sportsbook_id,
        snapshot.game_id AS snapshot_game_id,
        snapshot.market_type,
        snapshot.selection_name,
        snapshot.price,
        snapshot.line_value,
        snapshot.snapshot_time,
        snapshot.source_name AS snapshot_source_name,
        snapshot.observed_at AS snapshot_observed_at,
        snapshot.bookmaker_updated_at,
        snapshot.market_updated_at,
        event.nfl_odds_provider_event_mapping_id,
        event.odds_ingestion_run_id AS event_run_id,
        event.source_name AS event_source_name,
        event.provider_sport_key AS event_sport_key,
        event.provider_commence_time,
        event.observed_at AS event_observed_at,
        run.sport AS run_sport,
        run.source_name AS run_source_name,
        run.status AS run_status,
        run.response_received_at,
        identity.sportsbook_id AS identity_sportsbook_id,
        identity.provider_name AS identity_provider_name,
        mapping.game_id AS mapped_game_id,
        mapping.provider_name AS mapping_provider_name,
        mapping.provider_sport_key AS mapping_sport_key,
        mapping.canonical_home_team_id,
        mapping.canonical_away_team_id,
        mapping.provider_home_team_name,
        mapping.provider_away_team_name,
        game.home_team_id AS current_home_team_id,
        game.away_team_id AS current_away_team_id,
        nfl.scheduled_start_time AS current_canonical_kickoff
    INTO source_row
    FROM odds_market_snapshots AS snapshot
    LEFT JOIN odds_provider_event_observations AS event
      ON event.odds_provider_event_observation_id
        = snapshot.odds_provider_event_observation_id
    LEFT JOIN odds_ingestion_runs AS run
      ON run.odds_ingestion_run_id = snapshot.odds_ingestion_run_id
    LEFT JOIN sportsbook_provider_identities AS identity
      ON identity.sportsbook_provider_identity_id
        = snapshot.sportsbook_provider_identity_id
    LEFT JOIN nfl_odds_provider_event_mappings AS mapping
      ON mapping.nfl_odds_provider_event_mapping_id
        = event.nfl_odds_provider_event_mapping_id
    LEFT JOIN games AS game
      ON game.game_id = mapping.game_id
    LEFT JOIN nfl_games AS nfl
      ON nfl.game_id = mapping.game_id
    WHERE snapshot.odds_market_snapshot_id = NEW.odds_market_snapshot_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'official NFL evidence requires an existing quote snapshot';
    END IF;

    IF source_row.odds_provider_event_observation_id IS NULL
       OR source_row.odds_ingestion_run_id IS NULL
       OR source_row.sportsbook_provider_identity_id IS NULL
       OR source_row.snapshot_observed_at IS NULL THEN
        RAISE EXCEPTION 'official NFL evidence requires complete quote provenance';
    END IF;

    IF source_row.nfl_odds_provider_event_mapping_id IS NULL
       OR source_row.mapped_game_id IS NULL THEN
        RAISE EXCEPTION 'official NFL evidence requires canonical NFL event mapping';
    END IF;

    SELECT scheduled_start_time
    INTO source_row.current_canonical_kickoff
    FROM nfl_games
    WHERE game_id = source_row.mapped_game_id
    FOR SHARE;

    IF source_row.run_sport <> 'americanfootball_nfl'
       OR source_row.event_sport_key <> 'americanfootball_nfl'
       OR source_row.mapping_sport_key <> 'americanfootball_nfl'
       OR source_row.run_source_name <> 'odds_api'
       OR source_row.event_source_name <> 'odds_api'
       OR source_row.snapshot_source_name <> 'odds_api'
       OR source_row.mapping_provider_name <> 'odds_api'
       OR source_row.identity_provider_name <> 'odds_api' THEN
        RAISE EXCEPTION 'official NFL evidence source or sport mismatch';
    END IF;

    IF source_row.run_status <> 'completed'
       OR source_row.response_received_at IS NULL THEN
        RAISE EXCEPTION 'official NFL evidence requires a completed provenance run';
    END IF;

    IF source_row.event_run_id <> source_row.odds_ingestion_run_id
       OR source_row.event_observed_at <> source_row.response_received_at
       OR source_row.snapshot_observed_at <> source_row.event_observed_at
       OR source_row.snapshot_time <> source_row.snapshot_observed_at
       OR source_row.identity_sportsbook_id <> source_row.sportsbook_id THEN
        RAISE EXCEPTION 'official NFL evidence has incompatible provenance linkage';
    END IF;

    IF source_row.snapshot_game_id <> source_row.mapped_game_id
       OR source_row.current_home_team_id
            <> source_row.canonical_home_team_id
       OR source_row.current_away_team_id
            <> source_row.canonical_away_team_id THEN
        RAISE EXCEPTION 'official NFL evidence has incompatible canonical game linkage';
    END IF;

    IF source_row.market_type <> 'h2h' THEN
        RAISE EXCEPTION 'official NFL evidence supports only h2h selections';
    END IF;

    IF source_row.selection_name = source_row.provider_home_team_name THEN
        expected_selection_team_id := source_row.canonical_home_team_id;
    ELSIF source_row.selection_name = source_row.provider_away_team_name THEN
        expected_selection_team_id := source_row.canonical_away_team_id;
    ELSE
        RAISE EXCEPTION 'provider selection does not match mapped NFL teams';
    END IF;

    IF NEW.canonical_selection_team_id <> expected_selection_team_id THEN
        RAISE EXCEPTION 'canonical selection team does not match provider selection';
    END IF;

    IF source_row.snapshot_observed_at
        >= source_row.current_canonical_kickoff THEN
        RAISE EXCEPTION
            'official NFL evidence observation must be strictly before canonical kickoff';
    END IF;

    NEW.odds_provider_event_observation_id :=
        source_row.odds_provider_event_observation_id;
    NEW.nfl_odds_provider_event_mapping_id :=
        source_row.nfl_odds_provider_event_mapping_id;
    NEW.odds_ingestion_run_id := source_row.odds_ingestion_run_id;
    NEW.sportsbook_provider_identity_id :=
        source_row.sportsbook_provider_identity_id;
    NEW.sportsbook_id := source_row.sportsbook_id;
    NEW.game_id := source_row.mapped_game_id;
    NEW.provider_selection_name := source_row.selection_name;
    NEW.market_type := source_row.market_type;
    NEW.american_price := source_row.price;
    NEW.line_value := source_row.line_value;
    NEW.trusted_observed_at := source_row.snapshot_observed_at;
    NEW.canonical_kickoff_at_qualification :=
        source_row.current_canonical_kickoff;
    NEW.provider_commence_time := source_row.provider_commence_time;
    NEW.bookmaker_updated_at := source_row.bookmaker_updated_at;
    NEW.market_updated_at := source_row.market_updated_at;
    NEW.qualified_at := clock_timestamp();

    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_validate_nfl_official_pregame_evidence
BEFORE INSERT ON nfl_official_pregame_evidence
FOR EACH ROW
EXECUTE FUNCTION validate_nfl_official_pregame_evidence_insert();

CREATE FUNCTION reject_nfl_official_pregame_evidence_mutation()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'official NFL pregame evidence is immutable';
END;
$$;

CREATE TRIGGER trg_nfl_official_pregame_evidence_immutable
BEFORE UPDATE OR DELETE ON nfl_official_pregame_evidence
FOR EACH ROW
EXECUTE FUNCTION reject_nfl_official_pregame_evidence_mutation();

COMMENT ON TABLE nfl_official_pregame_evidence IS
    'Explicit immutable qualification of one provenance-bearing NFL H2H quote. '
    'The database-recorded observation time must be strictly before the current '
    'canonical kickoff when this row is created.';

COMMENT ON COLUMN nfl_official_pregame_evidence.trusted_observed_at IS
    'SportsModel database response/observation time; authoritative for pregame '
    'eligibility. Provider timestamps cannot relax this boundary.';

COMMENT ON COLUMN
    nfl_official_pregame_evidence.canonical_kickoff_at_qualification IS
    'Current nfl_games kickoff copied immutably when eligibility is decided. '
    'Later canonical schedule changes do not rewrite this evidence.';
