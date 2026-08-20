-- Migration 026
-- Immutable 2026+ NFL Moneyline forward-prediction evidence.

CREATE TABLE nfl_moneyline_prediction_runs (
    nfl_moneyline_prediction_run_id BIGSERIAL PRIMARY KEY,
    run_key UUID NOT NULL UNIQUE,
    request_sha256 CHAR(64) NOT NULL,
    run_type VARCHAR(16) NOT NULL,
    evaluation_protocol_version VARCHAR(64) NOT NULL,
    routing_contract_version VARCHAR(64) NOT NULL,
    season INTEGER NOT NULL,
    target_date DATE NOT NULL,
    slate_start_time TIMESTAMPTZ NOT NULL,
    slate_end_time TIMESTAMPTZ NOT NULL,
    slate_fingerprint CHAR(64) NOT NULL,
    early_model_specification_version VARCHAR(100) NOT NULL,
    early_feature_schema_version VARCHAR(100) NOT NULL,
    early_specification_fingerprint CHAR(64) NOT NULL,
    early_model_fingerprint CHAR(64) NOT NULL,
    mature_model_specification_version VARCHAR(100) NOT NULL,
    mature_feature_schema_version VARCHAR(100) NOT NULL,
    mature_specification_fingerprint CHAR(64) NOT NULL,
    mature_model_fingerprint CHAR(64) NOT NULL,
    source_data_as_of TIMESTAMPTZ,
    source_snapshot_sha256 CHAR(64),
    prediction_set_sha256 CHAR(64),
    target_count INTEGER NOT NULL,
    prediction_count INTEGER NOT NULL DEFAULT 0,
    status VARCHAR(16) NOT NULL DEFAULT 'running',
    started_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    completed_at TIMESTAMPTZ,
    failed_at TIMESTAMPTZ,
    failure_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT uq_nfl_moneyline_run_identity
        UNIQUE (
            nfl_moneyline_prediction_run_id,
            run_type,
            evaluation_protocol_version
        ),
    CONSTRAINT chk_nfl_moneyline_runs_season CHECK (season >= 2026),
    CONSTRAINT chk_nfl_moneyline_runs_type
        CHECK (run_type IN ('official', 'preview')),
    CONSTRAINT chk_nfl_moneyline_runs_status
        CHECK (status IN ('running', 'completed', 'failed')),
    CONSTRAINT chk_nfl_moneyline_runs_window
        CHECK (slate_start_time < slate_end_time),
    CONSTRAINT chk_nfl_moneyline_runs_counts
        CHECK (
            target_count >= 0
            AND prediction_count >= 0
            AND prediction_count <= target_count
        ),
    CONSTRAINT chk_nfl_moneyline_runs_completion CHECK (
        (
            status = 'running'
            AND completed_at IS NULL
            AND failed_at IS NULL
            AND failure_message IS NULL
            AND source_data_as_of IS NULL
            AND source_snapshot_sha256 IS NULL
            AND prediction_set_sha256 IS NULL
        )
        OR (
            status = 'completed'
            AND completed_at IS NOT NULL
            AND failed_at IS NULL
            AND failure_message IS NULL
            AND source_data_as_of IS NOT NULL
            AND source_snapshot_sha256 IS NOT NULL
            AND prediction_set_sha256 IS NOT NULL
            AND target_count = prediction_count
        )
        OR (
            status = 'failed'
            AND completed_at IS NULL
            AND failed_at IS NOT NULL
            AND BTRIM(failure_message) <> ''
            AND prediction_count = 0
            AND source_data_as_of IS NULL
            AND source_snapshot_sha256 IS NULL
            AND prediction_set_sha256 IS NULL
        )
    ),
    CONSTRAINT chk_nfl_moneyline_runs_sha256 CHECK (
        request_sha256 ~ '^[0-9a-f]{64}$'
        AND slate_fingerprint ~ '^[0-9a-f]{64}$'
        AND (
            source_snapshot_sha256 IS NULL
            OR source_snapshot_sha256 ~ '^[0-9a-f]{64}$'
        )
        AND (
            prediction_set_sha256 IS NULL
            OR prediction_set_sha256 ~ '^[0-9a-f]{64}$'
        )
        AND early_specification_fingerprint ~ '^[0-9a-f]{64}$'
        AND early_model_fingerprint ~ '^[0-9a-f]{64}$'
        AND mature_specification_fingerprint ~ '^[0-9a-f]{64}$'
        AND mature_model_fingerprint ~ '^[0-9a-f]{64}$'
    )
);

CREATE TABLE nfl_moneyline_game_predictions (
    nfl_moneyline_game_prediction_id BIGSERIAL PRIMARY KEY,
    nfl_moneyline_prediction_run_id BIGINT NOT NULL,
    run_type VARCHAR(16) NOT NULL,
    evaluation_protocol_version VARCHAR(64) NOT NULL,
    game_id INTEGER NOT NULL REFERENCES nfl_games(game_id) ON DELETE RESTRICT,
    season INTEGER NOT NULL,
    target_kickoff TIMESTAMPTZ NOT NULL,
    prediction_created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    home_team_id INTEGER NOT NULL REFERENCES teams(team_id) ON DELETE RESTRICT,
    away_team_id INTEGER NOT NULL REFERENCES teams(team_id) ON DELETE RESTRICT,
    neutral_site BOOLEAN NOT NULL,
    feature_cutoff TIMESTAMPTZ NOT NULL,
    source_data_as_of TIMESTAMPTZ NOT NULL,
    home_current_prior_games INTEGER NOT NULL,
    away_current_prior_games INTEGER NOT NULL,
    selected_route VARCHAR(16) NOT NULL,
    routing_contract_version VARCHAR(64) NOT NULL,
    selected_model_specification_version VARCHAR(100) NOT NULL,
    feature_schema_version VARCHAR(100) NOT NULL,
    specification_fingerprint CHAR(64) NOT NULL,
    model_fingerprint CHAR(64) NOT NULL,
    feature_payload JSONB NOT NULL,
    feature_vector_sha256 CHAR(64) NOT NULL,
    source_trace_payload JSONB NOT NULL,
    source_trace_sha256 CHAR(64) NOT NULL,
    latest_source_kickoff TIMESTAMPTZ,
    model_home_win_probability NUMERIC(18, 16) NOT NULL,
    frozen_route_home_baseline_probability NUMERIC(18, 16) NOT NULL,
    classification_threshold NUMERIC(18, 16) NOT NULL,
    predicted_side VARCHAR(8) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT fk_nfl_moneyline_prediction_run_identity
        FOREIGN KEY (
            nfl_moneyline_prediction_run_id,
            run_type,
            evaluation_protocol_version
        ) REFERENCES nfl_moneyline_prediction_runs (
            nfl_moneyline_prediction_run_id,
            run_type,
            evaluation_protocol_version
        ) ON DELETE RESTRICT,
    CONSTRAINT uq_nfl_moneyline_prediction_run_game
        UNIQUE (nfl_moneyline_prediction_run_id, game_id),
    CONSTRAINT chk_nfl_moneyline_predictions_season CHECK (season >= 2026),
    CONSTRAINT chk_nfl_moneyline_predictions_teams
        CHECK (home_team_id <> away_team_id),
    CONSTRAINT chk_nfl_moneyline_predictions_time CHECK (
        prediction_created_at < target_kickoff
        AND feature_cutoff = target_kickoff
        AND source_data_as_of <= prediction_created_at
        AND (
            latest_source_kickoff IS NULL
            OR latest_source_kickoff < feature_cutoff
        )
    ),
    CONSTRAINT chk_nfl_moneyline_predictions_counts CHECK (
        home_current_prior_games >= 0
        AND away_current_prior_games >= 0
    ),
    CONSTRAINT chk_nfl_moneyline_predictions_route CHECK (
        (
            selected_route = 'mature'
            AND home_current_prior_games >= 3
            AND away_current_prior_games >= 3
        )
        OR (
            selected_route = 'early'
            AND (
                home_current_prior_games < 3
                OR away_current_prior_games < 3
            )
        )
    ),
    CONSTRAINT chk_nfl_moneyline_predictions_probabilities CHECK (
        model_home_win_probability BETWEEN 0 AND 1
        AND frozen_route_home_baseline_probability BETWEEN 0 AND 1
        AND classification_threshold BETWEEN 0 AND 1
    ),
    CONSTRAINT chk_nfl_moneyline_predictions_side CHECK (
        (
            predicted_side = 'home'
            AND model_home_win_probability >= classification_threshold
        )
        OR (
            predicted_side = 'away'
            AND model_home_win_probability < classification_threshold
        )
    ),
    CONSTRAINT chk_nfl_moneyline_predictions_sha256 CHECK (
        specification_fingerprint ~ '^[0-9a-f]{64}$'
        AND model_fingerprint ~ '^[0-9a-f]{64}$'
        AND feature_vector_sha256 ~ '^[0-9a-f]{64}$'
        AND source_trace_sha256 ~ '^[0-9a-f]{64}$'
    ),
    CONSTRAINT chk_nfl_moneyline_predictions_payloads CHECK (
        jsonb_typeof(feature_payload) = 'object'
        AND jsonb_typeof(source_trace_payload) = 'object'
    )
);

CREATE UNIQUE INDEX uq_nfl_moneyline_official_game_protocol
    ON nfl_moneyline_game_predictions (
        evaluation_protocol_version,
        game_id
    ) WHERE run_type = 'official';

CREATE INDEX idx_nfl_moneyline_predictions_game
    ON nfl_moneyline_game_predictions(game_id, prediction_created_at);
CREATE INDEX idx_nfl_moneyline_predictions_run
    ON nfl_moneyline_game_predictions(nfl_moneyline_prediction_run_id);
CREATE INDEX idx_nfl_moneyline_runs_window
    ON nfl_moneyline_prediction_runs(season, slate_start_time, slate_end_time);

CREATE FUNCTION protect_nfl_moneyline_prediction_run_transition()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE
    actual_prediction_count BIGINT;
BEGIN
    IF OLD.status IN ('completed', 'failed') THEN
        RAISE EXCEPTION 'terminal NFL prediction runs are immutable';
    END IF;
    IF OLD.status = 'running' AND NEW.status NOT IN ('running', 'completed', 'failed') THEN
        RAISE EXCEPTION 'invalid NFL prediction run status transition';
    END IF;
    IF NEW.status IN ('completed', 'failed') THEN
        SELECT COUNT(*) INTO actual_prediction_count
        FROM nfl_moneyline_game_predictions
        WHERE nfl_moneyline_prediction_run_id = OLD.nfl_moneyline_prediction_run_id;
    END IF;
    IF NEW.status = 'completed' THEN
        IF actual_prediction_count <> NEW.prediction_count
           OR actual_prediction_count <> NEW.target_count THEN
            RAISE EXCEPTION 'completed NFL prediction run count does not match children';
        END IF;
    END IF;
    IF NEW.status = 'failed' AND actual_prediction_count <> 0 THEN
        RAISE EXCEPTION 'failed NFL prediction run cannot retain child predictions';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_nfl_moneyline_run_transition
BEFORE UPDATE ON nfl_moneyline_prediction_runs
FOR EACH ROW EXECUTE FUNCTION protect_nfl_moneyline_prediction_run_transition();

CREATE FUNCTION prevent_nfl_moneyline_prediction_run_delete()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'NFL prediction run evidence cannot be deleted';
END;
$$;

CREATE TRIGGER trg_prevent_nfl_moneyline_prediction_run_delete
BEFORE DELETE ON nfl_moneyline_prediction_runs
FOR EACH ROW EXECUTE FUNCTION prevent_nfl_moneyline_prediction_run_delete();

CREATE FUNCTION validate_nfl_moneyline_prediction_insert()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE
    canonical RECORD;
    parent_run RECORD;
BEGIN
    NEW.prediction_created_at := clock_timestamp();
    NEW.created_at := NEW.prediction_created_at;

    SELECT status, routing_contract_version,
           early_model_specification_version,
           early_feature_schema_version,
           early_specification_fingerprint,
           early_model_fingerprint,
           mature_model_specification_version,
           mature_feature_schema_version,
           mature_specification_fingerprint,
           mature_model_fingerprint
    INTO parent_run
    FROM nfl_moneyline_prediction_runs
    WHERE nfl_moneyline_prediction_run_id = NEW.nfl_moneyline_prediction_run_id
    FOR KEY SHARE;
    IF parent_run.status IS DISTINCT FROM 'running' THEN
        RAISE EXCEPTION 'NFL prediction parent run must be running';
    END IF;
    IF NEW.routing_contract_version <> parent_run.routing_contract_version THEN
        RAISE EXCEPTION 'NFL prediction routing contract identity mismatch';
    END IF;
    IF NEW.selected_route = 'early' AND (
        NEW.selected_model_specification_version
            <> parent_run.early_model_specification_version
        OR NEW.feature_schema_version
            <> parent_run.early_feature_schema_version
        OR NEW.specification_fingerprint
            <> parent_run.early_specification_fingerprint
        OR NEW.model_fingerprint <> parent_run.early_model_fingerprint
    ) THEN
        RAISE EXCEPTION 'NFL prediction early artifact identity mismatch';
    END IF;
    IF NEW.selected_route = 'mature' AND (
        NEW.selected_model_specification_version
            <> parent_run.mature_model_specification_version
        OR NEW.feature_schema_version
            <> parent_run.mature_feature_schema_version
        OR NEW.specification_fingerprint
            <> parent_run.mature_specification_fingerprint
        OR NEW.model_fingerprint <> parent_run.mature_model_fingerprint
    ) THEN
        RAISE EXCEPTION 'NFL prediction mature artifact identity mismatch';
    END IF;

    SELECT
        nfl.season,
        nfl.scheduled_start_time,
        nfl.status,
        nfl.neutral_site,
        game.home_team_id,
        game.away_team_id
    INTO canonical
    FROM nfl_games AS nfl
    JOIN games AS game ON game.game_id = nfl.game_id
    WHERE nfl.game_id = NEW.game_id
    FOR KEY SHARE OF nfl, game;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'canonical NFL target game does not exist';
    END IF;
    IF canonical.season <> NEW.season
       OR canonical.scheduled_start_time <> NEW.target_kickoff
       OR canonical.home_team_id <> NEW.home_team_id
       OR canonical.away_team_id <> NEW.away_team_id
       OR canonical.neutral_site <> NEW.neutral_site THEN
        RAISE EXCEPTION 'persisted NFL prediction target identity mismatch';
    END IF;
    IF canonical.status <> 'unplayed' THEN
        RAISE EXCEPTION 'NFL prediction target must still be unplayed';
    END IF;
    IF NEW.prediction_created_at >= NEW.target_kickoff THEN
        RAISE EXCEPTION 'NFL prediction must be persisted strictly before kickoff';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_validate_nfl_moneyline_prediction_insert
BEFORE INSERT ON nfl_moneyline_game_predictions
FOR EACH ROW EXECUTE FUNCTION validate_nfl_moneyline_prediction_insert();

CREATE FUNCTION prevent_nfl_moneyline_prediction_mutation()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'NFL forward prediction evidence is append-only';
END;
$$;

CREATE TRIGGER trg_prevent_nfl_moneyline_prediction_update
BEFORE UPDATE ON nfl_moneyline_game_predictions
FOR EACH ROW EXECUTE FUNCTION prevent_nfl_moneyline_prediction_mutation();

CREATE TRIGGER trg_prevent_nfl_moneyline_prediction_delete
BEFORE DELETE ON nfl_moneyline_game_predictions
FOR EACH ROW EXECUTE FUNCTION prevent_nfl_moneyline_prediction_mutation();
