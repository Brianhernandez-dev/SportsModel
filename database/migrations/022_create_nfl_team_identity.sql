-- Add canonical NFL franchise, season, and provider identity.
-- This migration assumes the established shared teams table.

CREATE TABLE nfl_team_profiles (
    team_id INTEGER PRIMARY KEY
        REFERENCES teams(team_id)
        ON DELETE CASCADE,
    franchise_key VARCHAR(50) NOT NULL UNIQUE,
    current_abbreviation VARCHAR(4) NOT NULL UNIQUE,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT chk_nfl_team_profiles_franchise_key
        CHECK (
            franchise_key ~
            '^nfl_franchise_[0-9a-f]{8}-[0-9a-f]{4}-'
            '[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
        ),
    CONSTRAINT chk_nfl_team_profiles_abbreviation
        CHECK (current_abbreviation ~ '^[A-Z0-9]{1,4}$')
);

CREATE TABLE nfl_team_seasons (
    team_id INTEGER NOT NULL
        REFERENCES nfl_team_profiles(team_id)
        ON DELETE CASCADE,
    season SMALLINT NOT NULL,
    display_name VARCHAR(150) NOT NULL,
    abbreviation VARCHAR(4) NOT NULL,
    conference VARCHAR(3) NOT NULL,
    division VARCHAR(5) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (team_id, season),
    CONSTRAINT chk_nfl_team_seasons_season
        CHECK (season BETWEEN 1920 AND 2100),
    CONSTRAINT chk_nfl_team_seasons_abbreviation
        CHECK (abbreviation ~ '^[A-Z0-9]{1,4}$'),
    CONSTRAINT chk_nfl_team_seasons_conference
        CHECK (conference IN ('AFC', 'NFC')),
    CONSTRAINT chk_nfl_team_seasons_division
        CHECK (division IN ('East', 'North', 'South', 'West'))
);

CREATE INDEX idx_nfl_team_seasons_season
    ON nfl_team_seasons(season, abbreviation);

CREATE TABLE nfl_team_sources (
    nfl_team_source_id BIGSERIAL PRIMARY KEY,
    team_id INTEGER NOT NULL
        REFERENCES nfl_team_profiles(team_id)
        ON DELETE CASCADE,
    source_name VARCHAR(50) NOT NULL,
    external_team_id VARCHAR(100) NOT NULL,
    source_team_name VARCHAR(150),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_nfl_team_sources_identity
        UNIQUE (source_name, external_team_id)
);

CREATE INDEX idx_nfl_team_sources_team
    ON nfl_team_sources(team_id);

CREATE TEMP TABLE nfl_team_seed (
    abbreviation VARCHAR(4) PRIMARY KEY,
    display_name VARCHAR(150) NOT NULL UNIQUE,
    franchise_key VARCHAR(50) NOT NULL UNIQUE,
    external_team_id VARCHAR(100) NOT NULL UNIQUE,
    conference VARCHAR(3) NOT NULL,
    division VARCHAR(5) NOT NULL
) ON COMMIT DROP;

INSERT INTO nfl_team_seed (
    abbreviation,
    display_name,
    franchise_key,
    external_team_id,
    conference,
    division
)
VALUES
    ('ARI', 'Arizona Cardinals', 'nfl_franchise_115e5e7f-0cb9-4961-a6a2-4baa5ca5c26f', '3800', 'NFC', 'West'),
    ('ATL', 'Atlanta Falcons', 'nfl_franchise_b3858db8-e9c2-4b8e-ae9f-123a4c50f889', '0200', 'NFC', 'South'),
    ('BAL', 'Baltimore Ravens', 'nfl_franchise_e863c688-dc34-4162-a7b9-14046d58cb38', '0325', 'AFC', 'North'),
    ('BUF', 'Buffalo Bills', 'nfl_franchise_fda0b8a1-0aad-487c-87d8-84a00d391883', '0610', 'AFC', 'East'),
    ('CAR', 'Carolina Panthers', 'nfl_franchise_c2b948de-c850-4650-8b46-eb9cad5d4053', '0750', 'NFC', 'South'),
    ('CHI', 'Chicago Bears', 'nfl_franchise_c2520914-b975-4104-9e09-44a75f7646ae', '0810', 'NFC', 'North'),
    ('CIN', 'Cincinnati Bengals', 'nfl_franchise_0a310342-3970-40d0-95c8-7b76eaf2c1cb', '0920', 'AFC', 'North'),
    ('CLE', 'Cleveland Browns', 'nfl_franchise_1a2ea8e6-1a06-4d3c-b9ff-f4ae03ec5b3e', '1050', 'AFC', 'North'),
    ('DAL', 'Dallas Cowboys', 'nfl_franchise_489074c2-530d-4a37-b49a-f7962a244711', '1200', 'NFC', 'East'),
    ('DEN', 'Denver Broncos', 'nfl_franchise_ce4ecf15-e728-4f42-9816-f70837f92330', '1400', 'AFC', 'West'),
    ('DET', 'Detroit Lions', 'nfl_franchise_687f1069-42be-4754-89ec-13e9050fdaab', '1540', 'NFC', 'North'),
    ('GB', 'Green Bay Packers', 'nfl_franchise_17017ab6-18a7-4286-a6b4-8685dd563a7d', '1800', 'NFC', 'North'),
    ('HOU', 'Houston Texans', 'nfl_franchise_9ac40ed9-1eea-432f-82b2-34e74af626a7', '2120', 'AFC', 'South'),
    ('IND', 'Indianapolis Colts', 'nfl_franchise_ad460023-10c8-49fb-9c28-8e55c93614a4', '2200', 'AFC', 'South'),
    ('JAX', 'Jacksonville Jaguars', 'nfl_franchise_75ec423d-3492-4987-b0bf-e2ba91be322c', '2250', 'AFC', 'South'),
    ('KC', 'Kansas City Chiefs', 'nfl_franchise_915aed3c-024b-4379-b4e5-4b59479ed602', '2310', 'AFC', 'West'),
    ('LAR', 'Los Angeles Rams', 'nfl_franchise_f0342fdc-9a08-44c2-a103-b6de72ef814b', '2510', 'NFC', 'West'),
    ('LAC', 'Los Angeles Chargers', 'nfl_franchise_d858ba3e-b5b4-4809-9eaf-ec1304c69143', '4400', 'AFC', 'West'),
    ('LV', 'Las Vegas Raiders', 'nfl_franchise_38f7d31e-ff94-48ec-905a-0c80ca64c6db', '2520', 'AFC', 'West'),
    ('MIA', 'Miami Dolphins', 'nfl_franchise_596f0922-8fdb-4582-b447-9b87983796b4', '2700', 'AFC', 'East'),
    ('MIN', 'Minnesota Vikings', 'nfl_franchise_4d1ec3d0-ff6e-45b9-9698-1f5865e53cc1', '3000', 'NFC', 'North'),
    ('NE', 'New England Patriots', 'nfl_franchise_24b047b4-b850-4302-9ae2-02d68c0e17b8', '3200', 'AFC', 'East'),
    ('NO', 'New Orleans Saints', 'nfl_franchise_1cefa7b3-6fbc-4b5f-8c32-619b5d13d1dd', '3300', 'NFC', 'South'),
    ('NYG', 'New York Giants', 'nfl_franchise_8b1089c9-36a0-47b7-a4ec-70857aab3983', '3410', 'NFC', 'East'),
    ('NYJ', 'New York Jets', 'nfl_franchise_1ed0c65d-5289-4e65-8bc3-300c55300651', '3430', 'AFC', 'East'),
    ('PHI', 'Philadelphia Eagles', 'nfl_franchise_00d8ea72-b2e8-4e77-a896-1d8433f5451e', '3700', 'NFC', 'East'),
    ('PIT', 'Pittsburgh Steelers', 'nfl_franchise_68b5675c-4ae0-4887-908c-9660be3de985', '3900', 'AFC', 'North'),
    ('SEA', 'Seattle Seahawks', 'nfl_franchise_c7d92ba5-691d-4920-8322-c9828e7677aa', '4600', 'NFC', 'West'),
    ('SF', 'San Francisco 49ers', 'nfl_franchise_9991f726-999f-45fe-83e4-46934f7ad813', '4500', 'NFC', 'West'),
    ('TB', 'Tampa Bay Buccaneers', 'nfl_franchise_f2ca15b6-8ef8-4660-9b98-7d02bfdce443', '4900', 'NFC', 'South'),
    ('TEN', 'Tennessee Titans', 'nfl_franchise_bde17090-5331-4064-a50a-67b5da0d41d8', '2100', 'AFC', 'South'),
    ('WAS', 'Washington Commanders', 'nfl_franchise_6af2f784-b3c7-4127-bb0b-cb23ecb91f80', '5110', 'NFC', 'East');

INSERT INTO teams (team_name)
SELECT display_name
FROM nfl_team_seed
ON CONFLICT (team_name) DO NOTHING;

INSERT INTO nfl_team_profiles (
    team_id,
    franchise_key,
    current_abbreviation,
    is_active
)
SELECT
    team.team_id,
    seed.franchise_key,
    seed.abbreviation,
    TRUE
FROM nfl_team_seed AS seed
JOIN teams AS team
  ON team.team_name = seed.display_name
ON CONFLICT (team_id)
DO UPDATE SET
    franchise_key = EXCLUDED.franchise_key,
    current_abbreviation = EXCLUDED.current_abbreviation,
    is_active = TRUE,
    updated_at = CURRENT_TIMESTAMP;

INSERT INTO nfl_team_seasons (
    team_id,
    season,
    display_name,
    abbreviation,
    conference,
    division
)
SELECT
    team.team_id,
    2026,
    seed.display_name,
    seed.abbreviation,
    seed.conference,
    seed.division
FROM nfl_team_seed AS seed
JOIN teams AS team
  ON team.team_name = seed.display_name
ON CONFLICT (team_id, season)
DO UPDATE SET
    display_name = EXCLUDED.display_name,
    abbreviation = EXCLUDED.abbreviation,
    conference = EXCLUDED.conference,
    division = EXCLUDED.division,
    updated_at = CURRENT_TIMESTAMP;

INSERT INTO nfl_team_sources (
    team_id,
    source_name,
    external_team_id,
    source_team_name
)
SELECT
    team.team_id,
    'nflverse',
    seed.external_team_id,
    seed.display_name
FROM nfl_team_seed AS seed
JOIN teams AS team
  ON team.team_name = seed.display_name
ON CONFLICT (source_name, external_team_id)
DO UPDATE SET
    source_team_name = EXCLUDED.source_team_name,
    updated_at = CURRENT_TIMESTAMP
WHERE nfl_team_sources.team_id = EXCLUDED.team_id;

DO $migration$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM nfl_team_seed AS seed
        JOIN nfl_team_sources AS source
          ON source.source_name = 'nflverse'
         AND source.external_team_id = seed.external_team_id
        JOIN teams AS team
          ON team.team_name = seed.display_name
        WHERE source.team_id <> team.team_id
    ) THEN
        RAISE EXCEPTION
            'An nflverse team ID is mapped to a different franchise.';
    END IF;

    IF (
        SELECT COUNT(*)
        FROM nfl_team_seed
    ) <> 32 THEN
        RAISE EXCEPTION 'NFL franchise seed must contain exactly 32 rows.';
    END IF;
END;
$migration$;
