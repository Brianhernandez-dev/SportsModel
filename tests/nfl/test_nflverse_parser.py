import json
from copy import deepcopy
from datetime import timezone
from pathlib import Path

import pytest

from sportsmodel.nfl.models import (
    NflGameStatus,
    NflSeasonType,
)
from sportsmodel.nfl.nflverse_parser import (
    build_nflverse_team_identity_index,
    parse_nflverse_game_records,
    parse_nflverse_team_game_statistics_records,
    parse_nflverse_team_records,
)


FIXTURE_PATH = (
    Path(__file__).parents[1]
    / "fixtures"
    / "nflverse"
    / "phase_1_source_rows.json"
)


@pytest.fixture(scope="module")
def fixture_data():
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def teams(fixture_data):
    return parse_nflverse_team_records(fixture_data["teams"])


@pytest.fixture(scope="module")
def team_identities(teams):
    return build_nflverse_team_identity_index(teams)


def _case(fixture_data, name):
    return next(
        item["row"]
        for item in fixture_data["schedule_cases"]
        if item["case"] == name
    )


def _parse_case(fixture_data, team_identities, name):
    return parse_nflverse_game_records(
        [_case(fixture_data, name)],
        team_identities=team_identities,
    )[0]


def test_parses_regular_season_final(fixture_data, team_identities) -> None:
    game = _parse_case(
        fixture_data,
        team_identities,
        "regular_season_final",
    )

    assert game.external_game_id == "2023_01_DET_KC"
    assert game.season_type is NflSeasonType.REGULAR
    assert game.week == 1
    assert game.week_label == "Regular Season"
    assert game.home_external_team_id == "2310"
    assert game.away_external_team_id == "1540"
    assert game.status is NflGameStatus.FINAL
    assert game.home_score == 20
    assert game.away_score == 21
    assert game.overtime is False
    assert game.neutral_site is False


def test_parses_postseason_overtime_neutral_final(
    fixture_data,
    team_identities,
) -> None:
    game = _parse_case(
        fixture_data,
        team_identities,
        "postseason_overtime_neutral_final",
    )

    assert game.season_type is NflSeasonType.POSTSEASON
    assert game.week_label == "Super Bowl"
    assert game.overtime is True
    assert game.neutral_site is True


def test_parses_regular_season_overtime_tie(
    fixture_data,
    team_identities,
) -> None:
    game = _parse_case(
        fixture_data,
        team_identities,
        "regular_season_overtime_tie",
    )

    assert game.home_score == game.away_score == 20
    assert game.overtime is True
    assert game.status is NflGameStatus.FINAL


def test_parses_neutral_site(fixture_data, team_identities) -> None:
    game = _parse_case(
        fixture_data,
        team_identities,
        "neutral_site_regular_final",
    )

    assert game.neutral_site is True
    assert game.season_type is NflSeasonType.REGULAR


def test_unplayed_row_has_no_result_fields(
    fixture_data,
    team_identities,
) -> None:
    game = _parse_case(
        fixture_data,
        team_identities,
        "scheduled_unplayed",
    )

    assert game.status is NflGameStatus.UNPLAYED
    assert game.home_score is None
    assert game.away_score is None
    assert game.overtime is None


def test_schedule_time_is_timezone_aware_and_dst_correct(
    fixture_data,
    team_identities,
) -> None:
    game = _parse_case(
        fixture_data,
        team_identities,
        "regular_season_final",
    )

    assert game.scheduled_start_time.tzinfo is not None
    assert game.scheduled_start_time.isoformat() == (
        "2023-09-07T20:20:00-04:00"
    )
    assert game.scheduled_start_time.astimezone(timezone.utc).isoformat() == (
        "2023-09-08T00:20:00+00:00"
    )

    winter_game = _parse_case(
        fixture_data,
        team_identities,
        "rescheduled_final_without_source_marker",
    )
    assert winter_game.scheduled_start_time.isoformat() == (
        "2020-12-02T15:40:00-05:00"
    )


def test_parsing_is_deterministic(fixture_data, team_identities) -> None:
    rows = [item["row"] for item in fixture_data["schedule_cases"]]

    first = parse_nflverse_game_records(
        rows,
        team_identities=team_identities,
    )
    second = parse_nflverse_game_records(
        reversed(rows),
        team_identities=team_identities,
    )

    assert first == second


def test_rejects_malformed_required_identity(
    fixture_data,
    team_identities,
) -> None:
    row = deepcopy(_case(fixture_data, "regular_season_final"))
    row["game_id"] = ""

    with pytest.raises(ValueError, match="game_id is required"):
        parse_nflverse_game_records(
            [row],
            team_identities=team_identities,
        )


def test_rejects_unknown_team_without_inference(
    fixture_data,
    team_identities,
) -> None:
    row = deepcopy(_case(fixture_data, "regular_season_final"))
    row["away_team"] = "UNKNOWN"

    with pytest.raises(ValueError, match="Unknown nflverse team"):
        parse_nflverse_game_records(
            [row],
            team_identities=team_identities,
        )


def test_rejects_partial_score(fixture_data, team_identities) -> None:
    row = deepcopy(_case(fixture_data, "regular_season_final"))
    row["away_score"] = None

    with pytest.raises(ValueError, match="must both be present or absent"):
        parse_nflverse_game_records(
            [row],
            team_identities=team_identities,
        )


def test_franchise_aliases_preserve_provider_identity(teams) -> None:
    by_abbreviation = {team.abbreviation: team for team in teams}

    assert by_abbreviation["OAK"].display_name == "Oakland Raiders"
    assert by_abbreviation["LV"].display_name == "Las Vegas Raiders"
    assert (
        by_abbreviation["OAK"].external_team_id
        == by_abbreviation["LV"].external_team_id
        == "2520"
    )


def test_parses_stable_team_game_statistics(
    fixture_data,
    team_identities,
) -> None:
    records = parse_nflverse_team_game_statistics_records(
        fixture_data["team_stats"],
        team_identities=team_identities,
    )

    assert len(records) == 2
    dallas = next(
        record for record in records if record.team_external_id == "1200"
    )
    assert dallas.external_game_id == "2025_01_DAL_PHI"
    assert dallas.opponent_external_id == "3700"
    assert dallas.pass_attempts == 34
    assert dallas.passing_yards == 188
    assert dallas.rushing_yards == 119
    assert dallas.fumbles_lost == 1
    assert dallas.penalty_yards == 42
