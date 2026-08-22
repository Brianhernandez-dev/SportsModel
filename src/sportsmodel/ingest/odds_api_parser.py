"""Strict offline parsing for The Odds API two-outcome H2H payloads."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any


ODDS_API_MLB_SPORT_KEY = "baseball_mlb"
ODDS_API_NFL_SPORT_KEY = "americanfootball_nfl"
SUPPORTED_ODDS_API_SPORT_KEYS = frozenset(
    {
        ODDS_API_MLB_SPORT_KEY,
        ODDS_API_NFL_SPORT_KEY,
    }
)


class OddsApiPayloadError(ValueError):
    """Raised when an Odds API response cannot be preserved safely."""


@dataclass(frozen=True)
class OddsApiH2HOutcome:
    selection_name: str
    american_price: int
    line_value: Decimal | None


@dataclass(frozen=True)
class OddsApiH2HMarket:
    market_key: str
    last_update: datetime | None
    outcomes: tuple[OddsApiH2HOutcome, ...]


@dataclass(frozen=True)
class OddsApiBookmaker:
    bookmaker_key: str
    title: str
    last_update: datetime | None
    markets: tuple[OddsApiH2HMarket, ...]


@dataclass(frozen=True)
class OddsApiEvent:
    event_id: str
    sport_key: str
    commence_time: datetime
    home_team: str
    away_team: str
    bookmakers: tuple[OddsApiBookmaker, ...]


def parse_odds_api_h2h_response(
    payload: Any,
    *,
    expected_sport_key: str,
) -> tuple[OddsApiEvent, ...]:
    """Parse one MLB or NFL H2H response without I/O or persistence."""

    if expected_sport_key not in SUPPORTED_ODDS_API_SPORT_KEYS:
        raise ValueError(
            "Unsupported Odds API sport key: "
            f"{expected_sport_key!r}."
        )
    if not isinstance(payload, list):
        raise OddsApiPayloadError(
            "Odds API response must be a JSON array."
        )

    events = tuple(
        _parse_event(
            value,
            expected_sport_key=expected_sport_key,
            path=f"events[{index}]",
        )
        for index, value in enumerate(payload)
    )

    event_ids = [event.event_id for event in events]
    if len(event_ids) != len(set(event_ids)):
        raise OddsApiPayloadError(
            "Odds API response contains duplicate event IDs."
        )

    return events


def _parse_event(
    value: Any,
    *,
    expected_sport_key: str,
    path: str,
) -> OddsApiEvent:
    event = _mapping(value, path)
    event_id = _text(event.get("id"), f"{path}.id")
    sport_key = _text(
        event.get("sport_key"),
        f"{path}.sport_key",
    )
    if sport_key != expected_sport_key:
        raise OddsApiPayloadError(
            f"{path}.sport_key must equal "
            f"{expected_sport_key!r}; found {sport_key!r}."
        )

    home_team = _text(
        event.get("home_team"),
        f"{path}.home_team",
    )
    away_team = _text(
        event.get("away_team"),
        f"{path}.away_team",
    )
    if home_team == away_team:
        raise OddsApiPayloadError(
            f"{path} home and away teams must differ."
        )

    bookmakers_value = event.get("bookmakers")
    if not isinstance(bookmakers_value, list):
        raise OddsApiPayloadError(
            f"{path}.bookmakers must be an array."
        )
    bookmakers = tuple(
        _parse_bookmaker(
            bookmaker,
            home_team=home_team,
            away_team=away_team,
            path=f"{path}.bookmakers[{index}]",
        )
        for index, bookmaker in enumerate(bookmakers_value)
    )
    bookmaker_keys = [item.bookmaker_key for item in bookmakers]
    if len(bookmaker_keys) != len(set(bookmaker_keys)):
        raise OddsApiPayloadError(
            f"{path} contains duplicate bookmaker keys."
        )

    return OddsApiEvent(
        event_id=event_id,
        sport_key=sport_key,
        commence_time=_timestamp(
            event.get("commence_time"),
            f"{path}.commence_time",
            required=True,
        ),
        home_team=home_team,
        away_team=away_team,
        bookmakers=bookmakers,
    )


def _parse_bookmaker(
    value: Any,
    *,
    home_team: str,
    away_team: str,
    path: str,
) -> OddsApiBookmaker:
    bookmaker = _mapping(value, path)
    markets_value = bookmaker.get("markets")
    if not isinstance(markets_value, list) or not markets_value:
        raise OddsApiPayloadError(
            f"{path}.markets must be a non-empty array."
        )
    markets = tuple(
        _parse_market(
            market,
            home_team=home_team,
            away_team=away_team,
            path=f"{path}.markets[{index}]",
        )
        for index, market in enumerate(markets_value)
    )
    if len(markets) != 1:
        raise OddsApiPayloadError(
            f"{path} must contain exactly one H2H market."
        )

    return OddsApiBookmaker(
        bookmaker_key=_text(
            bookmaker.get("key"),
            f"{path}.key",
        ),
        title=_text(
            bookmaker.get("title"),
            f"{path}.title",
        ),
        last_update=_timestamp(
            bookmaker.get("last_update"),
            f"{path}.last_update",
            required=False,
        ),
        markets=markets,
    )


def _parse_market(
    value: Any,
    *,
    home_team: str,
    away_team: str,
    path: str,
) -> OddsApiH2HMarket:
    market = _mapping(value, path)
    market_key = _text(market.get("key"), f"{path}.key")
    if market_key != "h2h":
        raise OddsApiPayloadError(
            f"{path}.key must be 'h2h'; found {market_key!r}."
        )
    outcomes_value = market.get("outcomes")
    if not isinstance(outcomes_value, list):
        raise OddsApiPayloadError(
            f"{path}.outcomes must be an array."
        )
    outcomes = tuple(
        _parse_outcome(
            outcome,
            path=f"{path}.outcomes[{index}]",
        )
        for index, outcome in enumerate(outcomes_value)
    )
    expected_selections = {home_team, away_team}
    actual_selections = {
        outcome.selection_name for outcome in outcomes
    }
    if (
        len(outcomes) != 2
        or actual_selections != expected_selections
    ):
        raise OddsApiPayloadError(
            f"{path} must contain exactly one outcome for each "
            "provider home and away team."
        )

    return OddsApiH2HMarket(
        market_key=market_key,
        last_update=_timestamp(
            market.get("last_update"),
            f"{path}.last_update",
            required=False,
        ),
        outcomes=outcomes,
    )


def _parse_outcome(
    value: Any,
    *,
    path: str,
) -> OddsApiH2HOutcome:
    outcome = _mapping(value, path)
    price = outcome.get("price")
    if isinstance(price, bool) or not isinstance(price, int):
        raise OddsApiPayloadError(
            f"{path}.price must be integer American odds."
        )
    if price == 0:
        raise OddsApiPayloadError(
            f"{path}.price cannot be zero."
        )

    point = outcome.get("point")
    if point is not None and (
        isinstance(point, bool)
        or not isinstance(point, (int, float))
    ):
        raise OddsApiPayloadError(
            f"{path}.point must be numeric when present."
        )

    return OddsApiH2HOutcome(
        selection_name=_text(
            outcome.get("name"),
            f"{path}.name",
        ),
        american_price=price,
        line_value=(
            None if point is None else Decimal(str(point))
        ),
    )


def _mapping(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise OddsApiPayloadError(
            f"{path} must be a JSON object."
        )
    return value


def _text(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise OddsApiPayloadError(
            f"{path} must be non-empty text."
        )
    return value


def _timestamp(
    value: Any,
    path: str,
    *,
    required: bool,
) -> datetime | None:
    if value is None and not required:
        return None
    if not isinstance(value, str) or not value.strip():
        raise OddsApiPayloadError(
            f"{path} must be a timezone-aware timestamp."
        )
    try:
        parsed = datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )
    except ValueError as error:
        raise OddsApiPayloadError(
            f"{path} must be a valid timestamp."
        ) from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise OddsApiPayloadError(
            f"{path} must be timezone-aware."
        )
    return parsed.astimezone(timezone.utc)
