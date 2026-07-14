from datetime import datetime, timezone
from decimal import Decimal

from sportsmodel.models import (
    BetCandidate,
    BetOutcome,
    GameResult,
)
from sportsmodel.settlement.settlement import (
    settle_bet_candidates,
)


BET_TIME = datetime(
    2026,
    7,
    10,
    18,
    0,
    tzinfo=timezone.utc,
)


def make_candidate(
    *,
    market_type: str,
    selection_name: str,
    line_value: Decimal | None,
    price: int = -110,
    game_id: int = 1,
) -> BetCandidate:
    return BetCandidate(
        odds_market_snapshot_id=1,
        game_id=game_id,
        sportsbook_id=1,
        market_type=market_type,
        selection_name=selection_name,
        line_value=line_value,
        bet_snapshot_time=BET_TIME,
        price=price,
        consensus_probability=Decimal("0.55"),
        expected_value=Decimal("0.05"),
    )


def make_result(
    *,
    game_id: int = 1,
    home_score: int = 5,
    away_score: int = 3,
) -> GameResult:
    return GameResult(
        game_id=game_id,
        home_team="Home Team",
        away_team="Away Team",
        home_score=home_score,
        away_score=away_score,
    )


def test_settles_winning_home_moneyline():
    candidate = make_candidate(
        market_type="h2h",
        selection_name="Home Team",
        line_value=None,
        price=125,
    )

    settled = settle_bet_candidates(
        [candidate],
        [make_result()],
    )

    assert len(settled) == 1
    assert settled[0].outcome is BetOutcome.WIN
    assert settled[0].profit_units == Decimal("1.25")


def test_settles_losing_away_moneyline():
    candidate = make_candidate(
        market_type="h2h",
        selection_name="Away Team",
        line_value=None,
    )

    settled = settle_bet_candidates(
        [candidate],
        [make_result()],
    )

    assert settled[0].outcome is BetOutcome.LOSS
    assert settled[0].profit_units == Decimal("-1")


def test_settles_spread_win():
    candidate = make_candidate(
        market_type="spreads",
        selection_name="Away Team",
        line_value=Decimal("2.5"),
    )

    result = make_result(
        home_score=5,
        away_score=3,
    )

    settled = settle_bet_candidates(
        [candidate],
        [result],
    )

    assert settled[0].outcome is BetOutcome.WIN


def test_settles_spread_loss():
    candidate = make_candidate(
        market_type="spreads",
        selection_name="Away Team",
        line_value=Decimal("1.5"),
    )

    result = make_result(
        home_score=5,
        away_score=3,
    )

    settled = settle_bet_candidates(
        [candidate],
        [result],
    )

    assert settled[0].outcome is BetOutcome.LOSS


def test_settles_spread_push():
    candidate = make_candidate(
        market_type="spreads",
        selection_name="Away Team",
        line_value=Decimal("2"),
    )

    result = make_result(
        home_score=5,
        away_score=3,
    )

    settled = settle_bet_candidates(
        [candidate],
        [result],
    )

    assert settled[0].outcome is BetOutcome.PUSH
    assert settled[0].profit_units == Decimal("0")


def test_settles_over_win():
    candidate = make_candidate(
        market_type="totals",
        selection_name="Over",
        line_value=Decimal("7.5"),
    )

    result = make_result(
        home_score=5,
        away_score=3,
    )

    settled = settle_bet_candidates(
        [candidate],
        [result],
    )

    assert settled[0].outcome is BetOutcome.WIN


def test_settles_under_win():
    candidate = make_candidate(
        market_type="totals",
        selection_name="Under",
        line_value=Decimal("8.5"),
    )

    result = make_result(
        home_score=5,
        away_score=3,
    )

    settled = settle_bet_candidates(
        [candidate],
        [result],
    )

    assert settled[0].outcome is BetOutcome.WIN


def test_settles_total_push():
    candidate = make_candidate(
        market_type="totals",
        selection_name="Over",
        line_value=Decimal("8"),
    )

    result = make_result(
        home_score=5,
        away_score=3,
    )

    settled = settle_bet_candidates(
        [candidate],
        [result],
    )

    assert settled[0].outcome is BetOutcome.PUSH


def test_negative_american_odds_win_profit():
    candidate = make_candidate(
        market_type="h2h",
        selection_name="Home Team",
        line_value=None,
        price=-200,
    )

    settled = settle_bet_candidates(
        [candidate],
        [make_result()],
    )

    assert settled[0].profit_units == Decimal("0.5")


def test_candidate_without_result_is_omitted():
    candidate = make_candidate(
        market_type="h2h",
        selection_name="Home Team",
        line_value=None,
        game_id=99,
    )

    settled = settle_bet_candidates(
        [candidate],
        [make_result(game_id=1)],
    )

    assert settled == []


def test_unknown_team_selection_is_omitted():
    candidate = make_candidate(
        market_type="h2h",
        selection_name="Unknown Team",
        line_value=None,
    )

    settled = settle_bet_candidates(
        [candidate],
        [make_result()],
    )

    assert settled == []


def test_unsupported_market_is_omitted():
    candidate = make_candidate(
        market_type="team_totals",
        selection_name="Home Team",
        line_value=Decimal("4.5"),
    )

    settled = settle_bet_candidates(
        [candidate],
        [make_result()],
    )

    assert settled == []


def test_empty_input_returns_empty_list():
    assert settle_bet_candidates([], []) == []
