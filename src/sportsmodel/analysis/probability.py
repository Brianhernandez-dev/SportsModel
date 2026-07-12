from decimal import Decimal, getcontext

# Increase precision for repeated probability calculations.
getcontext().prec = 28


def american_to_implied_probability(price: int) -> Decimal:
    """
    Convert American odds to implied probability.

    Examples:
        -110 -> 0.5238095238
        +150 -> 0.4000000000
    """

    if price == 0:
        raise ValueError("American odds cannot be zero.")

    if price > 0:
        return Decimal(100) / Decimal(price + 100)

    return Decimal(-price) / Decimal((-price) + 100)


def remove_vig(
    implied_probabilities: list[Decimal],
) -> list[Decimal]:
    """
    Normalize implied probabilities so they sum to exactly 1.0.
    """

    if not implied_probabilities:
        raise ValueError("At least one probability is required.")

    total = sum(implied_probabilities)

    if total <= 0:
        raise ValueError("Probability total must be greater than zero.")

    return [
        probability / total
        for probability in implied_probabilities
    ]