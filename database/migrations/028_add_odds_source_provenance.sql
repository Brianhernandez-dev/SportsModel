-- Migration 028
-- Add provider identity and source-acquisition provenance without inventing
-- evidence for historical odds rows.

ALTER TABLE odds_ingestion_runs
ADD COLUMN request_path VARCHAR(255);

ALTER TABLE odds_ingestion_runs
ADD COLUMN request_regions VARCHAR(50);

ALTER TABLE odds_ingestion_runs
ADD COLUMN request_markets VARCHAR(100);

ALTER TABLE odds_ingestion_runs
ADD COLUMN request_odds_format VARCHAR(20);

ALTER TABLE odds_ingestion_runs
ADD COLUMN request_commence_time_from TIMESTAMPTZ;

ALTER TABLE odds_ingestion_runs
ADD COLUMN request_commence_time_to TIMESTAMPTZ;

ALTER TABLE odds_ingestion_runs
ADD COLUMN request_started_at TIMESTAMPTZ;

ALTER TABLE odds_ingestion_runs
ADD COLUMN response_received_at TIMESTAMPTZ;

ALTER TABLE odds_ingestion_runs
ADD CONSTRAINT chk_odds_ingestion_runs_request_context
CHECK (
    (
        request_path IS NULL
        AND request_regions IS NULL
        AND request_markets IS NULL
        AND request_odds_format IS NULL
        AND request_started_at IS NULL
    )
    OR (
        request_path IS NOT NULL
        AND request_regions IS NOT NULL
        AND request_markets IS NOT NULL
        AND request_odds_format IS NOT NULL
        AND request_started_at IS NOT NULL
        AND LENGTH(BTRIM(request_path)) > 0
        AND LENGTH(BTRIM(request_regions)) > 0
        AND LENGTH(BTRIM(request_markets)) > 0
        AND LENGTH(BTRIM(request_odds_format)) > 0
        AND POSITION('apikey' IN LOWER(request_path)) = 0
    )
);

ALTER TABLE odds_ingestion_runs
ADD CONSTRAINT chk_odds_ingestion_runs_request_window
CHECK (
    (
        request_commence_time_from IS NULL
        AND request_commence_time_to IS NULL
    )
    OR (
        request_commence_time_from IS NOT NULL
        AND request_commence_time_to IS NOT NULL
        AND request_started_at IS NOT NULL
        AND request_commence_time_from < request_commence_time_to
    )
);

ALTER TABLE odds_ingestion_runs
ADD CONSTRAINT chk_odds_ingestion_runs_response_time
CHECK (
    response_received_at IS NULL
    OR (
        request_started_at IS NOT NULL
        AND status_code IS NOT NULL
        AND response_received_at >= request_started_at
    )
);

ALTER TABLE odds_ingestion_runs
ADD CONSTRAINT uq_odds_ingestion_runs_source_observation
UNIQUE (
    odds_ingestion_run_id,
    sport,
    source_name,
    response_received_at
);

CREATE TABLE sportsbook_provider_identities (
    sportsbook_provider_identity_id BIGSERIAL PRIMARY KEY,

    provider_name VARCHAR(100) NOT NULL,

    provider_bookmaker_key VARCHAR(100) NOT NULL,

    sportsbook_id INTEGER NOT NULL
        REFERENCES sportsbooks(sportsbook_id)
        ON DELETE RESTRICT,

    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT chk_sportsbook_provider_identity_text
        CHECK (
            LENGTH(BTRIM(provider_name)) > 0
            AND LENGTH(BTRIM(provider_bookmaker_key)) > 0
        ),

    CONSTRAINT uq_sportsbook_provider_identity
        UNIQUE (provider_name, provider_bookmaker_key),

    CONSTRAINT uq_sportsbook_provider_per_book
        UNIQUE (sportsbook_id, provider_name),

    CONSTRAINT uq_sportsbook_provider_identity_reference
        UNIQUE (
            sportsbook_provider_identity_id,
            sportsbook_id,
            provider_name
        )
);

CREATE TABLE odds_provider_event_observations (
    odds_provider_event_observation_id BIGSERIAL PRIMARY KEY,

    odds_ingestion_run_id BIGINT NOT NULL,

    source_name VARCHAR(100) NOT NULL,

    provider_sport_key VARCHAR(50) NOT NULL,

    external_event_id VARCHAR(255) NOT NULL,

    provider_commence_time TIMESTAMPTZ NOT NULL,

    provider_home_team_name VARCHAR(150) NOT NULL,

    provider_away_team_name VARCHAR(150) NOT NULL,

    observed_at TIMESTAMPTZ NOT NULL,

    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_odds_event_observation_run_source
        FOREIGN KEY (
            odds_ingestion_run_id,
            provider_sport_key,
            source_name,
            observed_at
        )
        REFERENCES odds_ingestion_runs (
            odds_ingestion_run_id,
            sport,
            source_name,
            response_received_at
        )
        ON DELETE RESTRICT,

    CONSTRAINT chk_odds_event_observation_identity
        CHECK (
            LENGTH(BTRIM(source_name)) > 0
            AND LENGTH(BTRIM(provider_sport_key)) > 0
            AND LENGTH(BTRIM(external_event_id)) > 0
            AND LENGTH(BTRIM(provider_home_team_name)) > 0
            AND LENGTH(BTRIM(provider_away_team_name)) > 0
            AND provider_home_team_name <> provider_away_team_name
        ),

    CONSTRAINT uq_odds_event_observation_run_event
        UNIQUE (odds_ingestion_run_id, external_event_id),

    CONSTRAINT uq_odds_event_observation_snapshot_reference
        UNIQUE (
            odds_provider_event_observation_id,
            odds_ingestion_run_id,
            observed_at
        )
);

ALTER TABLE odds_market_snapshots
ADD COLUMN odds_provider_event_observation_id BIGINT;

ALTER TABLE odds_market_snapshots
ADD COLUMN sportsbook_provider_identity_id BIGINT;

ALTER TABLE odds_market_snapshots
ADD COLUMN bookmaker_title_at_observation VARCHAR(150);

ALTER TABLE odds_market_snapshots
ADD COLUMN bookmaker_updated_at TIMESTAMPTZ;

ALTER TABLE odds_market_snapshots
ADD COLUMN market_updated_at TIMESTAMPTZ;

ALTER TABLE odds_market_snapshots
ADD COLUMN observed_at TIMESTAMPTZ;

ALTER TABLE odds_market_snapshots
ADD CONSTRAINT fk_odds_snapshot_event_observation
FOREIGN KEY (
    odds_provider_event_observation_id,
    odds_ingestion_run_id,
    observed_at
)
REFERENCES odds_provider_event_observations (
    odds_provider_event_observation_id,
    odds_ingestion_run_id,
    observed_at
)
ON DELETE RESTRICT;

ALTER TABLE odds_market_snapshots
ADD CONSTRAINT fk_odds_snapshot_provider_sportsbook
FOREIGN KEY (
    sportsbook_provider_identity_id,
    sportsbook_id,
    source_name
)
REFERENCES sportsbook_provider_identities (
    sportsbook_provider_identity_id,
    sportsbook_id,
    provider_name
)
ON DELETE RESTRICT;

ALTER TABLE odds_market_snapshots
ADD CONSTRAINT chk_odds_snapshot_provider_provenance
CHECK (
    (
        odds_provider_event_observation_id IS NULL
        AND sportsbook_provider_identity_id IS NULL
        AND bookmaker_title_at_observation IS NULL
        AND bookmaker_updated_at IS NULL
        AND market_updated_at IS NULL
        AND observed_at IS NULL
    )
    OR (
        odds_provider_event_observation_id IS NOT NULL
        AND sportsbook_provider_identity_id IS NOT NULL
        AND bookmaker_title_at_observation IS NOT NULL
        AND LENGTH(BTRIM(bookmaker_title_at_observation)) > 0
        AND observed_at IS NOT NULL
        AND snapshot_time = observed_at
    )
);

CREATE UNIQUE INDEX uq_odds_snapshot_provider_selection
ON odds_market_snapshots (
    odds_ingestion_run_id,
    odds_provider_event_observation_id,
    sportsbook_provider_identity_id,
    market_type,
    selection_name
)
WHERE odds_provider_event_observation_id IS NOT NULL;

CREATE INDEX idx_odds_event_observation_provider_identity
ON odds_provider_event_observations (
    source_name,
    provider_sport_key,
    external_event_id
);

CREATE FUNCTION reject_odds_source_identity_mutation()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION '% rows are immutable', TG_TABLE_NAME;
END;
$$;

CREATE TRIGGER trg_sportsbook_provider_identity_immutable
BEFORE UPDATE OR DELETE ON sportsbook_provider_identities
FOR EACH ROW
EXECUTE FUNCTION reject_odds_source_identity_mutation();

CREATE TRIGGER trg_odds_event_observation_immutable
BEFORE UPDATE OR DELETE ON odds_provider_event_observations
FOR EACH ROW
EXECUTE FUNCTION reject_odds_source_identity_mutation();

CREATE FUNCTION protect_odds_snapshot_provenance()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.odds_provider_event_observation_id IS NOT NULL THEN
            RAISE EXCEPTION 'provenance-bearing odds snapshots are immutable';
        END IF;
        RETURN OLD;
    END IF;

    IF OLD.odds_provider_event_observation_id IS NOT NULL
       OR NEW.odds_provider_event_observation_id IS NOT NULL THEN
        RAISE EXCEPTION 'provenance-bearing odds snapshots are immutable';
    END IF;

    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_odds_snapshot_provenance_immutable
BEFORE UPDATE OR DELETE ON odds_market_snapshots
FOR EACH ROW
EXECUTE FUNCTION protect_odds_snapshot_provenance();

CREATE FUNCTION protect_odds_ingestion_run_provenance()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.request_started_at IS NOT NULL THEN
            RAISE EXCEPTION 'provenance-bearing odds ingestion runs cannot be deleted';
        END IF;
        RETURN OLD;
    END IF;

    IF OLD.request_started_at IS NOT NULL THEN
        IF NEW.sport IS DISTINCT FROM OLD.sport
           OR NEW.source_name IS DISTINCT FROM OLD.source_name
           OR NEW.started_at IS DISTINCT FROM OLD.started_at
           OR NEW.created_at IS DISTINCT FROM OLD.created_at
           OR NEW.target_date IS DISTINCT FROM OLD.target_date
           OR NEW.snapshot_role IS DISTINCT FROM OLD.snapshot_role
           OR NEW.request_path IS DISTINCT FROM OLD.request_path
           OR NEW.request_regions IS DISTINCT FROM OLD.request_regions
           OR NEW.request_markets IS DISTINCT FROM OLD.request_markets
           OR NEW.request_odds_format IS DISTINCT FROM OLD.request_odds_format
           OR NEW.request_commence_time_from IS DISTINCT FROM OLD.request_commence_time_from
           OR NEW.request_commence_time_to IS DISTINCT FROM OLD.request_commence_time_to
           OR NEW.request_started_at IS DISTINCT FROM OLD.request_started_at THEN
            RAISE EXCEPTION 'odds ingestion request provenance is immutable';
        END IF;

        IF OLD.response_received_at IS NOT NULL
           AND (
               NEW.response_received_at IS DISTINCT FROM OLD.response_received_at
               OR NEW.status_code IS DISTINCT FROM OLD.status_code
               OR NEW.remaining_requests IS DISTINCT FROM OLD.remaining_requests
               OR NEW.used_requests IS DISTINCT FROM OLD.used_requests
           ) THEN
            RAISE EXCEPTION 'odds ingestion response provenance is immutable';
        END IF;

        IF OLD.status IN ('completed', 'failed')
           AND NEW IS DISTINCT FROM OLD THEN
            RAISE EXCEPTION 'terminal provenance-bearing odds ingestion runs are immutable';
        END IF;
    END IF;

    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_odds_ingestion_run_provenance_immutable
BEFORE UPDATE OR DELETE ON odds_ingestion_runs
FOR EACH ROW
EXECUTE FUNCTION protect_odds_ingestion_run_provenance();

COMMENT ON TABLE sportsbook_provider_identities IS
    'Immutable mapping from a provider bookmaker key to one shared '
    'SportsModel sportsbook. Provider keys, not display titles, are identity.';

COMMENT ON TABLE odds_provider_event_observations IS
    'Immutable provider event identity observed in one odds response. No '
    'canonical NFL game mapping is implied.';

COMMENT ON COLUMN odds_ingestion_runs.request_path IS
    'Provider request path without query-string secrets or API keys.';

COMMENT ON COLUMN odds_ingestion_runs.response_received_at IS
    'Database timestamp recorded when SportsModel received the HTTP response.';

COMMENT ON COLUMN odds_market_snapshots.bookmaker_title_at_observation IS
    'Provider display title retained exactly for this observation; not identity.';
