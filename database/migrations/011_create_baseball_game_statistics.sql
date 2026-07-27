-- Migration 011
-- Create historical team game statistics, player pitching appearances,
-- and canonical game context required for MLB feature engineering.

ALTER TABLE games
ADD COLUMN scheduled_innings SMALLINT,
ADD COLUMN doubleheader_status VARCHAR(20),
ADD COLUMN game_number SMALLINT;

ALTER TABLE games
ADD CONSTRAINT chk_games_scheduled_innings
    CHECK (
        scheduled_innings IS NULL
        OR scheduled_innings > 0
    );

ALTER TABLE games
ADD CONSTRAINT chk_games_doubleheader_status
    CHECK (
        doubleheader_status IS NULL
        OR doubleheader_status IN (
            'single',
            'doubleheader'
        )
    );

ALTER TABLE games
ADD CONSTRAINT chk_games_game_number
    CHECK (
        game_number IS NULL
        OR game_number > 0
    );


CREATE TABLE team_game_statistics (
    team_game_statistics_id BIGSERIAL PRIMARY KEY,

    game_id INTEGER NOT NULL
        REFERENCES games (game_id)
        ON DELETE CASCADE,

    team_id INTEGER NOT NULL
        REFERENCES teams (team_id)
        ON DELETE CASCADE,

    is_home BOOLEAN NOT NULL,

    runs INTEGER NOT NULL,
    hits INTEGER NOT NULL,
    errors INTEGER NOT NULL,

    at_bats INTEGER NOT NULL,
    plate_appearances INTEGER,

    doubles INTEGER NOT NULL,
    triples INTEGER NOT NULL,
    home_runs INTEGER NOT NULL,

    walks INTEGER NOT NULL,
    intentional_walks INTEGER NOT NULL,

    strikeouts INTEGER NOT NULL,
    hit_by_pitch INTEGER NOT NULL,
    sacrifice_flies INTEGER NOT NULL,

    stolen_bases INTEGER NOT NULL,
    caught_stealing INTEGER NOT NULL,

    pitching_outs INTEGER NOT NULL,

    runs_allowed INTEGER NOT NULL,
    earned_runs_allowed INTEGER NOT NULL,
    hits_allowed INTEGER NOT NULL,
    home_runs_allowed INTEGER NOT NULL,
    walks_allowed INTEGER NOT NULL,
    strikeouts_recorded INTEGER NOT NULL,

    left_on_base INTEGER,
    double_plays INTEGER,

    source_name VARCHAR(50) NOT NULL,

    created_at TIMESTAMPTZ NOT NULL
        DEFAULT CURRENT_TIMESTAMP,

    updated_at TIMESTAMPTZ NOT NULL
        DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT uq_team_game_statistics
        UNIQUE (game_id, team_id),

    CONSTRAINT chk_team_game_statistics_runs
        CHECK (runs >= 0),

    CONSTRAINT chk_team_game_statistics_hits
        CHECK (hits >= 0),

    CONSTRAINT chk_team_game_statistics_errors
        CHECK (errors >= 0),

    CONSTRAINT chk_team_game_statistics_at_bats
        CHECK (at_bats >= 0),

    CONSTRAINT chk_team_game_statistics_plate_appearances
        CHECK (
            plate_appearances IS NULL
            OR plate_appearances >= 0
        ),

    CONSTRAINT chk_team_game_statistics_extra_base_hits
        CHECK (
            doubles >= 0
            AND triples >= 0
            AND home_runs >= 0
        ),

    CONSTRAINT chk_team_game_statistics_walks
        CHECK (
            walks >= 0
            AND intentional_walks >= 0
        ),

    CONSTRAINT chk_team_game_statistics_batting_events
        CHECK (
            strikeouts >= 0
            AND hit_by_pitch >= 0
            AND sacrifice_flies >= 0
        ),

    CONSTRAINT chk_team_game_statistics_running
        CHECK (
            stolen_bases >= 0
            AND caught_stealing >= 0
        ),

    CONSTRAINT chk_team_game_statistics_pitching_outs
        CHECK (pitching_outs >= 0),

    CONSTRAINT chk_team_game_statistics_runs_allowed
        CHECK (
            runs_allowed >= 0
            AND earned_runs_allowed >= 0
            AND earned_runs_allowed <= runs_allowed
        ),

    CONSTRAINT chk_team_game_statistics_pitching_events
        CHECK (
            hits_allowed >= 0
            AND home_runs_allowed >= 0
            AND walks_allowed >= 0
            AND strikeouts_recorded >= 0
        ),

    CONSTRAINT chk_team_game_statistics_optional_counts
        CHECK (
            (
                left_on_base IS NULL
                OR left_on_base >= 0
            )
            AND (
                double_plays IS NULL
                OR double_plays >= 0
            )
        )
);


CREATE TABLE player_game_pitching_statistics (
    player_game_pitching_statistics_id BIGSERIAL PRIMARY KEY,

    game_id INTEGER NOT NULL
        REFERENCES games (game_id)
        ON DELETE CASCADE,

    team_id INTEGER NOT NULL
        REFERENCES teams (team_id)
        ON DELETE CASCADE,

    baseball_player_id BIGINT NOT NULL
        REFERENCES baseball_players (baseball_player_id)
        ON DELETE CASCADE,

    appearance_order SMALLINT NOT NULL,

    is_starter BOOLEAN NOT NULL,

    pitching_outs INTEGER NOT NULL,

    batters_faced INTEGER,

    hits_allowed INTEGER NOT NULL,
    runs_allowed INTEGER NOT NULL,
    earned_runs_allowed INTEGER NOT NULL,
    home_runs_allowed INTEGER NOT NULL,

    walks_allowed INTEGER NOT NULL,
    intentional_walks_allowed INTEGER NOT NULL,

    strikeouts INTEGER NOT NULL,
    hit_batters INTEGER NOT NULL,

    pitches_thrown INTEGER,
    strikes_thrown INTEGER,

    decision VARCHAR(10),

    save_recorded BOOLEAN NOT NULL DEFAULT FALSE,
    hold_recorded BOOLEAN NOT NULL DEFAULT FALSE,
    blown_save_recorded BOOLEAN NOT NULL DEFAULT FALSE,

    source_name VARCHAR(50) NOT NULL,

    created_at TIMESTAMPTZ NOT NULL
        DEFAULT CURRENT_TIMESTAMP,

    updated_at TIMESTAMPTZ NOT NULL
        DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT uq_player_game_pitching_statistics
        UNIQUE (game_id, baseball_player_id),

    CONSTRAINT uq_player_game_pitching_appearance_order
        UNIQUE (game_id, team_id, appearance_order),

    CONSTRAINT chk_player_game_pitching_appearance_order
        CHECK (appearance_order > 0),

    CONSTRAINT chk_player_game_pitching_outs
        CHECK (pitching_outs >= 0),

    CONSTRAINT chk_player_game_pitching_batters_faced
        CHECK (
            batters_faced IS NULL
            OR batters_faced >= 0
        ),

    CONSTRAINT chk_player_game_pitching_runs
        CHECK (
            runs_allowed >= 0
            AND earned_runs_allowed >= 0
            AND earned_runs_allowed <= runs_allowed
        ),

    CONSTRAINT chk_player_game_pitching_events
        CHECK (
            hits_allowed >= 0
            AND home_runs_allowed >= 0
            AND walks_allowed >= 0
            AND intentional_walks_allowed >= 0
            AND strikeouts >= 0
            AND hit_batters >= 0
        ),

    CONSTRAINT chk_player_game_pitching_pitches
        CHECK (
            (
                pitches_thrown IS NULL
                OR pitches_thrown >= 0
            )
            AND (
                strikes_thrown IS NULL
                OR strikes_thrown >= 0
            )
            AND (
                pitches_thrown IS NULL
                OR strikes_thrown IS NULL
                OR strikes_thrown <= pitches_thrown
            )
        ),

    CONSTRAINT chk_player_game_pitching_decision
        CHECK (
            decision IS NULL
            OR decision IN (
                'W',
                'L',
                'S',
                'H',
                'BS'
            )
        )
);


CREATE INDEX idx_team_game_statistics_team_game
ON team_game_statistics (
    team_id,
    game_id
);

CREATE INDEX idx_team_game_statistics_game_id
ON team_game_statistics (
    game_id
);

CREATE INDEX idx_player_game_pitching_player_game
ON player_game_pitching_statistics (
    baseball_player_id,
    game_id
);

CREATE INDEX idx_player_game_pitching_team_game
ON player_game_pitching_statistics (
    team_id,
    game_id
);

CREATE INDEX idx_player_game_pitching_starters
ON player_game_pitching_statistics (
    game_id,
    team_id
)
WHERE is_starter = TRUE;
