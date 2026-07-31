from collections.abc import Iterable
from decimal import Decimal

from sportsmodel.analysis.probability import (
    american_to_decimal_odds,
)
from sportsmodel.models.game_result import (
    GameResult,
)
from sportsmodel.models.moneyline_paper_settlement import (
    MoneylinePaperCandidate,
    MoneylinePaperSettlement,
)
from sportsmodel.models.settled_bet import (
    BetOutcome,
)


def settle_moneyline_paper_candidates(
    candidates: Iterable[MoneylinePaperCandidate],
    results: Iterable[GameResult],
) -> list[MoneylinePaperSettlement]:
    """
    Settle qualified forward Moneyline paper candidates.

    Candidates without a matching completed result are omitted so the
    service can be rerun safely while games remain unfinished.
    """

    results_by_game = {
        result.game_id: result
        for result in results
    }

    settlements: list[
        MoneylinePaperSettlement
    ] = []

    for candidate in candidates:
        result = results_by_game.get(
            candidate.game_id
        )

        if result is None:
            continue

        outcome = _determine_moneyline_outcome(
            selection_name=(
                candidate.selection_name
            ),
            result=result,
        )

        settlements.append(
            MoneylinePaperSettlement(
                moneyline_prediction_market_evaluation_id=(
                    candidate
                    .moneyline_prediction_market_evaluation_id
                ),
                game_id=candidate.game_id,
                selection_name=(
                    candidate.selection_name
                ),
                snapshot_time=(
                    candidate.snapshot_time
                ),
                price=candidate.price,
                model_probability=(
                    candidate.model_probability
                ),
                model_expected_value=(
                    candidate.model_expected_value
                ),
                home_team_name=(
                    result.home_team
                ),
                away_team_name=(
                    result.away_team
                ),
                home_score=result.home_score,
                away_score=result.away_score,
                outcome=outcome,
                profit_units=_calculate_profit_units(
                    price=candidate.price,
                    outcome=outcome,
                ),
            )
        )

    settlements.sort(
        key=lambda settlement: (
            settlement.snapshot_time,
            settlement.game_id,
            settlement
            .moneyline_prediction_market_evaluation_id,
        )
    )

    return settlements


def _determine_moneyline_outcome(
    *,
    selection_name: str,
    result: GameResult,
) -> BetOutcome:
    if selection_name == result.home_team:
        selected_score = result.home_score
        opponent_score = result.away_score

    elif selection_name == result.away_team:
        selected_score = result.away_score
        opponent_score = result.home_score

    else:
        raise ValueError(
            "Paper-candidate selection does not "
            "match either completed-game team."
        )

    if selected_score > opponent_score:
        return BetOutcome.WIN

    if selected_score < opponent_score:
        return BetOutcome.LOSS

    return BetOutcome.PUSH


def _calculate_profit_units(
    *,
    price: int,
    outcome: BetOutcome,
) -> Decimal:
    """
    Calculate flat one-unit profit.

    A loss returns -1 unit, a push returns zero, and a win returns the
    decimal-odds profit above the original one-unit stake.
    """

    if outcome is BetOutcome.LOSS:
        return Decimal("-1")

    if outcome is BetOutcome.PUSH:
        return Decimal("0")

    return (
        american_to_decimal_odds(price)
        - Decimal("1")
    )
