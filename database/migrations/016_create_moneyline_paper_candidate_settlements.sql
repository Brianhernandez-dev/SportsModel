CREATE TABLE moneyline_paper_candidate_settlements (
    moneyline_paper_candidate_settlement_id BIGSERIAL
        PRIMARY KEY,

    moneyline_prediction_market_evaluation_id BIGINT
        NOT NULL
        UNIQUE
        REFERENCES moneyline_prediction_market_evaluations (
            moneyline_prediction_market_evaluation_id
        )
        ON DELETE CASCADE,

    game_id BIGINT NOT NULL
        REFERENCES games (
            game_id
        )
        ON DELETE CASCADE,

    home_score INTEGER NOT NULL,

    away_score INTEGER NOT NULL,

    outcome VARCHAR(16) NOT NULL,

    profit_units NUMERIC(16, 10) NOT NULL,

    settled_at TIMESTAMPTZ NOT NULL
        DEFAULT CURRENT_TIMESTAMP,

    created_at TIMESTAMPTZ NOT NULL
        DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT chk_moneyline_paper_home_score
        CHECK (
            home_score >= 0
        ),

    CONSTRAINT chk_moneyline_paper_away_score
        CHECK (
            away_score >= 0
        ),

    CONSTRAINT chk_moneyline_paper_outcome
        CHECK (
            outcome IN (
                'win',
                'loss',
                'push'
            )
        ),

    CONSTRAINT chk_moneyline_paper_profit_by_outcome
        CHECK (
            (
                outcome = 'win'
                AND profit_units > 0
            )
            OR
            (
                outcome = 'loss'
                AND profit_units = -1
            )
            OR
            (
                outcome = 'push'
                AND profit_units = 0
            )
        )
);

CREATE INDEX idx_moneyline_paper_settlements_game
    ON moneyline_paper_candidate_settlements (
        game_id
    );

CREATE INDEX idx_moneyline_paper_settlements_outcome
    ON moneyline_paper_candidate_settlements (
        outcome
    );

CREATE INDEX idx_moneyline_paper_settlements_settled_at
    ON moneyline_paper_candidate_settlements (
        settled_at
    );
