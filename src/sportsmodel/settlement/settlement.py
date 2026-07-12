from collections.abc import Iterable
from decimal import Decimal

from sportsmodel.analysis.probability import (
    american_to_decimal_odds,
)
from sportsmodel.models import (
    BetCandidate,
    BetOutcome,
    GameResult,
    SettledBet,
)


def settle_bet_candidates(
    candidates: Iterable[BetCandidate],
    results: Iterable[GameResult],
) -> list[SettledBet]:
    """
    Settle strategy candidates against final game scores.

    Candidates without a matching final result are omitted.
    """

    results_by_game = {
        result.game_id: result
        for result in results
    }

    settled_bets: list[SettledBet] = []

    for candidate in candidates:
        result = results_by_game.get(candidate.game_id)

        if result is None:
            continue

        outcome = _determine_outcome(
            candidate,
            result,
        )

        if outcome is None:
            continue

        settled_bets.append(
            SettledBet(
                odds_market_snapshot_id=(
                    candidate.odds_market_snapshot_id
                ),
                game_id=candidate.game_id,
                sportsbook_id=candidate.sportsbook_id,
                market_type=candidate.market_type,
                selection_name=candidate.selection_name,
                line_value=candidate.line_value,
                bet_snapshot_time=(
                    candidate.bet_snapshot_time
                ),
                price=candidate.price,
                consensus_probability=(
                    candidate.consensus_probability
                ),
                expected_value=candidate.expected_value,
                outcome=outcome,
                profit_units=_calculate_profit(
                    candidate.price,
                    outcome,
                ),
            )
        )

    settled_bets.sort(
        key=lambda bet: (
            bet.bet_snapshot_time,
            bet.game_id,
            bet.sportsbook_id,
            bet.market_type,
            bet.selection_name,
        )
    )

    return settled_bets


def _determine_outcome(
    candidate: BetCandidate,
    result: GameResult,
) -> BetOutcome | None:
    if candidate.market_type == "h2h":
        return _settle_moneyline(candidate, result)

    if candidate.market_type == "spreads":
        return _settle_spread(candidate, result)

    if candidate.market_type == "totals":
        return _settle_total(candidate, result)

    return None


def _settle_moneyline(
    candidate: BetCandidate,
    result: GameResult,
) -> BetOutcome | None:
    selected_score, opponent_score = _team_scores(
        candidate.selection_name,
        result,
    )

    if selected_score is None or opponent_score is None:
        return None

    if selected_score > opponent_score:
        return BetOutcome.WIN

    if selected_score < opponent_score:
        return BetOutcome.LOSS

    return BetOutcome.PUSH


def _settle_spread(
    candidate: BetCandidate,
    result: GameResult,
) -> BetOutcome | None:
    if candidate.line_value is None:
        return None

    selected_score, opponent_score = _team_scores(
        candidate.selection_name,
        result,
    )

    if selected_score is None or opponent_score is None:
        return None

    adjusted_score = (
        Decimal(selected_score)
        + candidate.line_value
    )
    opponent = Decimal(opponent_score)

    if adjusted_score > opponent:
        return BetOutcome.WIN

    if adjusted_score < opponent:
        return BetOutcome.LOSS

    return BetOutcome.PUSH


def _settle_total(
    candidate: BetCandidate,
    result: GameResult,
) -> BetOutcome | None:
    if candidate.line_value is None:
        return None

    total_score = Decimal(
        result.home_score + result.away_score
    )

    if candidate.selection_name == "Over":
        if total_score > candidate.line_value:
            return BetOutcome.WIN
        if total_score < candidate.line_value:
            return BetOutcome.LOSS
        return BetOutcome.PUSH

    if candidate.selection_name == "Under":
        if total_score < candidate.line_value:
            return BetOutcome.WIN
        if total_score > candidate.line_value:
            return BetOutcome.LOSS
        return BetOutcome.PUSH

    return None


def _team_scores(
    selection_name: str,
    result: GameResult,
) -> tuple[int | None, int | None]:
    if selection_name == result.home_team:
        return result.home_score, result.away_score

    if selection_name == result.away_team:
        return result.away_score, result.home_score

    return None, None


def _calculate_profit(
    price: int,
    outcome: BetOutcome,
) -> Decimal:
    if outcome is BetOutcome.LOSS:
        return Decimal("-1")

    if outcome is BetOutcome.PUSH:
        return Decimal("0")

    return american_to_decimal_odds(price) - Decimal("1")
