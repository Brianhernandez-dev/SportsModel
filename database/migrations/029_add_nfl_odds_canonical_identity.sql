-- Migration 029
-- Add exact Odds API NFL team identities and immutable provider-event mapping
-- to existing canonical NFL games. No canonical teams or games are created.

CREATE TEMP TABLE odds_api_nfl_team_seed (
    abbreviation VARCHAR(4) PRIMARY KEY,
    provider_team_name VARCHAR(150) NOT NULL UNIQUE
) ON COMMIT DROP;

INSERT INTO odds_api_nfl_team_seed (
    abbreviation,
    provider_team_name
)
VALUES
    ('ARI', 'Arizona Cardinals'),
    ('ATL', 'Atlanta Falcons'),
    ('BAL', 'Baltimore Ravens'),
    ('BUF', 'Buffalo Bills'),
    ('CAR', 'Carolina Panthers'),
    ('CHI', 'Chicago Bears'),
    ('CIN', 'Cincinnati Bengals'),
    ('CLE', 'Cleveland Browns'),
    ('DAL', 'Dallas Cowboys'),
    ('DEN', 'Denver Broncos'),
    ('DET', 'Detroit Lions'),
    ('GB', 'Green Bay Packers'),
    ('HOU', 'Houston Texans'),
    ('IND', 'Indianapolis Colts'),
    ('JAX', 'Jacksonville Jaguars'),
    ('KC', 'Kansas City Chiefs'),
    ('LAC', 'Los Angeles Chargers'),
    ('LAR', 'Los Angeles Rams'),
    ('LV', 'Las Vegas Raiders'),
    ('MIA', 'Miami Dolphins'),
    ('MIN', 'Minnesota Vikings'),
    ('NE', 'New England Patriots'),
    ('NO', 'New Orleans Saints'),
    ('NYG', 'New York Giants'),
    ('NYJ', 'New York Jets'),
    ('PHI', 'Philadelphia Eagles'),
    ('PIT', 'Pittsburgh Steelers'),
    ('SEA', 'Seattle Seahawks'),
    ('SF', 'San Francisco 49ers'),
    ('TB', 'Tampa Bay Buccaneers'),
    ('TEN', 'Tennessee Titans'),
    ('WAS', 'Washington Commanders');

DO $migration$
BEGIN
    IF (
        SELECT COUNT(*)
        FROM odds_api_nfl_team_seed
    ) <> 32 THEN
        RAISE EXCEPTION
            'Odds API NFL identity seed must contain exactly 32 teams.';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM odds_api_nfl_team_seed AS seed
        LEFT JOIN nfl_team_profiles AS profile
          ON profile.current_abbreviation = seed.abbreviation
         AND profile.is_active IS TRUE
        WHERE profile.team_id IS NULL
    ) THEN
        RAISE EXCEPTION
            'Every Odds API NFL identity must resolve to one active '
            'canonical NFL team.';
    END IF;
END;
$migration$;

INSERT INTO nfl_team_sources (
    team_id,
    source_name,
    external_team_id,
    source_team_name
)
SELECT
    profile.team_id,
    'odds_api',
    seed.provider_team_name,
    seed.provider_team_name
FROM odds_api_nfl_team_seed AS seed
JOIN nfl_team_profiles AS profile
  ON profile.current_abbreviation = seed.abbreviation
 AND profile.is_active IS TRUE
ON CONFLICT (source_name, external_team_id) DO NOTHING;

DO $migration$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM odds_api_nfl_team_seed AS seed
        JOIN nfl_team_profiles AS profile
          ON profile.current_abbreviation = seed.abbreviation
        LEFT JOIN nfl_team_sources AS source
          ON source.source_name = 'odds_api'
         AND source.external_team_id = seed.provider_team_name
        WHERE source.team_id IS NULL
           OR source.team_id <> profile.team_id
    ) THEN
        RAISE EXCEPTION
            'An Odds API NFL team identity is missing or mapped to a '
            'different canonical team.';
    END IF;

    IF (
        SELECT COUNT(*)
        FROM nfl_team_sources
        WHERE source_name = 'odds_api'
    ) <> 32 THEN
        RAISE EXCEPTION
            'Exactly 32 Odds API NFL team identities are required.';
    END IF;
END;
$migration$;

CREATE UNIQUE INDEX uq_nfl_team_sources_odds_api_team
ON nfl_team_sources (team_id)
WHERE source_name = 'odds_api';

ALTER TABLE nfl_team_sources
ADD CONSTRAINT uq_nfl_team_sources_canonical_reference
UNIQUE (team_id, source_name, external_team_id);

CREATE FUNCTION protect_odds_api_nfl_team_identity()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF TG_OP = 'INSERT' AND NEW.source_name = 'odds_api' THEN
        RAISE EXCEPTION 'Odds API NFL team identities are immutable';
    END IF;
    IF TG_OP = 'INSERT' THEN
        RETURN NEW;
    END IF;

    IF OLD.source_name = 'odds_api'
       OR (TG_OP = 'UPDATE' AND NEW.source_name = 'odds_api') THEN
        RAISE EXCEPTION 'Odds API NFL team identities are immutable';
    END IF;

    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_odds_api_nfl_team_identity_immutable
BEFORE INSERT OR UPDATE OR DELETE ON nfl_team_sources
FOR EACH ROW
EXECUTE FUNCTION protect_odds_api_nfl_team_identity();

ALTER TABLE games
ADD CONSTRAINT uq_games_nfl_match_identity
UNIQUE (game_id, home_team_id, away_team_id);

CREATE TABLE nfl_odds_provider_event_mappings (
    nfl_odds_provider_event_mapping_id BIGSERIAL PRIMARY KEY,

    provider_name VARCHAR(100) NOT NULL,

    provider_sport_key VARCHAR(50) NOT NULL,

    external_event_id VARCHAR(255) NOT NULL,

    game_id INTEGER NOT NULL
        REFERENCES nfl_games(game_id)
        ON DELETE RESTRICT,

    canonical_home_team_id INTEGER NOT NULL,

    canonical_away_team_id INTEGER NOT NULL,

    provider_home_team_name VARCHAR(150) NOT NULL,

    provider_away_team_name VARCHAR(150) NOT NULL,

    canonical_kickoff TIMESTAMPTZ NOT NULL,

    first_provider_commence_time TIMESTAMPTZ NOT NULL,

    first_kickoff_drift_seconds DOUBLE PRECISION GENERATED ALWAYS AS (
        EXTRACT(
            EPOCH FROM (
                first_provider_commence_time - canonical_kickoff
            )
        )
    ) STORED,

    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT fk_nfl_odds_mapping_canonical_matchup
        FOREIGN KEY (
            game_id,
            canonical_home_team_id,
            canonical_away_team_id
        )
        REFERENCES games (
            game_id,
            home_team_id,
            away_team_id
        )
        ON DELETE RESTRICT,

    CONSTRAINT fk_nfl_odds_mapping_home_provider_team
        FOREIGN KEY (
            canonical_home_team_id,
            provider_name,
            provider_home_team_name
        )
        REFERENCES nfl_team_sources (
            team_id,
            source_name,
            external_team_id
        )
        ON DELETE RESTRICT,

    CONSTRAINT fk_nfl_odds_mapping_away_provider_team
        FOREIGN KEY (
            canonical_away_team_id,
            provider_name,
            provider_away_team_name
        )
        REFERENCES nfl_team_sources (
            team_id,
            source_name,
            external_team_id
        )
        ON DELETE RESTRICT,

    CONSTRAINT chk_nfl_odds_mapping_provider_identity
        CHECK (
            provider_name = 'odds_api'
            AND provider_sport_key = 'americanfootball_nfl'
            AND LENGTH(BTRIM(external_event_id)) > 0
            AND LENGTH(BTRIM(provider_home_team_name)) > 0
            AND LENGTH(BTRIM(provider_away_team_name)) > 0
            AND provider_home_team_name <> provider_away_team_name
        ),

    CONSTRAINT chk_nfl_odds_mapping_canonical_teams
        CHECK (canonical_home_team_id <> canonical_away_team_id),

    CONSTRAINT chk_nfl_odds_mapping_kickoff_drift
        CHECK (
            first_provider_commence_time
                BETWEEN canonical_kickoff - INTERVAL '15 minutes'
                    AND canonical_kickoff + INTERVAL '15 minutes'
        ),

    CONSTRAINT uq_nfl_odds_provider_event_identity
        UNIQUE (
            provider_name,
            provider_sport_key,
            external_event_id
        ),

    CONSTRAINT uq_nfl_odds_provider_event_reference
        UNIQUE (
            nfl_odds_provider_event_mapping_id,
            provider_name,
            provider_sport_key,
            external_event_id,
            provider_home_team_name,
            provider_away_team_name
        )
);

ALTER TABLE odds_provider_event_observations
ADD COLUMN nfl_odds_provider_event_mapping_id BIGINT;

ALTER TABLE odds_provider_event_observations
ADD CONSTRAINT fk_odds_event_observation_nfl_mapping
FOREIGN KEY (
    nfl_odds_provider_event_mapping_id,
    source_name,
    provider_sport_key,
    external_event_id,
    provider_home_team_name,
    provider_away_team_name
)
REFERENCES nfl_odds_provider_event_mappings (
    nfl_odds_provider_event_mapping_id,
    provider_name,
    provider_sport_key,
    external_event_id,
    provider_home_team_name,
    provider_away_team_name
)
ON DELETE RESTRICT;

ALTER TABLE odds_provider_event_observations
ADD CONSTRAINT chk_odds_event_observation_nfl_mapping
CHECK (
    nfl_odds_provider_event_mapping_id IS NULL
    OR provider_sport_key = 'americanfootball_nfl'
);

CREATE FUNCTION reject_nfl_odds_event_mapping_mutation()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'NFL Odds API provider-event mappings are immutable';
END;
$$;

CREATE TRIGGER trg_nfl_odds_provider_event_mapping_immutable
BEFORE UPDATE OR DELETE ON nfl_odds_provider_event_mappings
FOR EACH ROW
EXECUTE FUNCTION reject_nfl_odds_event_mapping_mutation();

COMMENT ON TABLE nfl_odds_provider_event_mappings IS
    'Immutable Odds API NFL event identity mapped to one existing canonical '
    'NFL game. Multiple provider event IDs may reference one game so reissues '
    'are retained rather than overwritten.';

COMMENT ON COLUMN
    nfl_odds_provider_event_mappings.first_kickoff_drift_seconds IS
    'Signed provider commence time minus canonical kickoff at first mapping; '
    'absolute drift is limited to the established 15-minute match boundary.';
