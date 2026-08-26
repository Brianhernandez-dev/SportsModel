-- Migration 031
-- Immutable official NFL Moneyline entry-market evaluation evidence.
-- This migration creates schema only and performs no production data rewrite.

CREATE TABLE nfl_moneyline_market_evaluation_runs (
    nfl_moneyline_market_evaluation_run_id BIGSERIAL PRIMARY KEY,
    run_key UUID NOT NULL UNIQUE,
    request_sha256 CHAR(64) NOT NULL,
    nfl_moneyline_game_prediction_id BIGINT NOT NULL
        REFERENCES nfl_moneyline_game_predictions(
            nfl_moneyline_game_prediction_id
        ) ON DELETE RESTRICT,
    nfl_moneyline_prediction_run_id BIGINT NOT NULL
        REFERENCES nfl_moneyline_prediction_runs(
            nfl_moneyline_prediction_run_id
        ) ON DELETE RESTRICT,
    odds_ingestion_run_id BIGINT NOT NULL
        REFERENCES odds_ingestion_runs(odds_ingestion_run_id)
        ON DELETE RESTRICT,
    market_evaluation_protocol_version VARCHAR(100) NOT NULL,
    market_evaluation_protocol_fingerprint CHAR(64) NOT NULL,
    evaluation_kind VARCHAR(32) NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'running',
    source_graph_fingerprint CHAR(64),
    evaluation_count INTEGER NOT NULL DEFAULT 0,
    failure_code VARCHAR(64),
    failure_message TEXT,
    started_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    completed_at TIMESTAMPTZ,
    failed_at TIMESTAMPTZ,
    CONSTRAINT chk_nfl_market_evaluation_run_protocol CHECK (
        market_evaluation_protocol_version
            = 'nfl_moneyline_market_evaluation_0.1.0'
        AND market_evaluation_protocol_fingerprint
            = '383592d724a83c991877dc940dc0f5f386b2f522725def58fef06f1035fbca0e'
        AND evaluation_kind = 'official_entry'
    ),
    CONSTRAINT chk_nfl_market_evaluation_run_status CHECK (
        status IN ('running', 'completed', 'failed')
    ),
    CONSTRAINT chk_nfl_market_evaluation_run_sha256 CHECK (
        request_sha256 ~ '^[0-9a-f]{64}$'
        AND (
            source_graph_fingerprint IS NULL
            OR source_graph_fingerprint ~ '^[0-9a-f]{64}$'
        )
    ),
    CONSTRAINT chk_nfl_market_evaluation_run_terminal CHECK (
        (
            status = 'running'
            AND source_graph_fingerprint IS NULL
            AND evaluation_count = 0
            AND failure_code IS NULL
            AND failure_message IS NULL
            AND completed_at IS NULL
            AND failed_at IS NULL
        )
        OR (
            status = 'completed'
            AND source_graph_fingerprint IS NOT NULL
            AND evaluation_count = 1
            AND failure_code IS NULL
            AND failure_message IS NULL
            AND completed_at IS NOT NULL
            AND failed_at IS NULL
        )
        OR (
            status = 'failed'
            AND evaluation_count = 0
            AND failure_code IS NOT NULL
            AND LENGTH(BTRIM(failure_code)) > 0
            AND failure_message IS NOT NULL
            AND LENGTH(BTRIM(failure_message)) > 0
            AND completed_at IS NULL
            AND failed_at IS NOT NULL
        )
    )
);

CREATE TABLE nfl_moneyline_market_evaluations (
    nfl_moneyline_market_evaluation_id BIGSERIAL PRIMARY KEY,
    creation_evaluation_run_id BIGINT NOT NULL UNIQUE
        REFERENCES nfl_moneyline_market_evaluation_runs(
            nfl_moneyline_market_evaluation_run_id
        ) ON DELETE RESTRICT,
    nfl_moneyline_game_prediction_id BIGINT NOT NULL
        REFERENCES nfl_moneyline_game_predictions(
            nfl_moneyline_game_prediction_id
        ) ON DELETE RESTRICT,
    nfl_moneyline_prediction_run_id BIGINT NOT NULL
        REFERENCES nfl_moneyline_prediction_runs(
            nfl_moneyline_prediction_run_id
        ) ON DELETE RESTRICT,
    game_id INTEGER NOT NULL
        REFERENCES nfl_games(game_id) ON DELETE RESTRICT,
    home_team_id INTEGER NOT NULL
        REFERENCES nfl_team_profiles(team_id) ON DELETE RESTRICT,
    away_team_id INTEGER NOT NULL
        REFERENCES nfl_team_profiles(team_id) ON DELETE RESTRICT,
    selected_team_id INTEGER NOT NULL
        REFERENCES nfl_team_profiles(team_id) ON DELETE RESTRICT,
    selected_side VARCHAR(8) NOT NULL,
    selected_route VARCHAR(16) NOT NULL,
    prediction_run_type VARCHAR(16) NOT NULL,
    prediction_protocol_version VARCHAR(100) NOT NULL,
    prediction_protocol_fingerprint CHAR(64) NOT NULL,
    routing_contract_version VARCHAR(100) NOT NULL,
    selected_model_specification_version VARCHAR(100) NOT NULL,
    feature_schema_version VARCHAR(100) NOT NULL,
    specification_fingerprint CHAR(64) NOT NULL,
    model_fingerprint CHAR(64) NOT NULL,
    selected_model_probability NUMERIC(18, 16) NOT NULL,
    prediction_created_at TIMESTAMPTZ NOT NULL,
    odds_ingestion_run_id BIGINT NOT NULL
        REFERENCES odds_ingestion_runs(odds_ingestion_run_id)
        ON DELETE RESTRICT,
    trusted_observed_at TIMESTAMPTZ NOT NULL,
    canonical_kickoff_at_evaluation TIMESTAMPTZ NOT NULL,
    evaluation_created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    market_evaluation_protocol_version VARCHAR(100) NOT NULL,
    market_evaluation_protocol_fingerprint CHAR(64) NOT NULL,
    evaluation_kind VARCHAR(32) NOT NULL,
    contributor_count INTEGER NOT NULL,
    consensus_no_vig_selected_probability NUMERIC(18, 16) NOT NULL,
    best_price_sportsbook_provider_identity_id BIGINT NOT NULL
        REFERENCES sportsbook_provider_identities(
            sportsbook_provider_identity_id
        ) ON DELETE RESTRICT,
    best_price_nfl_official_pregame_evidence_id BIGINT NOT NULL
        REFERENCES nfl_official_pregame_evidence(
            nfl_official_pregame_evidence_id
        ) ON DELETE RESTRICT,
    best_american_price INTEGER NOT NULL,
    best_decimal_odds NUMERIC(24, 16) NOT NULL,
    market_edge NUMERIC(18, 16) NOT NULL,
    model_expected_value NUMERIC(24, 16) NOT NULL,
    source_graph_fingerprint CHAR(64) NOT NULL,
    CONSTRAINT uq_nfl_market_evaluation_identity UNIQUE (
        nfl_moneyline_game_prediction_id,
        market_evaluation_protocol_version,
        evaluation_kind
    ),
    CONSTRAINT uq_nfl_market_evaluation_context UNIQUE (
        nfl_moneyline_market_evaluation_id,
        odds_ingestion_run_id,
        game_id,
        trusted_observed_at
    ),
    CONSTRAINT chk_nfl_market_evaluation_protocol CHECK (
        market_evaluation_protocol_version
            = 'nfl_moneyline_market_evaluation_0.1.0'
        AND market_evaluation_protocol_fingerprint
            = '383592d724a83c991877dc940dc0f5f386b2f522725def58fef06f1035fbca0e'
        AND evaluation_kind = 'official_entry'
    ),
    CONSTRAINT chk_nfl_market_evaluation_prediction_protocol CHECK (
        prediction_run_type = 'official'
        AND prediction_protocol_version = 'nfl_moneyline_forward_0.1.0'
        AND prediction_protocol_fingerprint
            = '7e211679904df35db95d2da7e559c5b1cc0650f2e2849048fae8247dba3c1aa7'
        AND routing_contract_version = 'nfl_moneyline_routing_0.1.0'
        AND selected_route IN ('early', 'mature')
    ),
    CONSTRAINT chk_nfl_market_evaluation_identity_values CHECK (
        home_team_id <> away_team_id
        AND (
            (selected_side = 'home' AND selected_team_id = home_team_id)
            OR
            (selected_side = 'away' AND selected_team_id = away_team_id)
        )
    ),
    CONSTRAINT chk_nfl_market_evaluation_numbers CHECK (
        contributor_count >= 5
        AND selected_model_probability BETWEEN 0 AND 1
        AND consensus_no_vig_selected_probability BETWEEN 0 AND 1
        AND best_american_price <> 0
        AND best_decimal_odds > 1
    ),
    CONSTRAINT chk_nfl_market_evaluation_time CHECK (
        prediction_created_at < trusted_observed_at
        AND trusted_observed_at <= evaluation_created_at
        AND evaluation_created_at < canonical_kickoff_at_evaluation
        AND trusted_observed_at - prediction_created_at
            <= INTERVAL '900 seconds'
        AND evaluation_created_at - trusted_observed_at
            <= INTERVAL '300 seconds'
    ),
    CONSTRAINT chk_nfl_market_evaluation_sha256 CHECK (
        prediction_protocol_fingerprint ~ '^[0-9a-f]{64}$'
        AND specification_fingerprint ~ '^[0-9a-f]{64}$'
        AND model_fingerprint ~ '^[0-9a-f]{64}$'
        AND market_evaluation_protocol_fingerprint ~ '^[0-9a-f]{64}$'
        AND source_graph_fingerprint ~ '^[0-9a-f]{64}$'
    )
);

ALTER TABLE nfl_moneyline_market_evaluation_runs
ADD COLUMN nfl_moneyline_market_evaluation_id BIGINT
    REFERENCES nfl_moneyline_market_evaluations(
        nfl_moneyline_market_evaluation_id
    ) ON DELETE RESTRICT;

ALTER TABLE nfl_moneyline_market_evaluation_runs
ADD CONSTRAINT chk_nfl_market_evaluation_run_result CHECK (
    (
        status = 'completed'
        AND nfl_moneyline_market_evaluation_id IS NOT NULL
    )
    OR (
        status <> 'completed'
        AND nfl_moneyline_market_evaluation_id IS NULL
    )
);

CREATE TABLE nfl_moneyline_market_evaluation_contributors (
    nfl_moneyline_market_evaluation_contributor_id BIGSERIAL PRIMARY KEY,
    nfl_moneyline_market_evaluation_id BIGINT NOT NULL,
    odds_ingestion_run_id BIGINT NOT NULL,
    game_id INTEGER NOT NULL,
    trusted_observed_at TIMESTAMPTZ NOT NULL,
    contributor_ordinal INTEGER NOT NULL,
    sportsbook_provider_identity_id BIGINT NOT NULL
        REFERENCES sportsbook_provider_identities(
            sportsbook_provider_identity_id
        ) ON DELETE RESTRICT,
    home_nfl_official_pregame_evidence_id BIGINT NOT NULL
        REFERENCES nfl_official_pregame_evidence(
            nfl_official_pregame_evidence_id
        ) ON DELETE RESTRICT,
    away_nfl_official_pregame_evidence_id BIGINT NOT NULL
        REFERENCES nfl_official_pregame_evidence(
            nfl_official_pregame_evidence_id
        ) ON DELETE RESTRICT,
    home_american_price INTEGER NOT NULL,
    away_american_price INTEGER NOT NULL,
    home_raw_implied_probability NUMERIC(18, 16) NOT NULL,
    away_raw_implied_probability NUMERIC(18, 16) NOT NULL,
    home_no_vig_probability NUMERIC(18, 16) NOT NULL,
    away_no_vig_probability NUMERIC(18, 16) NOT NULL,
    market_updated_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT fk_nfl_market_contributor_parent_context
        FOREIGN KEY (
            nfl_moneyline_market_evaluation_id,
            odds_ingestion_run_id,
            game_id,
            trusted_observed_at
        ) REFERENCES nfl_moneyline_market_evaluations (
            nfl_moneyline_market_evaluation_id,
            odds_ingestion_run_id,
            game_id,
            trusted_observed_at
        ) ON DELETE RESTRICT,
    CONSTRAINT uq_nfl_market_contributor_provider UNIQUE (
        nfl_moneyline_market_evaluation_id,
        sportsbook_provider_identity_id
    ),
    CONSTRAINT uq_nfl_market_contributor_ordinal UNIQUE (
        nfl_moneyline_market_evaluation_id,
        contributor_ordinal
    ),
    CONSTRAINT uq_nfl_market_contributor_home_evidence UNIQUE (
        nfl_moneyline_market_evaluation_id,
        home_nfl_official_pregame_evidence_id
    ),
    CONSTRAINT uq_nfl_market_contributor_away_evidence UNIQUE (
        nfl_moneyline_market_evaluation_id,
        away_nfl_official_pregame_evidence_id
    ),
    CONSTRAINT chk_nfl_market_contributor_identity CHECK (
        contributor_ordinal >= 1
        AND home_nfl_official_pregame_evidence_id
            <> away_nfl_official_pregame_evidence_id
    ),
    CONSTRAINT chk_nfl_market_contributor_prices CHECK (
        home_american_price <> 0
        AND away_american_price <> 0
    ),
    CONSTRAINT chk_nfl_market_contributor_probabilities CHECK (
        home_raw_implied_probability BETWEEN 0 AND 1
        AND away_raw_implied_probability BETWEEN 0 AND 1
        AND home_no_vig_probability BETWEEN 0 AND 1
        AND away_no_vig_probability BETWEEN 0 AND 1
        AND home_no_vig_probability + away_no_vig_probability = 1
    )
);

CREATE TABLE nfl_moneyline_market_evaluation_exclusions (
    nfl_moneyline_market_evaluation_exclusion_id BIGSERIAL PRIMARY KEY,
    nfl_moneyline_market_evaluation_id BIGINT NOT NULL
        REFERENCES nfl_moneyline_market_evaluations(
            nfl_moneyline_market_evaluation_id
        ) ON DELETE RESTRICT,
    sportsbook_provider_identity_id BIGINT NOT NULL
        REFERENCES sportsbook_provider_identities(
            sportsbook_provider_identity_id
        ) ON DELETE RESTRICT,
    reason_code VARCHAR(32) NOT NULL,
    CONSTRAINT uq_nfl_market_exclusion_provider UNIQUE (
        nfl_moneyline_market_evaluation_id,
        sportsbook_provider_identity_id
    ),
    CONSTRAINT chk_nfl_market_exclusion_reason CHECK (
        reason_code IN ('incomplete_market', 'stale_market')
    )
);

CREATE FUNCTION validate_nfl_market_evaluation_parent_insert()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    source RECORD;
    expected_selected_team_id INTEGER;
    expected_selected_probability NUMERIC(18, 16);
BEGIN
    NEW.evaluation_created_at := clock_timestamp();

    SELECT
        prediction.nfl_moneyline_prediction_run_id,
        prediction.run_type,
        prediction.evaluation_protocol_version,
        prediction.game_id,
        prediction.target_kickoff,
        prediction.prediction_created_at,
        prediction.home_team_id,
        prediction.away_team_id,
        prediction.selected_route,
        prediction.routing_contract_version,
        prediction.selected_model_specification_version,
        prediction.feature_schema_version,
        prediction.specification_fingerprint,
        prediction.model_fingerprint,
        prediction.model_home_win_probability,
        prediction.predicted_side,
        prediction_run.status AS prediction_run_status,
        prediction_run.completed_at AS prediction_run_completed_at,
        nfl.scheduled_start_time AS current_kickoff,
        nfl.status AS game_status,
        game.home_team_id AS current_home_team_id,
        game.away_team_id AS current_away_team_id,
        odds_run.sport AS odds_sport,
        odds_run.source_name AS odds_source,
        odds_run.snapshot_role,
        odds_run.status AS odds_status,
        odds_run.request_started_at,
        odds_run.response_received_at,
        evaluation_run.nfl_moneyline_game_prediction_id
            AS requested_prediction_id,
        evaluation_run.nfl_moneyline_prediction_run_id
            AS requested_prediction_run_id,
        evaluation_run.odds_ingestion_run_id AS requested_odds_run_id,
        evaluation_run.status AS evaluation_run_status,
        evaluation_run.market_evaluation_protocol_version
            AS requested_protocol_version,
        evaluation_run.market_evaluation_protocol_fingerprint
            AS requested_protocol_fingerprint,
        evaluation_run.evaluation_kind AS requested_evaluation_kind
    INTO source
    FROM nfl_moneyline_game_predictions AS prediction
    JOIN nfl_moneyline_prediction_runs AS prediction_run
      ON prediction_run.nfl_moneyline_prediction_run_id
        = prediction.nfl_moneyline_prediction_run_id
    JOIN nfl_games AS nfl ON nfl.game_id = prediction.game_id
    JOIN games AS game ON game.game_id = prediction.game_id
    JOIN odds_ingestion_runs AS odds_run
      ON odds_run.odds_ingestion_run_id = NEW.odds_ingestion_run_id
    JOIN nfl_moneyline_market_evaluation_runs AS evaluation_run
      ON evaluation_run.nfl_moneyline_market_evaluation_run_id
        = NEW.creation_evaluation_run_id
    WHERE prediction.nfl_moneyline_game_prediction_id
        = NEW.nfl_moneyline_game_prediction_id
    FOR SHARE OF prediction, prediction_run, nfl, game, odds_run,
        evaluation_run;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'official NFL market evaluation source graph is incomplete';
    END IF;

    IF source.evaluation_run_status <> 'running'
       OR source.requested_prediction_id
            <> NEW.nfl_moneyline_game_prediction_id
       OR source.requested_prediction_run_id
            <> NEW.nfl_moneyline_prediction_run_id
       OR source.requested_odds_run_id <> NEW.odds_ingestion_run_id
       OR source.requested_protocol_version
            <> NEW.market_evaluation_protocol_version
       OR source.requested_protocol_fingerprint
            <> NEW.market_evaluation_protocol_fingerprint
       OR source.requested_evaluation_kind <> NEW.evaluation_kind THEN
        RAISE EXCEPTION 'official NFL evaluation run identity mismatch';
    END IF;

    IF source.prediction_run_status <> 'completed'
       OR source.run_type <> 'official'
       OR source.evaluation_protocol_version
            <> 'nfl_moneyline_forward_0.1.0'
       OR source.selected_route NOT IN ('early', 'mature') THEN
        RAISE EXCEPTION 'official NFL market evaluation requires a recognized completed official prediction';
    END IF;

    IF source.predicted_side = 'home' THEN
        expected_selected_team_id := source.home_team_id;
        expected_selected_probability := source.model_home_win_probability;
    ELSIF source.predicted_side = 'away' THEN
        expected_selected_team_id := source.away_team_id;
        expected_selected_probability :=
            1.0000000000000000 - source.model_home_win_probability;
    ELSE
        RAISE EXCEPTION 'official NFL prediction selected side is unknown';
    END IF;

    IF ROW(
        NEW.nfl_moneyline_prediction_run_id,
        NEW.game_id,
        NEW.home_team_id,
        NEW.away_team_id,
        NEW.selected_team_id,
        NEW.selected_side,
        NEW.selected_route,
        NEW.prediction_run_type,
        NEW.prediction_protocol_version,
        NEW.routing_contract_version,
        NEW.selected_model_specification_version,
        NEW.feature_schema_version,
        NEW.specification_fingerprint,
        NEW.model_fingerprint,
        NEW.selected_model_probability,
        NEW.prediction_created_at,
        NEW.canonical_kickoff_at_evaluation,
        NEW.trusted_observed_at
    ) IS DISTINCT FROM ROW(
        source.nfl_moneyline_prediction_run_id,
        source.game_id,
        source.home_team_id,
        source.away_team_id,
        expected_selected_team_id,
        source.predicted_side,
        source.selected_route,
        source.run_type,
        source.evaluation_protocol_version,
        source.routing_contract_version,
        source.selected_model_specification_version,
        source.feature_schema_version,
        source.specification_fingerprint,
        source.model_fingerprint,
        expected_selected_probability,
        source.prediction_created_at,
        source.current_kickoff,
        source.response_received_at
    ) THEN
        RAISE EXCEPTION 'official NFL market evaluation copied source identity mismatch';
    END IF;

    IF source.current_home_team_id <> source.home_team_id
       OR source.current_away_team_id <> source.away_team_id
       OR source.current_kickoff <> source.target_kickoff
       OR source.game_status <> 'unplayed' THEN
        RAISE EXCEPTION 'official NFL market evaluation canonical game identity is no longer eligible';
    END IF;

    IF source.odds_sport <> 'americanfootball_nfl'
       OR source.odds_source <> 'odds_api'
       OR source.snapshot_role <> 'entry'
       OR source.odds_status <> 'completed'
       OR source.request_started_at IS NULL
       OR source.response_received_at IS NULL THEN
        RAISE EXCEPTION 'official NFL market evaluation requires a completed NFL Odds API entry run';
    END IF;

    IF source.prediction_run_completed_at > source.request_started_at
       OR source.prediction_created_at >= source.response_received_at
       OR source.response_received_at - source.prediction_created_at
            > INTERVAL '900 seconds'
       OR source.response_received_at > NEW.evaluation_created_at
       OR NEW.evaluation_created_at - source.response_received_at
            > INTERVAL '300 seconds'
       OR source.response_received_at >= source.current_kickoff
       OR NEW.evaluation_created_at >= source.current_kickoff THEN
        RAISE EXCEPTION 'official NFL market evaluation timing is ineligible';
    END IF;

    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_validate_nfl_market_evaluation_parent
BEFORE INSERT ON nfl_moneyline_market_evaluations
FOR EACH ROW
EXECUTE FUNCTION validate_nfl_market_evaluation_parent_insert();

CREATE FUNCTION validate_nfl_market_evaluation_contributor_insert()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    parent RECORD;
    home_source RECORD;
    away_source RECORD;
BEGIN
    SELECT home_team_id, away_team_id, canonical_kickoff_at_evaluation
    INTO parent
    FROM nfl_moneyline_market_evaluations
    WHERE nfl_moneyline_market_evaluation_id
        = NEW.nfl_moneyline_market_evaluation_id;

    SELECT * INTO home_source
    FROM nfl_official_pregame_evidence
    WHERE nfl_official_pregame_evidence_id
        = NEW.home_nfl_official_pregame_evidence_id;

    SELECT * INTO away_source
    FROM nfl_official_pregame_evidence
    WHERE nfl_official_pregame_evidence_id
        = NEW.away_nfl_official_pregame_evidence_id;

    IF parent IS NULL OR home_source IS NULL OR away_source IS NULL THEN
        RAISE EXCEPTION 'official NFL contributor source graph is incomplete';
    END IF;

    IF ROW(
        home_source.odds_ingestion_run_id,
        home_source.game_id,
        home_source.trusted_observed_at,
        home_source.sportsbook_provider_identity_id,
        home_source.canonical_selection_team_id,
        home_source.american_price,
        home_source.market_updated_at
    ) IS DISTINCT FROM ROW(
        NEW.odds_ingestion_run_id,
        NEW.game_id,
        NEW.trusted_observed_at,
        NEW.sportsbook_provider_identity_id,
        parent.home_team_id,
        NEW.home_american_price,
        NEW.market_updated_at
    ) OR ROW(
        away_source.odds_ingestion_run_id,
        away_source.game_id,
        away_source.trusted_observed_at,
        away_source.sportsbook_provider_identity_id,
        away_source.canonical_selection_team_id,
        away_source.american_price,
        away_source.market_updated_at
    ) IS DISTINCT FROM ROW(
        NEW.odds_ingestion_run_id,
        NEW.game_id,
        NEW.trusted_observed_at,
        NEW.sportsbook_provider_identity_id,
        parent.away_team_id,
        NEW.away_american_price,
        NEW.market_updated_at
    ) THEN
        RAISE EXCEPTION 'official NFL contributor copied source identity mismatch';
    END IF;

    IF home_source.canonical_kickoff_at_qualification
            <> parent.canonical_kickoff_at_evaluation
       OR away_source.canonical_kickoff_at_qualification
            <> parent.canonical_kickoff_at_evaluation
       OR home_source.bookmaker_updated_at > NEW.trusted_observed_at
       OR away_source.bookmaker_updated_at > NEW.trusted_observed_at
       OR NEW.market_updated_at > NEW.trusted_observed_at
       OR NEW.trusted_observed_at - NEW.market_updated_at
            > INTERVAL '300 seconds' THEN
        RAISE EXCEPTION 'official NFL contributor timing is ineligible';
    END IF;

    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_validate_nfl_market_evaluation_contributor
BEFORE INSERT ON nfl_moneyline_market_evaluation_contributors
FOR EACH ROW
EXECUTE FUNCTION validate_nfl_market_evaluation_contributor_insert();

CREATE FUNCTION validate_nfl_market_evaluation_exclusion_insert()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    parent RECORD;
    source_count BIGINT;
    distinct_selection_count BIGINT;
    home_count BIGINT;
    away_count BIGINT;
    missing_or_stale_count BIGINT;
    conflicting_pair_count BIGINT;
BEGIN
    SELECT game_id, odds_ingestion_run_id, home_team_id, away_team_id,
           trusted_observed_at
    INTO parent
    FROM nfl_moneyline_market_evaluations
    WHERE nfl_moneyline_market_evaluation_id
        = NEW.nfl_moneyline_market_evaluation_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'official NFL exclusion parent does not exist';
    END IF;

    SELECT
        COUNT(*),
        COUNT(DISTINCT canonical_selection_team_id),
        COUNT(*) FILTER (
            WHERE canonical_selection_team_id = parent.home_team_id
        ),
        COUNT(*) FILTER (
            WHERE canonical_selection_team_id = parent.away_team_id
        ),
        COUNT(*) FILTER (
            WHERE market_updated_at IS NULL
               OR market_updated_at > parent.trusted_observed_at
               OR parent.trusted_observed_at - market_updated_at
                    > INTERVAL '300 seconds'
        ),
        COUNT(DISTINCT market_updated_at)
    INTO source_count, distinct_selection_count, home_count, away_count,
         missing_or_stale_count, conflicting_pair_count
    FROM nfl_official_pregame_evidence
    WHERE game_id = parent.game_id
      AND odds_ingestion_run_id = parent.odds_ingestion_run_id
      AND sportsbook_provider_identity_id
            = NEW.sportsbook_provider_identity_id;

    IF NEW.reason_code = 'incomplete_market' AND NOT (
        source_count = 1
        AND distinct_selection_count = 1
        AND home_count + away_count = 1
    ) THEN
        RAISE EXCEPTION 'official NFL incomplete-market exclusion does not match source evidence';
    END IF;

    IF NEW.reason_code = 'stale_market' AND NOT (
        source_count = 2
        AND distinct_selection_count = 2
        AND home_count = 1
        AND away_count = 1
        AND conflicting_pair_count <= 1
        AND missing_or_stale_count >= 1
    ) THEN
        RAISE EXCEPTION 'official NFL stale-market exclusion does not match source evidence';
    END IF;

    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_validate_nfl_market_evaluation_exclusion
BEFORE INSERT ON nfl_moneyline_market_evaluation_exclusions
FOR EACH ROW
EXECUTE FUNCTION validate_nfl_market_evaluation_exclusion_insert();

CREATE FUNCTION validate_nfl_market_evaluation_graph()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    evaluation_id BIGINT;
    parent RECORD;
    actual_contributor_count BIGINT;
    best_match_count BIGINT;
    overlap_count BIGINT;
    ordinal_mismatch_count BIGINT;
    expected_best RECORD;
BEGIN
    evaluation_id := CASE
        WHEN TG_TABLE_NAME = 'nfl_moneyline_market_evaluations'
            THEN NEW.nfl_moneyline_market_evaluation_id
        ELSE NEW.nfl_moneyline_market_evaluation_id
    END;

    SELECT * INTO parent
    FROM nfl_moneyline_market_evaluations
    WHERE nfl_moneyline_market_evaluation_id = evaluation_id;

    IF NOT FOUND THEN
        RETURN NULL;
    END IF;

    SELECT COUNT(*) INTO actual_contributor_count
    FROM nfl_moneyline_market_evaluation_contributors
    WHERE nfl_moneyline_market_evaluation_id = evaluation_id;

    IF actual_contributor_count <> parent.contributor_count
       OR actual_contributor_count < 5 THEN
        RAISE EXCEPTION 'official NFL evaluation contributor count mismatch';
    END IF;

    SELECT COUNT(*) INTO ordinal_mismatch_count
    FROM (
        SELECT contributor_ordinal,
               ROW_NUMBER() OVER (
                   ORDER BY sportsbook_provider_identity_id,
                            home_nfl_official_pregame_evidence_id,
                            away_nfl_official_pregame_evidence_id
               ) AS expected_ordinal
        FROM nfl_moneyline_market_evaluation_contributors
        WHERE nfl_moneyline_market_evaluation_id = evaluation_id
    ) AS ordered
    WHERE contributor_ordinal <> expected_ordinal;

    IF ordinal_mismatch_count <> 0 THEN
        RAISE EXCEPTION 'official NFL evaluation contributor ordering mismatch';
    END IF;

    SELECT COUNT(*) INTO best_match_count
    FROM nfl_moneyline_market_evaluation_contributors AS contributor
    WHERE contributor.nfl_moneyline_market_evaluation_id = evaluation_id
      AND contributor.sportsbook_provider_identity_id
            = parent.best_price_sportsbook_provider_identity_id
      AND (
          (
              parent.selected_side = 'home'
              AND contributor.home_nfl_official_pregame_evidence_id
                    = parent.best_price_nfl_official_pregame_evidence_id
              AND contributor.home_american_price
                    = parent.best_american_price
          )
          OR (
              parent.selected_side = 'away'
              AND contributor.away_nfl_official_pregame_evidence_id
                    = parent.best_price_nfl_official_pregame_evidence_id
              AND contributor.away_american_price
                    = parent.best_american_price
          )
      );

    IF best_match_count <> 1 THEN
        RAISE EXCEPTION 'official NFL evaluation best price is outside contributor graph';
    END IF;

    SELECT
        sportsbook_provider_identity_id,
        CASE
            WHEN parent.selected_side = 'home'
                THEN home_nfl_official_pregame_evidence_id
            ELSE away_nfl_official_pregame_evidence_id
        END AS evidence_id,
        CASE
            WHEN parent.selected_side = 'home' THEN home_american_price
            ELSE away_american_price
        END AS american_price,
        CASE
            WHEN (
                CASE
                    WHEN parent.selected_side = 'home'
                        THEN home_american_price
                    ELSE away_american_price
                END
            ) > 0 THEN
                1 + (
                    CASE
                        WHEN parent.selected_side = 'home'
                            THEN home_american_price
                        ELSE away_american_price
                    END
                )::NUMERIC / 100
            ELSE
                1 + 100::NUMERIC / ABS(
                    CASE
                        WHEN parent.selected_side = 'home'
                            THEN home_american_price
                        ELSE away_american_price
                    END
                )
        END AS decimal_odds
    INTO expected_best
    FROM nfl_moneyline_market_evaluation_contributors
    WHERE nfl_moneyline_market_evaluation_id = evaluation_id
    ORDER BY decimal_odds DESC, sportsbook_provider_identity_id
    LIMIT 1;

    IF expected_best.sportsbook_provider_identity_id
            <> parent.best_price_sportsbook_provider_identity_id
       OR expected_best.evidence_id
            <> parent.best_price_nfl_official_pregame_evidence_id
       OR expected_best.american_price <> parent.best_american_price
       OR ABS(expected_best.decimal_odds - parent.best_decimal_odds)
            > 0.00000000000000005 THEN
        RAISE EXCEPTION 'official NFL evaluation best price is not deterministic';
    END IF;

    SELECT COUNT(*) INTO overlap_count
    FROM nfl_moneyline_market_evaluation_exclusions AS exclusion
    JOIN nfl_moneyline_market_evaluation_contributors AS contributor
      ON contributor.nfl_moneyline_market_evaluation_id
            = exclusion.nfl_moneyline_market_evaluation_id
     AND contributor.sportsbook_provider_identity_id
            = exclusion.sportsbook_provider_identity_id
    WHERE exclusion.nfl_moneyline_market_evaluation_id = evaluation_id;

    IF overlap_count <> 0 THEN
        RAISE EXCEPTION 'official NFL evaluation provider cannot be both contributor and exclusion';
    END IF;

    RETURN NULL;
END;
$$;

CREATE CONSTRAINT TRIGGER trg_validate_nfl_market_evaluation_graph_parent
AFTER INSERT ON nfl_moneyline_market_evaluations
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW
EXECUTE FUNCTION validate_nfl_market_evaluation_graph();

CREATE CONSTRAINT TRIGGER trg_validate_nfl_market_evaluation_graph_contributor
AFTER INSERT ON nfl_moneyline_market_evaluation_contributors
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW
EXECUTE FUNCTION validate_nfl_market_evaluation_graph();

CREATE CONSTRAINT TRIGGER trg_validate_nfl_market_evaluation_graph_exclusion
AFTER INSERT ON nfl_moneyline_market_evaluation_exclusions
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW
EXECUTE FUNCTION validate_nfl_market_evaluation_graph();

CREATE FUNCTION protect_nfl_market_evaluation_run_transition()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    parent RECORD;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'official NFL market evaluation run evidence is immutable';
    END IF;

    IF TG_OP = 'INSERT' THEN
        IF NEW.status <> 'running' THEN
            RAISE EXCEPTION 'new official NFL market evaluation runs must begin running';
        END IF;
        RETURN NEW;
    END IF;

    IF OLD.status IN ('completed', 'failed') THEN
        RAISE EXCEPTION 'terminal official NFL market evaluation runs are immutable';
    END IF;

    IF ROW(
        NEW.run_key,
        NEW.request_sha256,
        NEW.nfl_moneyline_game_prediction_id,
        NEW.nfl_moneyline_prediction_run_id,
        NEW.odds_ingestion_run_id,
        NEW.market_evaluation_protocol_version,
        NEW.market_evaluation_protocol_fingerprint,
        NEW.evaluation_kind,
        NEW.started_at
    ) IS DISTINCT FROM ROW(
        OLD.run_key,
        OLD.request_sha256,
        OLD.nfl_moneyline_game_prediction_id,
        OLD.nfl_moneyline_prediction_run_id,
        OLD.odds_ingestion_run_id,
        OLD.market_evaluation_protocol_version,
        OLD.market_evaluation_protocol_fingerprint,
        OLD.evaluation_kind,
        OLD.started_at
    ) THEN
        RAISE EXCEPTION 'official NFL market evaluation run identity is immutable';
    END IF;

    IF NEW.status = 'completed' THEN
        SELECT source_graph_fingerprint
        INTO parent
        FROM nfl_moneyline_market_evaluations
        WHERE nfl_moneyline_market_evaluation_id
            = NEW.nfl_moneyline_market_evaluation_id;
        IF NOT FOUND
           OR parent.source_graph_fingerprint
                <> NEW.source_graph_fingerprint THEN
            RAISE EXCEPTION 'completed evaluation run must reference its exact evaluation graph';
        END IF;
        NEW.completed_at := clock_timestamp();
    ELSIF NEW.status = 'failed' THEN
        NEW.failed_at := clock_timestamp();
    ELSE
        RAISE EXCEPTION 'invalid official NFL market evaluation run transition';
    END IF;

    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_protect_nfl_market_evaluation_run
BEFORE INSERT OR UPDATE OR DELETE
ON nfl_moneyline_market_evaluation_runs
FOR EACH ROW
EXECUTE FUNCTION protect_nfl_market_evaluation_run_transition();

CREATE FUNCTION reject_nfl_market_evaluation_mutation()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'official NFL market evaluation evidence is immutable';
END;
$$;

CREATE TRIGGER trg_nfl_market_evaluation_parent_immutable
BEFORE UPDATE OR DELETE ON nfl_moneyline_market_evaluations
FOR EACH ROW
EXECUTE FUNCTION reject_nfl_market_evaluation_mutation();

CREATE TRIGGER trg_nfl_market_evaluation_contributor_immutable
BEFORE UPDATE OR DELETE ON nfl_moneyline_market_evaluation_contributors
FOR EACH ROW
EXECUTE FUNCTION reject_nfl_market_evaluation_mutation();

CREATE TRIGGER trg_nfl_market_evaluation_exclusion_immutable
BEFORE UPDATE OR DELETE ON nfl_moneyline_market_evaluation_exclusions
FOR EACH ROW
EXECUTE FUNCTION reject_nfl_market_evaluation_mutation();

CREATE INDEX idx_nfl_market_evaluations_game
ON nfl_moneyline_market_evaluations(game_id, evaluation_created_at);

COMMENT ON TABLE nfl_moneyline_market_evaluations IS
    'One immutable official NFL entry-market evaluation per prediction and '
    'frozen market protocol. Exact contributors and exclusions are retained.';

COMMENT ON COLUMN nfl_moneyline_market_evaluations.source_graph_fingerprint IS
    'SHA-256 of the stable ordered prediction, odds-run, contributor, best-price, '
    'and exclusion source graph defined by protocol 0.1.0.';
