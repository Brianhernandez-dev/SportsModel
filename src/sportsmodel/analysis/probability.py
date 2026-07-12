from decimal import Decimal, getcontext


getcontext().prec = 28


def american_to_implied_probability(price: int) -> Decimal:
    """
    Convert American odds to implied probability.
    """

    if price == 0:
        raise ValueError("American odds cannot be zero.")

    if price > 0:
        return Decimal(100) / Decimal(price + 100)

    return Decimal(-price) / Decimal((-price) + 100)


def american_to_decimal_odds(price: int) -> Decimal:
    """
    Convert American odds to decimal odds.

    Examples:
        +150 -> 2.50
        -200 -> 1.50
    """

    if price == 0:
        raise ValueError("American odds cannot be zero.")

    if price > 0:
        return Decimal(1) + (
            Decimal(price) / Decimal(100)
        )

    return Decimal(1) + (
        Decimal(100) / Decimal(-price)
    )


def remove_vig(
    implied_probabilities: list[Decimal],
) -> list[Decimal]:
    """
    Normalize implied probabilities so they sum to 1.0.
    """

    if not implied_probabilities:
        raise ValueError("At least one probability is required.")

    total = sum(implied_probabilities)

    if total <= 0:
        raise ValueError(
            "Probability total must be greater than zero."
        )

    return [
        probability / total
        for probability in implied_probabilities
    ]