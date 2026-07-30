from datetime import datetime, timezone
from decimal import Decimal

import pytest

from sportsmodel.analysis.probability import (
    american_to_decimal_odds,
)
from sportsmodel.models.game_result import (
    GameResult,
)
from sportsmodel.models.moneyline_paper_settlement import (
    MoneylinePaperCandidate,
)
from sportsmodel.models.settled_bet import (
    BetOutcome,
)
from sportsmodel.settlement.moneyline_paper import (
    settle_moneyline_paper_candidates,
)


SNAPSHOT_TIME = datetime(
    2026,
    7,
    30,
    3,
    2,
    48,
    tzinfo=timezone.utc,
)


def test_settles_positive_odds_win() -> None:
    settlements = (
        settle_moneyline_paper_candidates(
            [
                _candidate(
                    selection_name="Away Team",
                    price=119,
                )
            ],
            [
                _result(
                    home_score=3,
                    away_score=5,
                )
            ],
        )
    )

    assert len(settlements) == 1
    assert (
        settlements[0].outcome
        is BetOutcome.WIN
    )
    assert (
        settlements[0].profit_units
        == Decimal("1.19")
    )


def test_settles_negative_odds_win() -> None:
    settlements = (
        settle_moneyline_paper_candidates(
            [
                _candidate(
                    selection_name="Home Team",
                    price=-130,
                )
            ],
            [
                _result(
                    home_score=6,
                    away_score=2,
                )
            ],
        )
    )

    assert (
        settlements[0].outcome
        is BetOutcome.WIN
    )

    assert (
        settlements[0].profit_units
        == (
            american_to_decimal_odds(-130)
            - Decimal("1")
        )
    )


def test_settles_loss_as_negative_one_unit() -> None:
    settlements = (
        settle_moneyline_paper_candidates(
            [
                _candidate(
                    selection_name="Away Team",
                    price=105,
                )
            ],
            [
                _result(
                    home_score=4,
                    away_score=1,
                )
            ],
        )
    )

    assert (
        settlements[0].outcome
        is BetOutcome.LOSS
    )
    assert (
        settlements[0].profit_units
        == Decimal("-1")
    )


def test_settles_tie_as_push() -> None:
    settlements = (
        settle_moneyline_paper_candidates(
            [
                _candidate(
                    selection_name="Home Team",
                    price=-110,
                )
            ],
            [
                _result(
                    home_score=3,
                    away_score=3,
                )
            ],
        )
    )

    assert (
        settlements[0].outcome
        is BetOutcome.PUSH
    )
    assert (
        settlements[0].profit_units
        == Decimal("0")
    )


def test_candidate_without_result_is_omitted() -> None:
    settlements = (
        settle_moneyline_paper_candidates(
            [
                _candidate(
                    selection_name="Home Team",
                    price=-110,
                    game_id=99,
                )
            ],
            [
                _result(game_id=1)
            ],
        )
    )

    assert settlements == []


def test_rejects_unknown_team_selection() -> None:
    with pytest.raises(
        ValueError,
        match="does not match",
    ):
        settle_moneyline_paper_candidates(
            [
                _candidate(
                    selection_name="Unknown Team",
                    price=-110,
                )
            ],
            [
                _result()
            ],
        )


def test_rejects_naive_snapshot_time() -> None:
    with pytest.raises(
        ValueError,
        match="timezone-aware",
    ):
        MoneylinePaperCandidate(
            moneyline_prediction_market_evaluation_id=1,
            game_id=1,
            selection_name="Home Team",
            snapshot_time=SNAPSHOT_TIME.replace(
                tzinfo=None
            ),
            price=-110,
            model_probability=Decimal("0.55"),
            model_expected_value=Decimal("0.04"),
        )


def _candidate(
    *,
    selection_name: str,
    price: int,
    game_id: int = 1,
) -> MoneylinePaperCandidate:
    return MoneylinePaperCandidate(
        moneyline_prediction_market_evaluation_id=71,
        game_id=game_id,
        selection_name=selection_name,
        snapshot_time=SNAPSHOT_TIME,
        price=price,
        model_probability=Decimal("0.55"),
        model_expected_value=Decimal("0.04"),
    )


def _result(
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
