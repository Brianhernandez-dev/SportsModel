ALTER TABLE moneyline_prediction_market_evaluations
    ADD COLUMN starter_match_status VARCHAR(16),
    ADD COLUMN starter_mismatch_reason VARCHAR(40),
    ADD COLUMN current_home_starting_pitcher_mlb_id BIGINT,
    ADD COLUMN current_away_starting_pitcher_mlb_id BIGINT;

ALTER TABLE moneyline_prediction_market_evaluations
    ADD CONSTRAINT chk_moneyline_evaluation_starter_match_status
        CHECK (
            starter_match_status IS NULL
            OR starter_match_status IN (
                'matched',
                'changed',
                'unavailable'
            )
        ),
    ADD CONSTRAINT chk_moneyline_evaluation_starter_match_reason
        CHECK (
            (starter_match_status IS NULL AND starter_mismatch_reason IS NULL)
            OR (starter_match_status = 'matched' AND starter_mismatch_reason IS NULL)
            OR (
                starter_match_status = 'changed'
                AND starter_mismatch_reason IN (
                    'starter_changed_home',
                    'starter_changed_away',
                    'starter_changed_both'
                )
            )
            OR (
                starter_match_status = 'unavailable'
                AND starter_mismatch_reason IN (
                    'starter_unavailable_home',
                    'starter_unavailable_away',
                    'starter_unavailable_both'
                )
            )
        ),
    ADD CONSTRAINT chk_moneyline_evaluation_starter_qualification
        CHECK (
            (
                qualifies_as_paper_candidate = FALSE
                OR starter_match_status = 'matched'
            ) IS TRUE
        ) NOT VALID;

-- Historical evaluations remain nullable evidence. New application writes
-- always populate these fields; no historical qualification is rewritten.
