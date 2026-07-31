from collections.abc import Callable
from decimal import Decimal
from typing import Any

from sportsmodel.database.connection import (
    get_connection,
)
from sportsmodel.models.moneyline_live_dashboard import (
    MoneylineLiveGame,
    MoneylineLivePerformance,
    MoneylineLiveSlate,
)


ConnectionFactory = Callable[[], Any]


LIST_MONEYLINE_LIVE_SLATES_QUERY = """
    SELECT DISTINCT
        prediction_run.moneyline_prediction_run_id,
        evaluation.odds_ingestion_run_id,
        evaluation.policy_version,
        prediction_run.target_date
    FROM moneyline_prediction_market_evaluations
        AS evaluation
    JOIN moneyline_game_predictions AS prediction
      ON prediction.moneyline_game_prediction_id =
         evaluation.moneyline_game_prediction_id
    JOIN moneyline_prediction_runs AS prediction_run
      ON prediction_run.moneyline_prediction_run_id =
         prediction.moneyline_prediction_run_id
    ORDER BY
        prediction_run.target_date DESC,
        prediction_run.moneyline_prediction_run_id DESC,
        evaluation.odds_ingestion_run_id DESC,
        evaluation.policy_version DESC;
"""


GET_MONEYLINE_LIVE_GAMES_QUERY = """
    SELECT
        prediction.game_id,
        prediction.game_start_time,
        away_team.team_name,
        home_team.team_name,
        predicted_team.team_name,
        prediction.predicted_probability,
        prediction.starter_coverage,
        prediction.missing_raw_value_count,
        evaluation.market_no_vig_probability,
        evaluation.model_market_edge,
        evaluation.price,
        sportsbook.name,
        evaluation.model_expected_value,
        evaluation.qualifies_as_paper_candidate,
        evaluation.disqualification_reasons,
        settlement.outcome,
        settlement.profit_units,
        settlement.home_score,
        settlement.away_score
    FROM moneyline_game_predictions AS prediction
    JOIN moneyline_prediction_market_evaluations
        AS evaluation
      ON evaluation.moneyline_game_prediction_id =
         prediction.moneyline_game_prediction_id
    JOIN teams AS away_team
      ON away_team.team_id =
         prediction.away_team_id
    JOIN teams AS home_team
      ON home_team.team_id =
         prediction.home_team_id
    JOIN teams AS predicted_team
      ON predicted_team.team_id =
         prediction.predicted_team_id
    JOIN sportsbooks AS sportsbook
      ON sportsbook.sportsbook_id =
         evaluation.sportsbook_id
    LEFT JOIN moneyline_paper_candidate_settlements
        AS settlement
      ON settlement
         .moneyline_prediction_market_evaluation_id =
         evaluation
         .moneyline_prediction_market_evaluation_id
    WHERE
        prediction.moneyline_prediction_run_id = %s
        AND evaluation.odds_ingestion_run_id = %s
        AND evaluation.policy_version = %s
    ORDER BY
        prediction.game_start_time,
        prediction.game_id;
"""


def list_moneyline_live_slates(
    *,
    connection_factory: ConnectionFactory = get_connection,
) -> tuple[MoneylineLiveSlate, ...]:
    """
    Return available live Moneyline slates, newest first.
    """

    connection = connection_factory()

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                LIST_MONEYLINE_LIVE_SLATES_QUERY
            )
            rows = cursor.fetchall()

        return tuple(
            MoneylineLiveSlate(
                prediction_run_id=row[0],
                odds_ingestion_run_id=row[1],
                policy_version=row[2],
                target_date=row[3],
            )
            for row in rows
        )

    finally:
        connection.close()


def get_moneyline_live_games(
    *,
    prediction_run_id: int,
    odds_ingestion_run_id: int,
    policy_version: str,
    connection_factory: ConnectionFactory = get_connection,
) -> tuple[MoneylineLiveGame, ...]:
    """
    Return dashboard rows for one persisted Moneyline slate.
    """

    _validate_positive_identifier(
        value=prediction_run_id,
        field_name="Prediction run ID",
    )

    _validate_positive_identifier(
        value=odds_ingestion_run_id,
        field_name="Odds ingestion run ID",
    )

    normalized_policy_version = policy_version.strip()

    if not normalized_policy_version:
        raise ValueError(
            "Policy version cannot be blank."
        )

    connection = connection_factory()

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                GET_MONEYLINE_LIVE_GAMES_QUERY,
                (
                    prediction_run_id,
                    odds_ingestion_run_id,
                    normalized_policy_version,
                ),
            )

            rows = cursor.fetchall()

        return tuple(
            MoneylineLiveGame(
                game_id=row[0],
                game_start_time=row[1],
                away_team_name=row[2],
                home_team_name=row[3],
                predicted_team_name=row[4],
                model_probability=row[5],
                starter_coverage=row[6],
                missing_raw_value_count=row[7],
                market_no_vig_probability=row[8],
                model_market_edge=row[9],
                price=row[10],
                sportsbook_name=row[11],
                model_expected_value=row[12],
                qualifies_as_paper_candidate=row[13],
                disqualification_reasons=tuple(
                    row[14] or ()
                ),
                outcome=row[15],
                profit_units=row[16],
                home_score=row[17],
                away_score=row[18],
            )
            for row in rows
        )

    finally:
        connection.close()


def build_moneyline_live_performance(
    games: tuple[MoneylineLiveGame, ...],
) -> MoneylineLivePerformance:
    """
    Calculate forward performance from settled dashboard rows.
    """

    settled_games = sorted(
        (
            game
            for game in games
            if (
                game.outcome is not None
                and game.profit_units is not None
            )
        ),
        key=lambda game: (
            game.game_start_time,
            game.game_id,
        ),
    )

    settlements = len(settled_games)

    wins = sum(
        game.outcome == "win"
        for game in settled_games
    )

    losses = sum(
        game.outcome == "loss"
        for game in settled_games
    )

    pushes = sum(
        game.outcome == "push"
        for game in settled_games
    )

    decisions = wins + losses

    units_staked = Decimal(settlements)

    profit_units = sum(
        (
            game.profit_units
            for game in settled_games
            if game.profit_units is not None
        ),
        start=Decimal("0"),
    )

    if decisions:
        win_rate = (
            Decimal(wins)
            / Decimal(decisions)
        )
    else:
        win_rate = Decimal("0")

    if units_staked:
        roi = profit_units / units_staked
    else:
        roi = Decimal("0")

    if settlements:
        average_model_expected_value = (
            sum(
                (
                    game.model_expected_value
                    for game in settled_games
                ),
                start=Decimal("0"),
            )
            / Decimal(settlements)
        )
    else:
        average_model_expected_value = (
            Decimal("0")
        )

    maximum_drawdown_units = (
        _calculate_maximum_drawdown(
            settled_games
        )
    )

    return MoneylineLivePerformance(
        settlements=settlements,
        wins=wins,
        losses=losses,
        pushes=pushes,
        win_rate=win_rate,
        units_staked=units_staked,
        profit_units=profit_units,
        roi=roi,
        average_model_expected_value=(
            average_model_expected_value
        ),
        maximum_drawdown_units=(
            maximum_drawdown_units
        ),
    )


def _calculate_maximum_drawdown(
    games: list[MoneylineLiveGame],
) -> Decimal:
    cumulative_profit = Decimal("0")
    peak_profit = Decimal("0")
    maximum_drawdown = Decimal("0")

    for game in games:
        if game.profit_units is None:
            continue

        cumulative_profit += game.profit_units

        if cumulative_profit > peak_profit:
            peak_profit = cumulative_profit

        drawdown = peak_profit - cumulative_profit

        if drawdown > maximum_drawdown:
            maximum_drawdown = drawdown

    return maximum_drawdown


def _validate_positive_identifier(
    *,
    value: int,
    field_name: str,
) -> None:
    if value <= 0:
        raise ValueError(
            f"{field_name} must be greater than zero."
        )
