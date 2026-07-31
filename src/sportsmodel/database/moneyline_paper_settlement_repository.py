from typing import Any

from sportsmodel.models.moneyline_paper_settlement import (
    MoneylinePaperSettlement,
)


def upsert_moneyline_paper_settlement(
    cursor: Any,
    settlement: MoneylinePaperSettlement,
) -> int:
    """
    Insert or refresh one Moneyline paper-candidate settlement.

    The market evaluation uniquely identifies the paper candidate.
    Re-running settlement updates the final score and calculated result
    rather than creating a duplicate record.
    """

    _validate_settlement(settlement)

    cursor.execute(
        """
        INSERT INTO
            moneyline_paper_candidate_settlements (
                moneyline_prediction_market_evaluation_id,
                game_id,
                home_score,
                away_score,
                outcome,
                profit_units
            )
        VALUES (
            %s,
            %s,
            %s,
            %s,
            %s,
            %s
        )
        ON CONFLICT (
            moneyline_prediction_market_evaluation_id
        )
        DO UPDATE SET
            game_id =
                EXCLUDED.game_id,
            home_score =
                EXCLUDED.home_score,
            away_score =
                EXCLUDED.away_score,
            outcome =
                EXCLUDED.outcome,
            profit_units =
                EXCLUDED.profit_units,
            settled_at =
                CURRENT_TIMESTAMP
        RETURNING
            moneyline_paper_candidate_settlement_id;
        """,
        (
            settlement
            .moneyline_prediction_market_evaluation_id,
            settlement.game_id,
            settlement.home_score,
            settlement.away_score,
            settlement.outcome.value,
            settlement.profit_units,
        ),
    )

    row = cursor.fetchone()

    if row is None:
        raise RuntimeError(
            "Moneyline paper settlement upsert "
            "returned no row."
        )

    return row[0]


def _validate_settlement(
    settlement: MoneylinePaperSettlement,
) -> None:
    if (
        settlement
        .moneyline_prediction_market_evaluation_id
        <= 0
    ):
        raise ValueError(
            "Moneyline market evaluation ID must "
            "be greater than zero."
        )

    if settlement.game_id <= 0:
        raise ValueError(
            "Game ID must be greater than zero."
        )

    if settlement.home_score < 0:
        raise ValueError(
            "Home score cannot be negative."
        )

    if settlement.away_score < 0:
        raise ValueError(
            "Away score cannot be negative."
        )
