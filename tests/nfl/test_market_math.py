from dataclasses import fields, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from sportsmodel.nfl.market_math import (
    BestOfferedPrice,
    CanonicalSelectionPrice,
    CompleteSportsbookMarket,
    MarketConsensus,
    american_to_decimal_odds,
    american_to_implied_probability,
    build_complete_sportsbook_market,
    calculate_market_consensus,
    calculate_model_market_evaluation,
    calculate_per_book_no_vig,
    find_best_offered_price,
)


OBSERVED_AT = datetime(2026, 9, 13, 16, tzinfo=timezone.utc)
NFL_SPORT = "americanfootball_nfl"


@pytest.mark.parametrize(
    ("price", "implied", "decimal_odds"),
    (
        (100, Decimal("0.5"), Decimal("2")),
        (120, Decimal(100) / Decimal(220), Decimal("2.2")),
        (-110, Decimal(110) / Decimal(210), Decimal(210) / Decimal(110)),
        (-200, Decimal(200) / Decimal(300), Decimal("1.5")),
    ),
)
def test_american_odds_conversions(
    price: int,
    implied: Decimal,
    decimal_odds: Decimal,
) -> None:
    assert american_to_implied_probability(price) == implied
    assert american_to_decimal_odds(price) == decimal_odds


@pytest.mark.parametrize(
    "conversion",
    (american_to_implied_probability, american_to_decimal_odds),
)
def test_american_odds_reject_zero(conversion) -> None:
    with pytest.raises(ValueError, match="cannot be zero"):
        conversion(0)


@pytest.mark.parametrize("invalid_price", (True, 110.5, Decimal("110")))
def test_american_odds_require_integer_prices(invalid_price) -> None:
    with pytest.raises(TypeError, match="integer"):
        american_to_implied_probability(invalid_price)


def test_american_odds_support_large_integer_prices() -> None:
    price = 10**18

    assert american_to_decimal_odds(price) == Decimal("10000000000000001")
    assert american_to_implied_probability(price) > Decimal("0")


def test_symmetric_market_removes_vig_evenly() -> None:
    market = _market(provider_identity_id=11, home_price=-110, away_price=-110)

    result = calculate_per_book_no_vig(market)

    probability_quantum = Decimal("0.0000000000000001")
    assert result.home.no_vig_probability.quantize(
        probability_quantum
    ) == Decimal("0.5000000000000000")
    assert result.away.no_vig_probability.quantize(
        probability_quantum
    ) == Decimal("0.5000000000000000")
    assert result.home.implied_probability == Decimal(110) / Decimal(210)
    assert result.overround == Decimal(220) / Decimal(210)


def test_asymmetric_market_uses_per_book_overround() -> None:
    market = _market(provider_identity_id=11, home_price=-135, away_price=115)
    home_raw = american_to_implied_probability(-135)
    away_raw = american_to_implied_probability(115)

    result = calculate_per_book_no_vig(market)

    assert result.home.no_vig_probability == home_raw / (home_raw + away_raw)
    assert result.away.no_vig_probability == (
        Decimal("1") - result.home.no_vig_probability
    )
    assert abs(
        result.away.no_vig_probability
        - (away_raw / (home_raw + away_raw))
    ) <= Decimal("1e-27")


def test_no_vig_probabilities_sum_exactly_to_one() -> None:
    result = calculate_per_book_no_vig(
        _market(provider_identity_id=11, home_price=-127, away_price=107)
    )

    assert (
        result.home.no_vig_probability + result.away.no_vig_probability
        == Decimal("1")
    )


def test_complete_market_rejects_one_sided_input() -> None:
    with pytest.raises(ValueError, match="exactly two"):
        build_complete_sportsbook_market((_selection("home", -110),))


@pytest.mark.parametrize("side", ("home", "away"))
def test_complete_market_rejects_duplicate_selection(side: str) -> None:
    with pytest.raises(ValueError, match="duplicate a side"):
        build_complete_sportsbook_market(
            (_selection(side, -110), _selection(side, 105))
        )


def test_complete_market_rejects_third_outcome() -> None:
    with pytest.raises(ValueError, match="exactly two"):
        build_complete_sportsbook_market(
            (
                _selection("home", -110),
                _selection("away", -110),
                _selection("home", 300),
            )
        )


@pytest.mark.parametrize(
    ("field_name", "changed_value"),
    (
        ("canonical_game_id", 999),
        ("sport_key", "baseball_mlb"),
        ("sportsbook_provider_identity_id", 999),
        ("trusted_observed_at", OBSERVED_AT + timedelta(seconds=1)),
    ),
)
def test_complete_market_rejects_mixed_context(
    field_name: str,
    changed_value,
) -> None:
    away = replace(
        _selection("away", -110),
        **{field_name: changed_value},
    )

    with pytest.raises(ValueError, match="must share"):
        build_complete_sportsbook_market((_selection("home", -110), away))


def test_selection_rejects_same_canonical_team_twice() -> None:
    with pytest.raises(ValueError, match="must be distinct"):
        _selection("home", -110, home_team_id=100, away_team_id=100)


def test_selection_rejects_unknown_canonical_selection_identity() -> None:
    with pytest.raises(ValueError, match="must match"):
        _selection("home", -110, selection_team_id=999)


def test_selection_rejects_invalid_price_and_naive_timestamp() -> None:
    with pytest.raises(ValueError, match="cannot be zero"):
        _selection("home", 0)
    with pytest.raises(ValueError, match="timezone-aware"):
        _selection("home", -110, trusted_observed_at=OBSERVED_AT.replace(tzinfo=None))


def test_one_book_consensus_equals_its_no_vig_market() -> None:
    no_vig = calculate_per_book_no_vig(
        _market(provider_identity_id=11, home_price=-125, away_price=105)
    )

    consensus = calculate_market_consensus((no_vig,))

    assert consensus.sportsbook_provider_identity_ids == (11,)
    assert consensus.sportsbook_count == 1
    assert consensus.home_no_vig_probability == no_vig.home.no_vig_probability
    assert consensus.away_no_vig_probability == no_vig.away.no_vig_probability


def test_multiple_book_consensus_is_equal_weight_average() -> None:
    first = calculate_per_book_no_vig(
        _market(provider_identity_id=11, home_price=-110, away_price=-110)
    )
    second = calculate_per_book_no_vig(
        _market(provider_identity_id=22, home_price=-150, away_price=130)
    )

    consensus = calculate_market_consensus((first, second))

    assert consensus.home_no_vig_probability == (
        first.home.no_vig_probability + second.home.no_vig_probability
    ) / Decimal("2")
    assert (
        consensus.home_no_vig_probability
        + consensus.away_no_vig_probability
        == Decimal("1")
    )


def test_consensus_rejects_duplicate_provider_identity() -> None:
    first = calculate_per_book_no_vig(
        _market(provider_identity_id=11, home_price=-110, away_price=-110)
    )
    duplicate = calculate_per_book_no_vig(
        _market(provider_identity_id=11, home_price=-120, away_price=100)
    )

    with pytest.raises(ValueError, match="may contribute only once"):
        calculate_market_consensus((first, duplicate))


def test_consensus_is_input_order_independent() -> None:
    markets = tuple(
        calculate_per_book_no_vig(
            _market(
                provider_identity_id=provider_identity_id,
                home_price=home_price,
                away_price=away_price,
            )
        )
        for provider_identity_id, home_price, away_price in (
            (33, -105, -115),
            (11, -110, -110),
            (22, 115, -135),
        )
    )

    assert calculate_market_consensus(markets) == calculate_market_consensus(
        reversed(markets)
    )


def test_consensus_identity_boundary_has_no_legacy_sportsbook_id() -> None:
    consensus_fields = {field.name for field in fields(MarketConsensus)}

    assert "sportsbook_id" not in consensus_fields
    assert "sportsbook_provider_identity_ids" in consensus_fields


def test_best_price_selects_highest_positive_return() -> None:
    best = find_best_offered_price(
        (
            _market(provider_identity_id=11, home_price=110),
            _market(provider_identity_id=22, home_price=120),
        ),
        selection_side="home",
    )

    assert best.american_price == 120
    assert best.sportsbook_provider_identity_id == 22


def test_best_price_selects_least_negative_price() -> None:
    best = find_best_offered_price(
        (
            _market(provider_identity_id=11, home_price=-115),
            _market(provider_identity_id=22, home_price=-105),
        ),
        selection_side="home",
    )

    assert best.american_price == -105
    assert best.sportsbook_provider_identity_id == 22


def test_best_price_compares_mixed_signs_by_decimal_return() -> None:
    best = find_best_offered_price(
        (
            _market(provider_identity_id=11, home_price=-105),
            _market(provider_identity_id=22, home_price=100),
        ),
        selection_side="home",
    )

    assert best.american_price == 100
    assert best.decimal_odds == Decimal("2")


def test_best_price_tie_uses_lowest_provider_identity() -> None:
    best = find_best_offered_price(
        (
            _market(provider_identity_id=22, home_price=120),
            _market(provider_identity_id=11, home_price=120),
        ),
        selection_side="home",
    )

    assert best.sportsbook_provider_identity_id == 11


def test_best_price_selects_home_and_away_independently() -> None:
    markets = (
        _market(
            provider_identity_id=11,
            home_price=120,
            away_price=-115,
        ),
        _market(
            provider_identity_id=22,
            home_price=110,
            away_price=-105,
        ),
    )

    home = find_best_offered_price(markets, selection_side="home")
    away = find_best_offered_price(markets, selection_side="away")

    assert (home.sportsbook_provider_identity_id, home.american_price) == (11, 120)
    assert (away.sportsbook_provider_identity_id, away.american_price) == (22, -105)


@pytest.mark.parametrize(
    ("model_probability", "market_probability", "expected_edge"),
    (
        (Decimal("0.60"), Decimal("0.55"), Decimal("0.05")),
        (Decimal("0.50"), Decimal("0.55"), Decimal("-0.05")),
        (Decimal("0.55"), Decimal("0.55"), Decimal("0.00")),
    ),
)
def test_model_market_edge_signs(
    model_probability: Decimal,
    market_probability: Decimal,
    expected_edge: Decimal,
) -> None:
    result = calculate_model_market_evaluation(
        model_probability=model_probability,
        consensus=_consensus(home_probability=market_probability),
        best_price=_best_price(selection_side="home", price=100),
    )

    assert result.market_edge == expected_edge


@pytest.mark.parametrize(
    ("model_probability", "price", "expected_ev"),
    (
        (Decimal("0.60"), 100, Decimal("0.20")),
        (Decimal("0.45"), 100, Decimal("-0.10")),
    ),
)
def test_model_expected_value_at_actual_price(
    model_probability: Decimal,
    price: int,
    expected_ev: Decimal,
) -> None:
    result = calculate_model_market_evaluation(
        model_probability=model_probability,
        consensus=_consensus(home_probability=Decimal("0.50")),
        best_price=_best_price(selection_side="home", price=price),
    )

    assert result.model_expected_value == expected_ev


def test_model_evaluation_works_for_away_selection() -> None:
    result = calculate_model_market_evaluation(
        model_probability=Decimal("0.50"),
        consensus=_consensus(home_probability=Decimal("0.55")),
        best_price=_best_price(selection_side="away", price=120),
    )

    assert result.selection_side == "away"
    assert result.canonical_selection_team_id == 200
    assert result.consensus_no_vig_probability == Decimal("0.45")
    assert result.market_edge == Decimal("0.05")
    assert result.model_expected_value == Decimal("0.10")


def test_model_evaluation_rejects_mixed_context() -> None:
    best_price = replace(_best_price(), canonical_game_id=999)

    with pytest.raises(ValueError, match="contexts do not match"):
        calculate_model_market_evaluation(
            model_probability=Decimal("0.55"),
            consensus=_consensus(),
            best_price=best_price,
        )


def test_model_evaluation_leaves_consensus_membership_to_caller() -> None:
    best_price = replace(
        _best_price(),
        sportsbook_provider_identity_id=33,
    )

    result = calculate_model_market_evaluation(
        model_probability=Decimal("0.55"),
        consensus=_consensus(),
        best_price=best_price,
    )

    assert result.sportsbook_provider_identity_id == 33


@pytest.mark.parametrize(
    "invalid_probability",
    (Decimal("-0.0001"), Decimal("1.0001"), Decimal("NaN")),
)
def test_model_evaluation_rejects_invalid_probability(
    invalid_probability: Decimal,
) -> None:
    with pytest.raises(ValueError, match="between zero and one"):
        calculate_model_market_evaluation(
            model_probability=invalid_probability,
            consensus=_consensus(),
            best_price=_best_price(),
        )


def _selection(
    selection_side: str,
    price: int,
    *,
    sport_key: str = NFL_SPORT,
    canonical_game_id: int = 10,
    home_team_id: int = 100,
    away_team_id: int = 200,
    selection_team_id: int | None = None,
    provider_identity_id: int = 11,
    trusted_observed_at: datetime = OBSERVED_AT,
) -> CanonicalSelectionPrice:
    if selection_team_id is None:
        selection_team_id = (
            home_team_id if selection_side == "home" else away_team_id
        )
    return CanonicalSelectionPrice(
        sport_key=sport_key,
        canonical_game_id=canonical_game_id,
        home_team_id=home_team_id,
        away_team_id=away_team_id,
        selection_team_id=selection_team_id,
        selection_side=selection_side,
        sportsbook_provider_identity_id=provider_identity_id,
        american_price=price,
        trusted_observed_at=trusted_observed_at,
    )


def _market(
    *,
    provider_identity_id: int,
    home_price: int = -110,
    away_price: int = -110,
) -> CompleteSportsbookMarket:
    return build_complete_sportsbook_market(
        (
            _selection(
                "home",
                home_price,
                provider_identity_id=provider_identity_id,
            ),
            _selection(
                "away",
                away_price,
                provider_identity_id=provider_identity_id,
            ),
        )
    )


def _consensus(
    *,
    home_probability: Decimal = Decimal("0.55"),
) -> MarketConsensus:
    return MarketConsensus(
        sport_key=NFL_SPORT,
        canonical_game_id=10,
        home_team_id=100,
        away_team_id=200,
        trusted_observed_at=OBSERVED_AT,
        sportsbook_provider_identity_ids=(11, 22),
        home_no_vig_probability=home_probability,
        away_no_vig_probability=Decimal("1") - home_probability,
    )


def _best_price(
    *,
    selection_side: str = "home",
    price: int = 100,
) -> BestOfferedPrice:
    selection_team_id = 100 if selection_side == "home" else 200
    return BestOfferedPrice(
        sport_key=NFL_SPORT,
        canonical_game_id=10,
        home_team_id=100,
        away_team_id=200,
        trusted_observed_at=OBSERVED_AT,
        canonical_selection_team_id=selection_team_id,
        selection_side=selection_side,
        sportsbook_provider_identity_id=11,
        american_price=price,
        decimal_odds=american_to_decimal_odds(price),
    )
