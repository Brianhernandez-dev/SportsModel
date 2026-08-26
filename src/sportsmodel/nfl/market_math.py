from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, localcontext
from typing import Literal, Protocol, TypeVar

from sportsmodel.analysis import probability as shared_probability


DECIMAL_PRECISION = 28
SelectionSide = Literal["home", "away"]


class _ContextMarket(Protocol):
    sport_key: str
    canonical_game_id: int
    home_team_id: int
    away_team_id: int
    sportsbook_provider_identity_id: int
    trusted_observed_at: datetime


_ContextMarketType = TypeVar(
    "_ContextMarketType",
    bound=_ContextMarket,
)


@dataclass(frozen=True)
class CanonicalSelectionPrice:
    """One canonical NFL selection at one trusted observation instant."""

    sport_key: str
    canonical_game_id: int
    home_team_id: int
    away_team_id: int
    selection_team_id: int
    selection_side: SelectionSide
    sportsbook_provider_identity_id: int
    american_price: int
    trusted_observed_at: datetime

    def __post_init__(self) -> None:
        _validate_market_identity(
            sport_key=self.sport_key,
            canonical_game_id=self.canonical_game_id,
            home_team_id=self.home_team_id,
            away_team_id=self.away_team_id,
            trusted_observed_at=self.trusted_observed_at,
        )
        _validate_positive_identifier(
            self.sportsbook_provider_identity_id,
            "sportsbook_provider_identity_id",
        )
        _validate_selection(
            selection_side=self.selection_side,
            selection_team_id=self.selection_team_id,
            home_team_id=self.home_team_id,
            away_team_id=self.away_team_id,
        )
        _validate_american_price(self.american_price)


@dataclass(frozen=True)
class CompleteSportsbookMarket:
    """A validated two-sided H2H market from one provider book."""

    sport_key: str
    canonical_game_id: int
    home_team_id: int
    away_team_id: int
    sportsbook_provider_identity_id: int
    trusted_observed_at: datetime
    home: CanonicalSelectionPrice
    away: CanonicalSelectionPrice

    def __post_init__(self) -> None:
        expected_key = _complete_market_key_from_values(
            sport_key=self.sport_key,
            canonical_game_id=self.canonical_game_id,
            home_team_id=self.home_team_id,
            away_team_id=self.away_team_id,
            sportsbook_provider_identity_id=(
                self.sportsbook_provider_identity_id
            ),
            trusted_observed_at=self.trusted_observed_at,
        )
        if _complete_market_key(self.home) != expected_key:
            raise ValueError("Home selection does not match the market context.")
        if _complete_market_key(self.away) != expected_key:
            raise ValueError("Away selection does not match the market context.")
        if self.home.selection_side != "home":
            raise ValueError("The home market selection must be the home side.")
        if self.away.selection_side != "away":
            raise ValueError("The away market selection must be the away side.")


@dataclass(frozen=True)
class NoVigSelection:
    """One canonical selection after removing one book's overround."""

    canonical_selection_team_id: int
    selection_side: SelectionSide
    american_price: int
    implied_probability: Decimal
    no_vig_probability: Decimal


@dataclass(frozen=True)
class PerBookNoVigMarket:
    """No-vig probabilities for one complete provider-identity market."""

    sport_key: str
    canonical_game_id: int
    home_team_id: int
    away_team_id: int
    sportsbook_provider_identity_id: int
    trusted_observed_at: datetime
    overround: Decimal
    home: NoVigSelection
    away: NoVigSelection

    def __post_init__(self) -> None:
        _validate_market_identity(
            sport_key=self.sport_key,
            canonical_game_id=self.canonical_game_id,
            home_team_id=self.home_team_id,
            away_team_id=self.away_team_id,
            trusted_observed_at=self.trusted_observed_at,
        )
        _validate_positive_identifier(
            self.sportsbook_provider_identity_id,
            "sportsbook_provider_identity_id",
        )
        if self.overround <= Decimal("0"):
            raise ValueError("Market overround must be greater than zero.")
        _validate_no_vig_selection(
            self.home,
            expected_side="home",
            expected_team_id=self.home_team_id,
        )
        _validate_no_vig_selection(
            self.away,
            expected_side="away",
            expected_team_id=self.away_team_id,
        )
        if (
            self.home.no_vig_probability
            + self.away.no_vig_probability
            != Decimal("1")
        ):
            raise ValueError("No-vig probabilities must sum exactly to one.")


@dataclass(frozen=True)
class MarketConsensus:
    """Equal-weight consensus of one no-vig vote per provider identity."""

    sport_key: str
    canonical_game_id: int
    home_team_id: int
    away_team_id: int
    trusted_observed_at: datetime
    sportsbook_provider_identity_ids: tuple[int, ...]
    home_no_vig_probability: Decimal
    away_no_vig_probability: Decimal

    def __post_init__(self) -> None:
        _validate_market_identity(
            sport_key=self.sport_key,
            canonical_game_id=self.canonical_game_id,
            home_team_id=self.home_team_id,
            away_team_id=self.away_team_id,
            trusted_observed_at=self.trusted_observed_at,
        )
        if not self.sportsbook_provider_identity_ids:
            raise ValueError("Consensus requires at least one provider identity.")
        if tuple(sorted(self.sportsbook_provider_identity_ids)) != (
            self.sportsbook_provider_identity_ids
        ):
            raise ValueError("Consensus provider identities must be sorted.")
        if len(set(self.sportsbook_provider_identity_ids)) != len(
            self.sportsbook_provider_identity_ids
        ):
            raise ValueError("Consensus provider identities must be unique.")
        for provider_identity_id in self.sportsbook_provider_identity_ids:
            _validate_positive_identifier(
                provider_identity_id,
                "sportsbook_provider_identity_id",
            )
        _validate_probability(
            self.home_no_vig_probability,
            "home_no_vig_probability",
        )
        _validate_probability(
            self.away_no_vig_probability,
            "away_no_vig_probability",
        )
        if (
            self.home_no_vig_probability
            + self.away_no_vig_probability
            != Decimal("1")
        ):
            raise ValueError("Consensus probabilities must sum exactly to one.")

    @property
    def sportsbook_count(self) -> int:
        return len(self.sportsbook_provider_identity_ids)


@dataclass(frozen=True)
class BestOfferedPrice:
    """Best eligible price for one canonical selection."""

    sport_key: str
    canonical_game_id: int
    home_team_id: int
    away_team_id: int
    trusted_observed_at: datetime
    canonical_selection_team_id: int
    selection_side: SelectionSide
    sportsbook_provider_identity_id: int
    american_price: int
    decimal_odds: Decimal

    def __post_init__(self) -> None:
        _validate_market_identity(
            sport_key=self.sport_key,
            canonical_game_id=self.canonical_game_id,
            home_team_id=self.home_team_id,
            away_team_id=self.away_team_id,
            trusted_observed_at=self.trusted_observed_at,
        )
        _validate_selection(
            selection_side=self.selection_side,
            selection_team_id=self.canonical_selection_team_id,
            home_team_id=self.home_team_id,
            away_team_id=self.away_team_id,
        )
        _validate_positive_identifier(
            self.sportsbook_provider_identity_id,
            "sportsbook_provider_identity_id",
        )
        _validate_american_price(self.american_price)
        if self.decimal_odds != american_to_decimal_odds(
            self.american_price
        ):
            raise ValueError(
                "decimal_odds must match the offered American price."
            )


@dataclass(frozen=True)
class ModelMarketEvaluationMath:
    """Pure model-versus-market calculations with no policy or persistence."""

    sport_key: str
    canonical_game_id: int
    canonical_selection_team_id: int
    selection_side: SelectionSide
    sportsbook_provider_identity_id: int
    american_price: int
    decimal_offered_odds: Decimal
    model_probability: Decimal
    consensus_no_vig_probability: Decimal
    market_edge: Decimal
    model_expected_value: Decimal


def american_to_implied_probability(price: int) -> Decimal:
    """Convert nonzero integer American odds to implied probability."""

    _validate_american_price(price)
    with localcontext() as context:
        context.prec = DECIMAL_PRECISION
        return shared_probability.american_to_implied_probability(price)


def american_to_decimal_odds(price: int) -> Decimal:
    """Convert nonzero integer American odds to decimal return odds."""

    _validate_american_price(price)
    with localcontext() as context:
        context.prec = DECIMAL_PRECISION
        return shared_probability.american_to_decimal_odds(price)


def build_complete_sportsbook_market(
    prices: Iterable[CanonicalSelectionPrice],
) -> CompleteSportsbookMarket:
    """Validate exactly one home and one away price from one book/context."""

    selections = tuple(prices)
    if len(selections) != 2:
        raise ValueError("A complete H2H market requires exactly two outcomes.")

    reference_key = _complete_market_key(selections[0])
    if any(
        _complete_market_key(selection) != reference_key
        for selection in selections[1:]
    ):
        raise ValueError(
            "H2H selections must share sport, game, teams, provider identity, "
            "and trusted observation time."
        )

    selections_by_side: dict[SelectionSide, CanonicalSelectionPrice] = {}
    for selection in selections:
        if selection.selection_side in selections_by_side:
            raise ValueError("A complete H2H market cannot duplicate a side.")
        selections_by_side[selection.selection_side] = selection

    if set(selections_by_side) != {"home", "away"}:
        raise ValueError("A complete H2H market requires home and away outcomes.")

    return CompleteSportsbookMarket(
        sport_key=selections[0].sport_key,
        canonical_game_id=selections[0].canonical_game_id,
        home_team_id=selections[0].home_team_id,
        away_team_id=selections[0].away_team_id,
        sportsbook_provider_identity_id=(
            selections[0].sportsbook_provider_identity_id
        ),
        trusted_observed_at=selections[0].trusted_observed_at,
        home=selections_by_side["home"],
        away=selections_by_side["away"],
    )


def calculate_per_book_no_vig(
    market: CompleteSportsbookMarket,
) -> PerBookNoVigMarket:
    """Normalize one complete two-outcome market to no-vig probabilities."""

    with localcontext() as context:
        context.prec = DECIMAL_PRECISION
        home_raw = american_to_implied_probability(market.home.american_price)
        away_raw = american_to_implied_probability(market.away.american_price)
        overround = home_raw + away_raw
        if overround <= Decimal("0"):
            raise ValueError("Market overround must be greater than zero.")
        home_no_vig = home_raw / overround
        away_no_vig = Decimal("1") - home_no_vig

    return PerBookNoVigMarket(
        sport_key=market.sport_key,
        canonical_game_id=market.canonical_game_id,
        home_team_id=market.home_team_id,
        away_team_id=market.away_team_id,
        sportsbook_provider_identity_id=(
            market.sportsbook_provider_identity_id
        ),
        trusted_observed_at=market.trusted_observed_at,
        overround=overround,
        home=NoVigSelection(
            canonical_selection_team_id=market.home.selection_team_id,
            selection_side="home",
            american_price=market.home.american_price,
            implied_probability=home_raw,
            no_vig_probability=home_no_vig,
        ),
        away=NoVigSelection(
            canonical_selection_team_id=market.away.selection_team_id,
            selection_side="away",
            american_price=market.away.american_price,
            implied_probability=away_raw,
            no_vig_probability=away_no_vig,
        ),
    )


def calculate_market_consensus(
    markets: Iterable[PerBookNoVigMarket],
) -> MarketConsensus:
    """
    Average one selected PIT no-vig observation per provider identity.

    Temporal eligibility and observation selection belong to the caller.
    Duplicate provider identities are rejected rather than averaged.
    """

    ordered = _validated_market_collection(markets)
    with localcontext() as context:
        context.prec = DECIMAL_PRECISION
        home_probability = sum(
            (market.home.no_vig_probability for market in ordered),
            Decimal("0"),
        ) / Decimal(len(ordered))
        away_probability = Decimal("1") - home_probability

    reference = ordered[0]
    return MarketConsensus(
        sport_key=reference.sport_key,
        canonical_game_id=reference.canonical_game_id,
        home_team_id=reference.home_team_id,
        away_team_id=reference.away_team_id,
        trusted_observed_at=reference.trusted_observed_at,
        sportsbook_provider_identity_ids=tuple(
            market.sportsbook_provider_identity_id for market in ordered
        ),
        home_no_vig_probability=home_probability,
        away_no_vig_probability=away_probability,
    )


def find_best_offered_price(
    markets: Iterable[CompleteSportsbookMarket],
    *,
    selection_side: SelectionSide,
) -> BestOfferedPrice:
    """Choose the largest decimal return, breaking ties by provider ID."""

    _validate_selection_side(selection_side)
    ordered = _validated_market_collection(markets)
    candidates = [
        market.home if selection_side == "home" else market.away
        for market in ordered
    ]
    best = max(
        candidates,
        key=lambda selection: (
            american_to_decimal_odds(selection.american_price),
            -selection.sportsbook_provider_identity_id,
        ),
    )
    decimal_odds = american_to_decimal_odds(best.american_price)

    return BestOfferedPrice(
        sport_key=best.sport_key,
        canonical_game_id=best.canonical_game_id,
        home_team_id=best.home_team_id,
        away_team_id=best.away_team_id,
        trusted_observed_at=best.trusted_observed_at,
        canonical_selection_team_id=best.selection_team_id,
        selection_side=best.selection_side,
        sportsbook_provider_identity_id=(
            best.sportsbook_provider_identity_id
        ),
        american_price=best.american_price,
        decimal_odds=decimal_odds,
    )


def calculate_model_market_evaluation(
    *,
    model_probability: Decimal,
    consensus: MarketConsensus,
    best_price: BestOfferedPrice,
) -> ModelMarketEvaluationMath:
    """Calculate model-minus-consensus edge and model EV at offered price."""

    _validate_probability(model_probability, "model_probability")
    if _consensus_context_key(consensus) != _best_price_context_key(best_price):
        raise ValueError("Consensus and best price contexts do not match.")

    if best_price.selection_side == "home":
        market_probability = consensus.home_no_vig_probability
    else:
        market_probability = consensus.away_no_vig_probability

    with localcontext() as context:
        context.prec = DECIMAL_PRECISION
        market_edge = model_probability - market_probability
        model_expected_value = (
            model_probability * best_price.decimal_odds - Decimal("1")
        )

    return ModelMarketEvaluationMath(
        sport_key=best_price.sport_key,
        canonical_game_id=best_price.canonical_game_id,
        canonical_selection_team_id=(
            best_price.canonical_selection_team_id
        ),
        selection_side=best_price.selection_side,
        sportsbook_provider_identity_id=(
            best_price.sportsbook_provider_identity_id
        ),
        american_price=best_price.american_price,
        decimal_offered_odds=best_price.decimal_odds,
        model_probability=model_probability,
        consensus_no_vig_probability=market_probability,
        market_edge=market_edge,
        model_expected_value=model_expected_value,
    )


def _validated_market_collection(
    markets: Iterable[_ContextMarketType],
) -> tuple[_ContextMarketType, ...]:
    ordered = tuple(
        sorted(
            markets,
            key=lambda market: market.sportsbook_provider_identity_id,
        )
    )
    if not ordered:
        raise ValueError("At least one complete provider market is required.")

    provider_identity_ids = tuple(
        market.sportsbook_provider_identity_id for market in ordered
    )
    if len(set(provider_identity_ids)) != len(provider_identity_ids):
        raise ValueError(
            "Each sportsbook_provider_identity_id may contribute only once."
        )

    reference_key = _market_context_key(ordered[0])
    if any(
        _market_context_key(market) != reference_key for market in ordered[1:]
    ):
        raise ValueError(
            "Provider markets must share sport, game, teams, and trusted "
            "observation context."
        )
    return ordered


def _market_context_key(market: _ContextMarket) -> tuple:
    return (
        market.sport_key,
        market.canonical_game_id,
        market.home_team_id,
        market.away_team_id,
        market.trusted_observed_at,
    )


def _complete_market_key(selection: CanonicalSelectionPrice) -> tuple:
    return _complete_market_key_from_values(
        sport_key=selection.sport_key,
        canonical_game_id=selection.canonical_game_id,
        home_team_id=selection.home_team_id,
        away_team_id=selection.away_team_id,
        sportsbook_provider_identity_id=(
            selection.sportsbook_provider_identity_id
        ),
        trusted_observed_at=selection.trusted_observed_at,
    )


def _complete_market_key_from_values(
    *,
    sport_key: str,
    canonical_game_id: int,
    home_team_id: int,
    away_team_id: int,
    sportsbook_provider_identity_id: int,
    trusted_observed_at: datetime,
) -> tuple:
    return (
        sport_key,
        canonical_game_id,
        home_team_id,
        away_team_id,
        sportsbook_provider_identity_id,
        trusted_observed_at,
    )


def _consensus_context_key(consensus: MarketConsensus) -> tuple:
    return (
        consensus.sport_key,
        consensus.canonical_game_id,
        consensus.home_team_id,
        consensus.away_team_id,
        consensus.trusted_observed_at,
    )


def _best_price_context_key(best_price: BestOfferedPrice) -> tuple:
    return (
        best_price.sport_key,
        best_price.canonical_game_id,
        best_price.home_team_id,
        best_price.away_team_id,
        best_price.trusted_observed_at,
    )


def _validate_market_identity(
    *,
    sport_key: str,
    canonical_game_id: int,
    home_team_id: int,
    away_team_id: int,
    trusted_observed_at: datetime,
) -> None:
    if not isinstance(sport_key, str) or not sport_key.strip():
        raise ValueError("sport_key must be non-empty text.")
    if sport_key != sport_key.strip():
        raise ValueError("sport_key must be canonical text without whitespace.")
    _validate_positive_identifier(canonical_game_id, "canonical_game_id")
    _validate_positive_identifier(home_team_id, "home_team_id")
    _validate_positive_identifier(away_team_id, "away_team_id")
    if home_team_id == away_team_id:
        raise ValueError("Home and away canonical teams must be distinct.")
    if (
        not isinstance(trusted_observed_at, datetime)
        or trusted_observed_at.tzinfo is None
        or trusted_observed_at.utcoffset() is None
    ):
        raise ValueError("trusted_observed_at must be timezone-aware.")


def _validate_selection(
    *,
    selection_side: str,
    selection_team_id: int,
    home_team_id: int,
    away_team_id: int,
) -> None:
    _validate_selection_side(selection_side)
    _validate_positive_identifier(selection_team_id, "selection_team_id")
    expected_team_id = (
        home_team_id if selection_side == "home" else away_team_id
    )
    if selection_team_id != expected_team_id:
        raise ValueError(
            "Selection team must match its canonical home/away identity."
        )


def _validate_selection_side(selection_side: str) -> None:
    if selection_side not in ("home", "away"):
        raise ValueError("selection_side must be 'home' or 'away'.")


def _validate_no_vig_selection(
    selection: NoVigSelection,
    *,
    expected_side: SelectionSide,
    expected_team_id: int,
) -> None:
    if selection.selection_side != expected_side:
        raise ValueError("No-vig selection side does not match the market.")
    if selection.canonical_selection_team_id != expected_team_id:
        raise ValueError("No-vig selection team does not match the market.")
    _validate_american_price(selection.american_price)
    _validate_probability(
        selection.implied_probability,
        "implied_probability",
    )
    _validate_probability(
        selection.no_vig_probability,
        "no_vig_probability",
    )


def _validate_probability(value: Decimal, field_name: str) -> None:
    if not isinstance(value, Decimal):
        raise TypeError(f"{field_name} must be a Decimal.")
    if not value.is_finite() or value < Decimal("0") or value > Decimal("1"):
        raise ValueError(f"{field_name} must be between zero and one.")


def _validate_american_price(price: int) -> None:
    if not isinstance(price, int) or isinstance(price, bool):
        raise TypeError("American odds must be an integer.")
    if price == 0:
        raise ValueError("American odds cannot be zero.")


def _validate_positive_identifier(value: int, field_name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{field_name} must be a positive integer.")
