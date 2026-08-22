from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from sportsmodel.ingest.odds_api_parser import (
    ODDS_API_MLB_SPORT_KEY,
    ODDS_API_NFL_SPORT_KEY,
    OddsApiPayloadError,
    parse_odds_api_h2h_response,
)


FIXTURES = Path(__file__).parents[1] / "fixtures" / "odds_api"


def _fixture(name: str):
    return json.loads(
        (FIXTURES / name).read_text(encoding="utf-8")
    )


def test_parses_valid_mlb_h2h_response_offline() -> None:
    events = parse_odds_api_h2h_response(
        _fixture("mlb_h2h.json"),
        expected_sport_key=ODDS_API_MLB_SPORT_KEY,
    )

    assert len(events) == 1
    event = events[0]
    assert event.event_id == "mlb-event-2026-08-21-001"
    assert event.sport_key == ODDS_API_MLB_SPORT_KEY
    assert event.home_team == "Seattle Mariners"
    assert event.away_team == "New York Yankees"
    assert {
        outcome.selection_name
        for outcome in event.bookmakers[0].markets[0].outcomes
    } == {event.home_team, event.away_team}


def test_parses_valid_nfl_h2h_response_offline() -> None:
    events = parse_odds_api_h2h_response(
        _fixture("nfl_h2h.json"),
        expected_sport_key=ODDS_API_NFL_SPORT_KEY,
    )

    event = events[0]
    assert event.event_id == "nfl-event-2026-week-01-001"
    assert event.sport_key == ODDS_API_NFL_SPORT_KEY
    assert event.home_team == "Kansas City Chiefs"
    assert event.away_team == "Denver Broncos"
    assert event.bookmakers[0].bookmaker_key == "betmgm"
    assert event.bookmakers[0].title == "BetMGM"
    assert event.bookmakers[0].markets[0].market_key == "h2h"
    assert [
        outcome.american_price
        for outcome in event.bookmakers[0].markets[0].outcomes
    ] == [-145, 125]


def test_preserves_multiple_bookmakers_and_provider_keys() -> None:
    event = parse_odds_api_h2h_response(
        _fixture("mlb_h2h.json"),
        expected_sport_key=ODDS_API_MLB_SPORT_KEY,
    )[0]

    assert [
        bookmaker.bookmaker_key
        for bookmaker in event.bookmakers
    ] == ["fanduel", "draftkings"]
    assert [
        bookmaker.title for bookmaker in event.bookmakers
    ] == ["FanDuel", "DraftKings"]


def test_rejects_incomplete_h2h_outcomes() -> None:
    payload = _fixture("nfl_h2h.json")
    payload[0]["bookmakers"][0]["markets"][0][
        "outcomes"
    ].pop()

    with pytest.raises(
        OddsApiPayloadError,
        match="exactly one outcome",
    ):
        parse_odds_api_h2h_response(
            payload,
            expected_sport_key=ODDS_API_NFL_SPORT_KEY,
        )


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        (
            lambda payload: payload[0]["bookmakers"][0][
                "markets"
            ][0].__setitem__("key", "spreads"),
            "must be 'h2h'",
        ),
        (
            lambda payload: payload[0]["bookmakers"][0][
                "markets"
            ][0]["outcomes"][0].__setitem__(
                "price", "-145"
            ),
            "integer American odds",
        ),
        (
            lambda payload: payload[0].__setitem__(
                "commence_time", "2026-09-10T20:20:00"
            ),
            "timezone-aware",
        ),
    ),
)
def test_rejects_malformed_or_unsupported_market_data(
    mutation,
    message,
) -> None:
    payload = deepcopy(_fixture("nfl_h2h.json"))
    mutation(payload)

    with pytest.raises(OddsApiPayloadError, match=message):
        parse_odds_api_h2h_response(
            payload,
            expected_sport_key=ODDS_API_NFL_SPORT_KEY,
        )


def test_preserves_timestamp_instants_as_timezone_aware_utc() -> None:
    mlb = parse_odds_api_h2h_response(
        _fixture("mlb_h2h.json"),
        expected_sport_key=ODDS_API_MLB_SPORT_KEY,
    )[0]
    nfl = parse_odds_api_h2h_response(
        _fixture("nfl_h2h.json"),
        expected_sport_key=ODDS_API_NFL_SPORT_KEY,
    )[0]

    assert mlb.commence_time == datetime(
        2026, 8, 21, 23, 10, tzinfo=timezone.utc
    )
    assert mlb.bookmakers[0].last_update == datetime(
        2026, 8, 21, 18, 0, 1, tzinfo=timezone.utc
    )
    assert mlb.bookmakers[0].markets[0].last_update == datetime(
        2026, 8, 21, 18, 0, tzinfo=timezone.utc
    )
    assert nfl.commence_time == datetime(
        2026, 9, 11, 0, 20, tzinfo=timezone.utc
    )


def test_rejects_cross_sport_payload_and_unsupported_sport() -> None:
    with pytest.raises(OddsApiPayloadError, match="sport_key must equal"):
        parse_odds_api_h2h_response(
            _fixture("nfl_h2h.json"),
            expected_sport_key=ODDS_API_MLB_SPORT_KEY,
        )

    with pytest.raises(ValueError, match="Unsupported Odds API sport"):
        parse_odds_api_h2h_response(
            [],
            expected_sport_key="basketball_nba",
        )


def test_rejects_non_array_response() -> None:
    with pytest.raises(OddsApiPayloadError, match="JSON array"):
        parse_odds_api_h2h_response(
            {"events": []},
            expected_sport_key=ODDS_API_NFL_SPORT_KEY,
        )
