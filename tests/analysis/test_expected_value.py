from datetime import datetime, timezone
from decimal import Decimal

from sportsmodel.analysis.expected_value import (
    calculate_expected_value_markets,
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
    sportsbook_id: int,
    selection_name: str,
    probability: str,
    price: int,
):
    probability = Decimal(probability)

    return NoVigSelection(
        odds_market_snapshot_id=snapshot_id,
        selection_name=selection_name,
        line_value=None,
        price=price,
        implied_probability=probability,
        no_vig_probability=probability,
    )


def make_market(
    sportsbook_id: int,
    team_a_probability: str,
    team_b_probability: str,
    team_a_price: int,
    team_b_price: int,
):
    return NoVigMarket(
        game_id=1,
        sportsbook_id=sportsbook_id,
        market_type="h2h",
        line_value=None,
        snapshot_time=SNAPSHOT_TIME,
        selections=(
            make_selection(
                sportsbook_id * 2 - 1,
                sportsbook_id,
                "Team A",
                team_a_probability,
                team_a_price,
            ),
            make_selection(
                sportsbook_id * 2,
                sportsbook_id,
                "Team B",
                team_b_probability,
                team_b_price,
            ),
        ),
    )


def test_requires_three_sportsbooks():
    markets = [
        make_market(
            1,
            "0.60",
            "0.40",
            -150,
            130,
        ),
        make_market(
            2,
            "0.62",
            "0.38",
            -155,
            135,
        ),
    ]

    assert calculate_expected_value_markets(markets) == []


def test_generates_expected_value_markets():
    markets = [
        make_market(
            1,
            "0.60",
            "0.40",
            -150,
            130,
        ),
        make_market(
            2,
            "0.62",
            "0.38",
            -155,
            135,
        ),
        make_market(
            3,
            "0.64",
            "0.36",
            -160,
            140,
        ),
    ]

    result = calculate_expected_value_markets(markets)

    assert len(result) == 3


def test_leave_one_out_consensus():
    markets = [
        make_market(
            1,
            "0.50",
            "0.50",
            120,
            -120,
        ),
        make_market(
            2,
            "0.70",
            "0.30",
            -200,
            180,
        ),
        make_market(
            3,
            "0.60",
            "0.40",
            -140,
            125,
        ),
    ]

    result = calculate_expected_value_markets(markets)

    first_market = result[0]

    selections = {
        selection.selection_name: selection
        for selection in first_market.selections
    }

    assert selections["Team A"].consensus_probability == Decimal("0.65")
    assert selections["Team B"].consensus_probability == Decimal("0.35")


def test_expected_value_is_decimal():
    markets = [
        make_market(
            1,
            "0.60",
            "0.40",
            -150,
            130,
        ),
        make_market(
            2,
            "0.61",
            "0.39",
            -152,
            132,
        ),
        make_market(
            3,
            "0.62",
            "0.38",
            -154,
            134,
        ),
    ]

    result = calculate_expected_value_markets(markets)

    selection = result[0].selections[0]

    assert isinstance(selection.expected_value, Decimal)