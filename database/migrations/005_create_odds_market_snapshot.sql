-- Migration 005
-- Create a generalized odds snapshot table that supports moneylines,
-- spreads, totals, team totals, first-five markets, and future props.

CREATE TABLE odds_market_snapshots (
    odds_market_snapshot_id BIGSERIAL PRIMARY KEY,

    game_id INTEGER NOT NULL
        REFERENCES games(game_id)
        ON DELETE CASCADE,

    sportsbook_id INTEGER NOT NULL
        REFERENCES sportsbooks(sportsbook_id)
        ON DELETE CASCADE,

    market_type VARCHAR(50) NOT NULL,

    selection_name VARCHAR(150) NOT NULL,

    line_value NUMERIC(10, 3),

    price INTEGER NOT NULL,

    snapshot_time TIMESTAMPTZ NOT NULL,

    source_name VARCHAR(50) NOT NULL DEFAULT 'odds_api',

    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_odds_market_snapshots_game
ON odds_market_snapshots (game_id);

CREATE INDEX idx_odds_market_snapshots_market
ON odds_market_snapshots (market_type);

CREATE INDEX idx_odds_market_snapshots_snapshot_time
ON odds_market_snapshots (snapshot_time);

CREATE INDEX idx_odds_market_snapshots_lookup
ON odds_market_snapshots (
    game_id,
    sportsbook_id,
    market_type,
    selection_name,
    snapshot_time
);