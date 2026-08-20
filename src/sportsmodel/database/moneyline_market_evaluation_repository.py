from typing import Any

from sportsmodel.models.moneyline_market_evaluation import (
    MoneylineModelMarketEvaluation,
)


def upsert_moneyline_market_evaluation(
    cursor: Any,
    *,
    moneyline_game_prediction_id: int,
    odds_ingestion_run_id: int,
    evaluation: MoneylineModelMarketEvaluation,
) -> int:
    """
    Insert or refresh one model-versus-market evaluation.

    The prediction, odds-ingestion run, and policy version identify one
    reproducible evaluation. Re-running the same evaluation refreshes its
    calculated values without creating a duplicate record.
    """

    _validate_positive_identifier(
        value=moneyline_game_prediction_id,
        field_name=(
            "Moneyline game prediction ID"
        ),
    )

    _validate_positive_identifier(
        value=odds_ingestion_run_id,
        field_name="Odds ingestion run ID",
    )

    cursor.execute(
        """
        INSERT INTO
            moneyline_prediction_market_evaluations (
                moneyline_game_prediction_id,
                odds_ingestion_run_id,
                odds_market_snapshot_id,
                sportsbook_id,
                snapshot_time,
                selection_name,
                price,
                model_probability,
                market_no_vig_probability,
                sportsbook_count,
                implied_probability,
                model_market_edge,
                model_price_edge,
                model_expected_value,
                starter_coverage,
                home_starter_features_available,
                away_starter_features_available,
                policy_version,
                qualifies_as_paper_candidate,
                disqualification_reasons,
                starter_match_status,
                starter_mismatch_reason,
                current_home_starting_pitcher_mlb_id,
                current_away_starting_pitcher_mlb_id
            )
        VALUES (
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s
        )
        ON CONFLICT (
            moneyline_game_prediction_id,
            odds_ingestion_run_id,
            policy_version
        )
        DO UPDATE SET
            odds_market_snapshot_id =
                EXCLUDED.odds_market_snapshot_id,
            sportsbook_id =
                EXCLUDED.sportsbook_id,
            snapshot_time =
                EXCLUDED.snapshot_time,
            selection_name =
                EXCLUDED.selection_name,
            price =
                EXCLUDED.price,
            model_probability =
                EXCLUDED.model_probability,
            market_no_vig_probability =
                EXCLUDED.market_no_vig_probability,
            sportsbook_count =
                EXCLUDED.sportsbook_count,
            implied_probability =
                EXCLUDED.implied_probability,
            model_market_edge =
                EXCLUDED.model_market_edge,
            model_price_edge =
                EXCLUDED.model_price_edge,
            model_expected_value =
                EXCLUDED.model_expected_value,
            starter_coverage =
                EXCLUDED.starter_coverage,
            home_starter_features_available =
                EXCLUDED.home_starter_features_available,
            away_starter_features_available =
                EXCLUDED.away_starter_features_available,
            qualifies_as_paper_candidate =
                EXCLUDED.qualifies_as_paper_candidate,
            disqualification_reasons =
                EXCLUDED.disqualification_reasons,
            starter_match_status =
                EXCLUDED.starter_match_status,
            starter_mismatch_reason =
                EXCLUDED.starter_mismatch_reason,
            current_home_starting_pitcher_mlb_id =
                EXCLUDED.current_home_starting_pitcher_mlb_id,
            current_away_starting_pitcher_mlb_id =
                EXCLUDED.current_away_starting_pitcher_mlb_id,
            evaluated_at =
                CURRENT_TIMESTAMP
        RETURNING
            moneyline_prediction_market_evaluation_id;
        """,
        (
            moneyline_game_prediction_id,
            odds_ingestion_run_id,
            evaluation.odds_market_snapshot_id,
            evaluation.sportsbook_id,
            evaluation.snapshot_time,
            evaluation.selection_name,
            evaluation.price,
            evaluation.model_probability,
            evaluation.market_no_vig_probability,
            evaluation.sportsbook_count,
            evaluation.implied_probability,
            evaluation.model_market_edge,
            evaluation.model_price_edge,
            evaluation.model_expected_value,
            evaluation.starter_coverage,
            evaluation.home_starter_features_available,
            evaluation.away_starter_features_available,
            evaluation.policy_version,
            evaluation.qualifies_as_paper_candidate,
            list(
                evaluation.disqualification_reasons
            ),
            evaluation.starter_match_status,
            evaluation.starter_mismatch_reason,
            evaluation.current_home_starting_pitcher_mlb_id,
            evaluation.current_away_starting_pitcher_mlb_id,
        ),
    )

    row = cursor.fetchone()

    if row is None:
        raise RuntimeError(
            "Moneyline market evaluation upsert "
            "returned no row."
        )

    return row[0]


def _validate_positive_identifier(
    *,
    value: int,
    field_name: str,
) -> None:
    if value <= 0:
        raise ValueError(
            f"{field_name} must be greater than zero."
        )
