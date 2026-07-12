from datetime import datetime, timezone
from decimal import Decimal

from sportsmodel.analysis.consensus import (
    build_consensus_markets,
)
from sportsmodel.models import (
    NoVigMarket,
    NoVigSelection,
)


SNAPSHOT_TIME = datetime(
    2026,
    7,
    12,
    18,
    0,
    tzinfo=timezone.utc,
)


def make_selection(
    snapshot_id: int,
    selection_name: str,
    line_value: Decimal | None,
    probability: str,
) -> NoVigSelection:
    no_vig_probability = Decimal(probability)

    return NoVigSelection(
        odds_market_snapshot_id=snapshot_id,
        selection_name=selection_name,
        line_value=line_value,
        price=-110,
        implied_probability=no_vig_probability,
        no_vig_probability=no_vig_probability,
    )


def make_market(
    sportsbook_id: int,
    market_type: str,
    line_value: Decimal | None,
    selections: tuple[NoVigSelection, ...],
) -> NoVigMarket:
    return NoVigMarket(
        game_id=10,
        sportsbook_id=sportsbook_id,
        market_type=market_type,
        line_value=line_value,
        snapshot_time=SNAPSHOT_TIME,
        selections=selections,
    )


def test_averages_probabilities_across_sportsbooks():
    markets = [
        make_market(
            sportsbook_id=1,
            market_type="h2h",
            line_value=None,
            selections=(
                make_selection(1, "Team A", None, "0.60"),
                make_selection(2, "Team B", None, "0.40"),
            ),
        ),
        make_market(
            sportsbook_id=2,
            market_type="h2h",
            line_value=None,
            selections=(
                make_selection(3, "Team A", None, "0.64"),
                make_selection(4, "Team B", None, "0.36"),
            ),
        ),
    ]

    result = build_consensus_markets(markets)

    assert len(result) == 1

    selections = {
        selection.selection_name: selection
        for selection in result[0].selections
    }

    assert selections["Team A"].consensus_probability == Decimal("0.62")
    assert selections["Team B"].consensus_probability == Decimal("0.38")
    assert selections["Team A"].sportsbook_count == 2
    assert selections["Team B"].sportsbook_count == 2


def test_preserves_signed_spread_selection_lines():
    markets = [
        make_market(
            sportsbook_id=1,
            market_type="spreads",
            line_value=Decimal("-1.5"),
            selections=(
                make_selection(
                    1,
                    "Team A",
                    Decimal("-1.5"),
                    "0.55",
                ),
                make_selection(
                    2,
                    "Team B",
                    Decimal("1.5"),
                    "0.45",
                ),
            ),
        ),
        make_market(
            sportsbook_id=2,
            market_type="spreads",
            line_value=Decimal("-1.5"),
            selections=(
                make_selection(
                    3,
                    "Team A",
                    Decimal("-1.5"),
                    "0.57",
                ),
                make_selection(
                    4,
                    "Team B",
                    Decimal("1.5"),
                    "0.43",
                ),
            ),
        ),
    ]

    result = build_consensus_markets(markets)

    assert len(result) == 1
    assert result[0].line_value == Decimal("1.5")

    selections = {
        selection.selection_name: selection
        for selection in result[0].selections
    }

    assert selections["Team A"].line_value == Decimal("-1.5")
    assert selections["Team B"].line_value == Decimal("1.5")
    assert selections["Team A"].consensus_probability == Decimal("0.56")
    assert selections["Team B"].consensus_probability == Decimal("0.44")


def test_excludes_single_sportsbook_market():
    markets = [
        make_market(
            sportsbook_id=1,
            market_type="totals",
            line_value=Decimal("8.5"),
            selections=(
                make_selection(
                    1,
                    "Over",
                    Decimal("8.5"),
                    "0.51",
                ),
                make_selection(
                    2,
                    "Under",
                    Decimal("8.5"),
                    "0.49",
                ),
            ),
        )
    ]

    assert build_consensus_markets(markets) == []


def test_excludes_inconsistent_sportsbook_group():
    markets = [
        make_market(
            sportsbook_id=1,
            market_type="h2h",
            line_value=None,
            selections=(
                make_selection(1, "Team A", None, "0.60"),
                make_selection(2, "Team B", None, "0.40"),
            ),
        ),
        make_market(
            sportsbook_id=2,
            market_type="h2h",
            line_value=None,
            selections=(
                make_selection(3, "Team A", None, "0.65"),
                make_selection(4, "Wrong Team", None, "0.35"),
            ),
        ),
    ]

    assert build_consensus_markets(markets) == []