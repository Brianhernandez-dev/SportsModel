from datetime import datetime, timezone
from decimal import Decimal

import pytest

from sportsmodel.models import (
    ExpectedValueMarket,
    ExpectedValueSelection,
)
from sportsmodel.strategies.positive_ev import (
    select_positive_ev_candidates,
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
    *,
    snapshot_id: int,
    selection_name: str,
    expected_value: str,
    price: int = -110,
) -> ExpectedValueSelection:
    return ExpectedValueSelection(
        odds_market_snapshot_id=snapshot_id,
        selection_name=selection_name,
        line_value=None,
        sportsbook_id=1,
        price=price,
        consensus_probability=Decimal("0.55"),
        expected_value=Decimal(expected_value),
    )


def make_market(
    selections: tuple[ExpectedValueSelection, ...],
) -> ExpectedValueMarket:
    return ExpectedValueMarket(
        game_id=10,
        sportsbook_id=1,
        market_type="h2h",
        line_value=None,
        snapshot_time=SNAPSHOT_TIME,
        selections=selections,
    )


def test_selects_opportunities_at_or_above_threshold():
    market = make_market(
        (
            make_selection(
                snapshot_id=1,
                selection_name="Team A",
                expected_value="0.02",
            ),
            make_selection(
                snapshot_id=2,
                selection_name="Team B",
                expected_value="0.05",
            ),
        )
    )

    result = select_positive_ev_candidates(
        [market],
        minimum_expected_value=Decimal("0.02"),
    )

    assert len(result) == 2


def test_excludes_opportunities_below_threshold():
    market = make_market(
        (
            make_selection(
                snapshot_id=1,
                selection_name="Team A",
                expected_value="0.0199",
            ),
            make_selection(
                snapshot_id=2,
                selection_name="Team B",
                expected_value="0.03",
            ),
        )
    )

    result = select_positive_ev_candidates(
        [market],
        minimum_expected_value=Decimal("0.02"),
    )

    assert len(result) == 1
    assert result[0].selection_name == "Team B"


def test_candidate_preserves_market_information():
    market = make_market(
        (
            make_selection(
                snapshot_id=41,
                selection_name="Team A",
                expected_value="0.04",
                price=125,
            ),
        )
    )

    result = select_positive_ev_candidates([market])

    candidate = result[0]

    assert candidate.odds_market_snapshot_id == 41
    assert candidate.game_id == 10
    assert candidate.sportsbook_id == 1
    assert candidate.market_type == "h2h"
    assert candidate.selection_name == "Team A"
    assert candidate.bet_snapshot_time == SNAPSHOT_TIME
    assert candidate.price == 125
    assert candidate.expected_value == Decimal("0.04")


def test_default_threshold_is_two_percent():
    market = make_market(
        (
            make_selection(
                snapshot_id=1,
                selection_name="Team A",
                expected_value="0.019",
            ),
            make_selection(
                snapshot_id=2,
                selection_name="Team B",
                expected_value="0.021",
            ),
        )
    )

    result = select_positive_ev_candidates([market])

    assert len(result) == 1
    assert result[0].selection_name == "Team B"


def test_empty_input_returns_empty_list():
    assert select_positive_ev_candidates([]) == []


def test_rejects_impossible_threshold():
    with pytest.raises(
        ValueError,
        match="cannot be less than -1",
    ):
        select_positive_ev_candidates(
            [],
            minimum_expected_value=Decimal("-1.01"),
        )
