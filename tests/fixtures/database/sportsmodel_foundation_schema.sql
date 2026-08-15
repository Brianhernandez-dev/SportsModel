-- Test-only reconstruction of foundational DDL missing from migrations.
-- Derived from current repository queries and migrations 001-021.

CREATE TABLE teams (
    team_id SERIAL PRIMARY KEY,
    team_name VARCHAR(150) NOT NULL UNIQUE
);

-- Migration 013 requires the established canonical Athletics identity.
INSERT INTO teams (team_id, team_name) VALUES (5, 'Athletics');
SELECT setval(
    pg_get_serial_sequence('teams', 'team_id'),
    (SELECT MAX(team_id) FROM teams)
);

CREATE TABLE games (
    game_id SERIAL PRIMARY KEY,
    game_date TIMESTAMP NOT NULL,
    home_team_id INTEGER NOT NULL REFERENCES teams(team_id),
    away_team_id INTEGER NOT NULL REFERENCES teams(team_id)
);

CREATE TABLE sportsbooks (
    sportsbook_id SERIAL PRIMARY KEY,
    name VARCHAR(150) NOT NULL UNIQUE
);

CREATE TABLE historical_games (
    historical_game_id SERIAL PRIMARY KEY,
    mlb_game_id BIGINT NOT NULL UNIQUE,
    game_date DATE NOT NULL,
    home_team VARCHAR(150) NOT NULL,
    away_team VARCHAR(150) NOT NULL,
    home_score INTEGER NOT NULL,
    away_score INTEGER NOT NULL,
    home_win BOOLEAN NOT NULL
);
