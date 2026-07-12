-- Migration 006
-- Generalized market analysis.

CREATE TABLE market_analysis (
    market_analysis_id BIGSERIAL PRIMARY KEY,

    odds_market_snapshot_id BIGINT NOT NULL
        REFERENCES odds_market_snapshots(odds_market_snapshot_id)
        ON DELETE CASCADE,

    implied_probability NUMERIC(10,8) NOT NULL,

    no_vig_probability NUMERIC(10,8),

    market_average_price NUMERIC(10,2),

    market_best_price INTEGER,

    sportsbook_count INTEGER,

    created_at TIMESTAMPTZ NOT NULL
        DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX idx_market_analysis_snapshot
ON market_analysis (odds_market_snapshot_id);