from collections.abc import Iterable
from decimal import Decimal

from sportsmodel.models import (
    BetCandidate,
    ExpectedValueMarket,
)


def select_positive_ev_candidates(
    markets: Iterable[ExpectedValueMarket],
    minimum_expected_value: Decimal = Decimal("0.02"),
) -> list[BetCandidate]:
    """
    Select sportsbook opportunities meeting an EV threshold.

    The strategy only uses information available at the market snapshot.
    Closing prices and game results are intentionally unavailable here.
    """

    if minimum_expected_value < Decimal("-1"):
        raise ValueError(
            "Minimum expected value cannot be less than -1."
        )

    candidates: list[BetCandidate] = []

    for market in markets:
        for selection in market.selections:
            if selection.expected_value < minimum_expected_value:
                continue

            candidates.append(
                BetCandidate(
                    odds_market_snapshot_id=(
                        selection.odds_market_snapshot_id
                    ),
                    game_id=market.game_id,
                    sportsbook_id=market.sportsbook_id,
                    market_type=market.market_type,
                    selection_name=selection.selection_name,
                    line_value=selection.line_value,
                    bet_snapshot_time=market.snapshot_time,
                    price=selection.price,
                    consensus_probability=(
                        selection.consensus_probability
                    ),
                    expected_value=selection.expected_value,
                )
            )

    candidates.sort(
        key=lambda candidate: (
            candidate.bet_snapshot_time,
            candidate.game_id,
            candidate.sportsbook_id,
            candidate.market_type,
            candidate.selection_name,
        )
    )

    return candidates
