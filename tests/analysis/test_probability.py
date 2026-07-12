from decimal import Decimal

from sportsmodel.analysis.probability import (
    american_to_implied_probability,
    remove_vig,
)


def test_even_money_conversion():
    probability = american_to_implied_probability(100)

    assert probability == Decimal("0.5")


def test_minus_110_conversion():
    probability = american_to_implied_probability(-110)

    assert probability.quantize(
        Decimal("0.000001")
    ) == Decimal("0.523810")


def test_plus_150_conversion():
    probability = american_to_implied_probability(150)

    assert probability == Decimal("0.4")


def test_remove_vig_even_market():
    implied = [
        american_to_implied_probability(-110),
        american_to_implied_probability(-110),
    ]

    normalized = remove_vig(implied)

    assert normalized[0].quantize(
        Decimal("0.000001")
    ) == Decimal("0.500000")

    assert normalized[1].quantize(
        Decimal("0.000001")
    ) == Decimal("0.500000")


def test_probabilities_sum_to_one():
    implied = [
        american_to_implied_probability(-135),
        american_to_implied_probability(115),
    ]

    normalized = remove_vig(implied)

    total = sum(normalized)

    assert total.quantize(
        Decimal("0.000001")
    ) == Decimal("1.000000")