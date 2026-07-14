from collections.abc import Iterable
from datetime import datetime
from decimal import Decimal

from sportsmodel.models import (
    BetCandidate,
    ExpectedValueMarket,
)


CandidateKey = tuple[
    int,
    int,
    str,
    str,
    Decimal | None,
]


def select_positive_ev_candidates(
    markets: Iterable[ExpectedValueMarket],
    minimum_expected_value: Decimal = Decimal("0.02"),
) -> list[BetCandidate]:
    """
    Select the first qualifying positive-EV wager per contract.

    A unique wager contract is identified by:
    - game
    - sportsbook
    - market type
    - selection
    - line value

    The earliest qualifying snapshot is retained. This prevents repeated
    polling from producing duplicate historical wagers and avoids using
    later information to select a more favorable entry.
    """

    if minimum_expected_value < Decimal("-1"):
        raise ValueError(
            "Minimum expected value cannot be less than -1."
        )

    ordered_markets = sorted(
        markets,
        key=lambda market: (
            market.snapshot_time,
            market.game_id,
            market.sportsbook_id,
            market.market_type,
            (
                str(market.line_value)
                if market.line_value is not None
                else ""
            ),
        ),
    )

    first_candidate_by_contract: dict[
        CandidateKey,
        BetCandidate,
    ] = {}

    for market in ordered_markets:
        for selection in market.selections:
            if selection.expected_value < minimum_expected_value:
                continue

            key = (
                market.game_id,
                market.sportsbook_id,
                market.market_type,
                selection.selection_name,
                selection.line_value,
            )

            if key in first_candidate_by_contract:
                continue

            first_candidate_by_contract[key] = BetCandidate(
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

    candidates = list(
        first_candidate_by_contract.values()
    )

    candidates.sort(
        key=lambda candidate: (
            candidate.bet_snapshot_time,
            candidate.game_id,
            candidate.sportsbook_id,
            candidate.market_type,
            candidate.selection_name,
            (
                str(candidate.line_value)
                if candidate.line_value is not None
                else ""
            ),
        )
    )

    return candidates