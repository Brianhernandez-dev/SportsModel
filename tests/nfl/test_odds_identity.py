import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from sportsmodel.ingest.odds_api_parser import (
    OddsApiEvent,
    OddsApiH2HOutcome,
    parse_odds_api_h2h_response,
)
from sportsmodel.nfl import odds_identity
from sportsmodel.nfl.odds_identity import (
    AmbiguousNflGameMatchError,
    AmbiguousNflTeamIdentityError,
    CanonicalNflGameNotFoundError,
    CanonicalNflGameStatusError,
    CanonicalNflProviderTeam,
    MalformedNflProviderKickoffError,
    NflKickoffMatchKind,
    NflProviderEventConflictError,
    NflSelectionIdentityError,
    ReversedNflMatchupError,
    SameNflTeamIdentityError,
    UnacceptableNflKickoffDriftError,
    UnknownNflTeamIdentityError,
    UnsupportedNflOddsSportError,
    resolve_nfl_odds_event,
)


ROOT = Path(__file__).parents[2]
NFL_EVENT_FIXTURE = ROOT / "tests" / "fixtures" / "odds_api" / "nfl_h2h.json"
NFL_TEAM_FIXTURE = (
    ROOT / "tests" / "fixtures" / "odds_api" / "nfl_team_identities.json"
)
KICKOFF = datetime(2026, 9, 11, 0, 20, tzinfo=timezone.utc)
HOME = CanonicalNflProviderTeam(1, "KC", "Kansas City Chiefs")
AWAY = CanonicalNflProviderTeam(2, "DEN", "Denver Broncos")


class _RowsCursor:
    def __init__(self, rows):
        self._rows = rows

    def execute(self, _query, _parameters):
        pass

    def fetchall(self):
        return self._rows


def _fixture_event() -> OddsApiEvent:
    payload = json.loads(NFL_EVENT_FIXTURE.read_text(encoding="utf-8"))
    return parse_odds_api_h2h_response(
        payload,
        expected_sport_key="americanfootball_nfl",
    )[0]


def _candidate(
    *,
    game_id: int = 100,
    kickoff: datetime = KICKOFF,
    home_team_id: int = HOME.team_id,
    away_team_id: int = AWAY.team_id,
    status: str = "unplayed",
):
    return odds_identity._CanonicalGameCandidate(
        game_id,
        kickoff,
        home_team_id,
        away_team_id,
        status,
    )


def _configure_resolution(monkeypatch, candidates, *, existing=None) -> None:
    teams = {
        HOME.provider_team_name: HOME,
        AWAY.provider_team_name: AWAY,
    }

    def load_team(_cursor, name):
        try:
            return teams[name]
        except KeyError as exc:
            raise UnknownNflTeamIdentityError(name) from exc

    monkeypatch.setattr(odds_identity, "_load_provider_team", load_team)
    monkeypatch.setattr(
        odds_identity,
        "_load_existing_mapping",
        lambda _cursor, _event: existing,
    )
    monkeypatch.setattr(
        odds_identity,
        "_load_matchup_candidates",
        lambda _cursor, _home, _away: tuple(candidates),
    )


def test_all_32_provider_team_identities_are_explicit_and_unique() -> None:
    identities = json.loads(NFL_TEAM_FIXTURE.read_text(encoding="utf-8"))

    assert len(identities) == 32
    assert len({item["abbreviation"] for item in identities}) == 32
    assert len({item["provider_team_name"] for item in identities}) == 32
    assert {item["provider_team_name"] for item in identities} >= {
        "Kansas City Chiefs",
        "Denver Broncos",
        "Washington Commanders",
    }


def test_valid_exact_match_resolves_canonical_teams_game_and_selections(
    monkeypatch,
) -> None:
    _configure_resolution(monkeypatch, [_candidate()])

    result = resolve_nfl_odds_event(object(), _fixture_event())

    assert result.game_id == 100
    assert result.canonical_home_team_id == HOME.team_id
    assert result.canonical_away_team_id == AWAY.team_id
    assert result.kickoff_drift_seconds == 0
    assert result.kickoff_match_kind is NflKickoffMatchKind.EXACT
    assert result.home_selection.team_id == HOME.team_id
    assert result.home_selection.side == "home"
    assert result.away_selection.team_id == AWAY.team_id
    assert result.away_selection.side == "away"


def test_reversed_provider_outcome_order_still_returns_fixed_canonical_sides(
    monkeypatch,
) -> None:
    _configure_resolution(monkeypatch, [_candidate()])
    event = _fixture_event()
    market = event.bookmakers[0].markets[0]
    reversed_market = replace(market, outcomes=tuple(reversed(market.outcomes)))
    event = replace(
        event,
        bookmakers=(replace(event.bookmakers[0], markets=(reversed_market,)),),
    )

    result = resolve_nfl_odds_event(object(), event)

    assert result.home_selection.provider_selection_name == event.home_team
    assert result.away_selection.provider_selection_name == event.away_team


def test_unknown_provider_team_fails_closed(monkeypatch) -> None:
    _configure_resolution(monkeypatch, [_candidate()])
    event = replace(_fixture_event(), home_team="Kansas City")

    with pytest.raises(UnknownNflTeamIdentityError):
        resolve_nfl_odds_event(object(), event)


def test_exact_team_loader_rejects_ambiguous_rows() -> None:
    cursor = _RowsCursor([(1, "KC", "Kansas City Chiefs"), (2, "DEN", "Denver")])

    with pytest.raises(AmbiguousNflTeamIdentityError):
        odds_identity._load_provider_team(cursor, "Kansas City Chiefs")


def test_reversed_home_away_matchup_fails_closed(monkeypatch) -> None:
    _configure_resolution(
        monkeypatch,
        [_candidate(home_team_id=AWAY.team_id, away_team_id=HOME.team_id)],
    )

    with pytest.raises(ReversedNflMatchupError):
        resolve_nfl_odds_event(object(), _fixture_event())


def test_same_canonical_team_fails_closed(monkeypatch) -> None:
    monkeypatch.setattr(
        odds_identity,
        "_load_provider_team",
        lambda _cursor, name: CanonicalNflProviderTeam(1, "KC", name),
    )

    with pytest.raises(SameNflTeamIdentityError):
        resolve_nfl_odds_event(object(), _fixture_event())


def test_zero_canonical_matches_fails_closed(monkeypatch) -> None:
    _configure_resolution(monkeypatch, [])

    with pytest.raises(CanonicalNflGameNotFoundError):
        resolve_nfl_odds_event(object(), _fixture_event())


def test_multiple_canonical_matches_fails_closed(monkeypatch) -> None:
    _configure_resolution(monkeypatch, [_candidate(game_id=100), _candidate(game_id=101)])

    with pytest.raises(AmbiguousNflGameMatchError):
        resolve_nfl_odds_event(object(), _fixture_event())


def test_acceptable_kickoff_drift_is_exposed(monkeypatch) -> None:
    _configure_resolution(monkeypatch, [_candidate(kickoff=KICKOFF - timedelta(minutes=15))])

    result = resolve_nfl_odds_event(object(), _fixture_event())

    assert result.kickoff_drift_seconds == 900
    assert result.kickoff_match_kind is NflKickoffMatchKind.ACCEPTABLE_DRIFT


def test_unacceptable_kickoff_drift_fails_closed(monkeypatch) -> None:
    _configure_resolution(monkeypatch, [_candidate(kickoff=KICKOFF - timedelta(minutes=16))])

    with pytest.raises(UnacceptableNflKickoffDriftError):
        resolve_nfl_odds_event(object(), _fixture_event())


def test_non_unplayed_canonical_game_fails_closed(monkeypatch) -> None:
    _configure_resolution(monkeypatch, [_candidate(status="final")])

    with pytest.raises(CanonicalNflGameStatusError):
        resolve_nfl_odds_event(object(), _fixture_event())


def test_reused_provider_event_id_with_conflicting_identity_fails_closed(
    monkeypatch,
) -> None:
    existing = odds_identity._ExistingMapping(
        50,
        100,
        HOME.team_id,
        AWAY.team_id,
        "Different Home",
        AWAY.provider_team_name,
        KICKOFF,
        KICKOFF,
        "unplayed",
        HOME.team_id,
        AWAY.team_id,
    )
    _configure_resolution(monkeypatch, [], existing=existing)

    with pytest.raises(NflProviderEventConflictError):
        resolve_nfl_odds_event(object(), _fixture_event())


def test_sport_mismatch_fails_before_identity_queries() -> None:
    event = replace(_fixture_event(), sport_key="baseball_mlb")

    with pytest.raises(UnsupportedNflOddsSportError):
        resolve_nfl_odds_event(object(), event)


@pytest.mark.parametrize("duplicate_side", ["home", "away"])
def test_duplicate_home_or_away_selection_fails_closed(monkeypatch, duplicate_side) -> None:
    _configure_resolution(monkeypatch, [_candidate()])
    event = _fixture_event()
    market = event.bookmakers[0].markets[0]
    duplicate_name = event.home_team if duplicate_side == "home" else event.away_team
    malformed_market = replace(
        market,
        outcomes=(
            OddsApiH2HOutcome(duplicate_name, -110, None),
            OddsApiH2HOutcome(duplicate_name, 100, None),
        ),
    )
    event = replace(
        event,
        bookmakers=(replace(event.bookmakers[0], markets=(malformed_market,)),),
    )

    with pytest.raises(NflSelectionIdentityError):
        resolve_nfl_odds_event(object(), event)


def test_malformed_naive_provider_kickoff_fails_closed() -> None:
    event = replace(_fixture_event(), commence_time=KICKOFF.replace(tzinfo=None))

    with pytest.raises(MalformedNflProviderKickoffError):
        resolve_nfl_odds_event(object(), event)
