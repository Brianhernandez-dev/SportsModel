from copy import deepcopy

import pytest

from sportsmodel.nfl.historical_backfill import (
    CANCELLED_BUF_CIN_GAME_ID,
    build_nflverse_historical_backfill_plan,
)


IDENTITIES = {
    "BUF": "buf", "CIN": "cin", "DAL": "dal", "JAX": "jax",
    "KC": "kc", "LAC": "lac", "LV": "lv", "OAK": "lv",
    "PHI": "phi", "STL": "lar", "TEN": "ten", "WAS": "was",
}


def schedule(**changes):
    row = {
        "game_id": "2023_01_DAL_PHI", "season": 2023,
        "game_type": "REG", "week": 1, "gameday": "2023-09-10",
        "gametime": "13:00", "away_team": "DAL", "away_score": 17,
        "home_team": "PHI", "home_score": 24, "location": "Home",
        "overtime": 0,
    }
    row.update(changes)
    return row


def stat(team="DAL", opponent="PHI", **changes):
    row = {
        "game_id": "2023_01_DAL_PHI", "season": 2023,
        "season_type": "REG", "week": 1, "team": team,
        "opponent_team": opponent, "completions": 20, "attempts": 30,
        "passing_yards": 200, "passing_tds": 2,
        "passing_interceptions": 1, "sacks_suffered": 2, "carries": 25,
        "rushing_yards": 110, "rushing_tds": 1, "fumbles_lost_total": 0,
        "penalties": 5, "penalty_yards": 40,
    }
    row.update(changes)
    return row


def plan(schedule_rows=None, stat_rows=None):
    return build_nflverse_historical_backfill_plan(
        [schedule()] if schedule_rows is None else schedule_rows,
        [stat(), stat("PHI", "DAL")] if stat_rows is None else stat_rows,
        team_identities=IDENTITIES,
    )


def categories(result):
    return {issue.category for issue in result.issues}


def test_valid_final_regular_game_with_two_statistics_rows():
    result = plan()
    assert result.is_valid
    assert len(result.accepted_schedule_rows) == 1
    assert len(result.accepted_team_statistics_rows) == 2


def test_schedule_selection_excludes_out_of_range_and_preseason():
    result = plan([
        schedule(), schedule(game_id="2017_01_DAL_PHI", season=2017),
        schedule(game_id="2023_00_DAL_PHI", game_type="PRE"),
    ])
    assert [row["game_id"] for row in result.selected_schedule_rows] == ["2023_01_DAL_PHI"]


def test_plan_is_deterministic_for_reversed_inputs():
    schedules = [schedule(), schedule(game_id="2024_01_KC_LV", season=2024, away_team="KC", home_team="LV")]
    stats = [
        stat(), stat("PHI", "DAL"),
        stat(game_id="2024_01_KC_LV", season=2024, team="KC", opponent_team="LV"),
        stat(game_id="2024_01_KC_LV", season=2024, team="LV", opponent_team="KC"),
    ]
    forward = plan(schedules, stats)
    reversed_plan = plan(reversed(schedules), reversed(stats))
    assert forward.is_valid
    assert reversed_plan.is_valid
    assert forward == reversed_plan


def test_parser_rejection_issue_sort_handles_missing_and_string_game_ids():
    rows = [
        schedule(game_id="", location="Somewhere"),
        schedule(game_id="2023_02_DAL_PHI", location="Somewhere"),
    ]
    forward = plan(rows, [])
    reversed_plan = plan(reversed(rows), [])
    rejection_ids = [
        issue.external_game_id
        for issue in forward.issues
        if issue.category == "schedule_parser_rejection"
    ]
    assert rejection_ids == [None, "2023_02_DAL_PHI"]
    assert forward == reversed_plan


def test_schedule_parser_rejection_preserves_reason():
    result = plan([schedule(location="Somewhere")], [])
    assert result.quarantined_schedule_rows
    issue = result.issues[0]
    assert issue.category == "schedule_parser_rejection"
    assert "Unsupported nflverse location" in issue.detail


def test_statistics_parser_rejection_preserves_reason():
    result = plan(stat_rows=[stat(attempts=-1), stat("PHI", "DAL")])
    issue = next(item for item in result.issues if item.category == "team_statistics_parser_rejection")
    assert "attempts cannot be negative" in issue.detail


def test_missing_one_statistics_row_is_reported():
    assert "one_team_statistics_row" in categories(plan(stat_rows=[stat()]))


def test_orphan_statistics_game_is_reported():
    orphan = stat(game_id="2023_02_DAL_PHI", week=2)
    assert "orphan_team_statistics" in categories(plan([], [orphan]))


def test_duplicate_team_statistics_row_is_reported():
    assert "duplicate_team_statistics_row" in categories(plan(stat_rows=[stat(), stat()]))


def test_participant_and_opponent_mismatches_are_reported():
    result = plan(stat_rows=[stat(team="KC", opponent="JAX"), stat("PHI", "KC")])
    assert {"team_participant_mismatch", "opponent_mismatch"} <= categories(result)


@pytest.mark.parametrize(
    ("change", "category"),
    [({"season": 2022}, "season_mismatch"), ({"week": 2}, "week_mismatch"),
     ({"season_type": "POST"}, "season_type_mismatch")],
)
def test_schedule_statistics_metadata_mismatch(change, category):
    assert category in categories(plan(stat_rows=[stat(**change), stat("PHI", "DAL")]))


def wembley(**changes):
    row = schedule(
        game_id="2018_08_PHI_JAX", season=2018, week=8,
        gameday="2018-10-28", gametime="21:30", away_team="PHI",
        home_team="JAX", location="Neutral",
    )
    row.update(changes)
    return row


def test_exact_wembley_reviewed_override_is_accepted():
    result = plan([wembley()], [])
    assert result.reviewed_override_game_ids == ("2018_08_PHI_JAX",)
    assert not result.quarantined_schedule_rows


def test_wembley_evidence_mismatch_is_quarantined_explicitly():
    result = plan([wembley(gametime="20:30")], [])
    assert "reviewed_override_evidence_mismatch" in categories(result)
    assert result.quarantined_schedule_rows
    assert not result.reviewed_override_game_ids


def test_cancelled_buf_cin_absence_is_proven():
    assert plan().cancelled_buf_cin_absent


@pytest.mark.parametrize("source", ["schedule", "statistics"])
def test_unexpected_cancelled_buf_cin_is_blocking(source):
    cancelled_schedule = schedule(
        game_id=CANCELLED_BUF_CIN_GAME_ID, season=2022, week=17,
        away_team="BUF", home_team="CIN",
    )
    cancelled_stat = stat(
        game_id=CANCELLED_BUF_CIN_GAME_ID, season=2022, week=17,
        team="BUF", opponent_team="CIN",
    )
    result = plan([cancelled_schedule] if source == "schedule" else [], [cancelled_stat] if source == "statistics" else [])
    assert "cancelled_game_present" in categories(result)
    assert not result.cancelled_buf_cin_absent
    assert not result.is_valid


@pytest.mark.parametrize("source", ["schedule", "statistics"])
def test_cancelled_buf_cin_is_detected_before_scope_filtering(source):
    cancelled_schedule = schedule(
        game_id=CANCELLED_BUF_CIN_GAME_ID, game_type="PRE",
        away_team="BUF", home_team="CIN",
    )
    cancelled_stat = stat(
        game_id=CANCELLED_BUF_CIN_GAME_ID, season_type="OTHER",
        team="BUF", opponent_team="CIN",
    )
    result = plan(
        [cancelled_schedule] if source == "schedule" else [],
        [cancelled_stat] if source == "statistics" else [],
    )
    assert "cancelled_game_present" in categories(result)
    assert not result.cancelled_buf_cin_absent
    assert not result.accepted_schedule_rows
    assert not result.accepted_team_statistics_rows


def test_exact_duplicate_schedule_game_id_is_blocking():
    result = plan([schedule(), schedule()])
    issue = next(
        item for item in result.issues
        if item.category == "duplicate_schedule_game_id"
    )
    assert "2 accepted schedule rows" in issue.detail
    assert len(result.accepted_schedule_rows) == 2
    assert not result.is_valid


def test_conflicting_schedule_rows_with_same_game_id_are_blocking():
    result = plan([schedule(), schedule(home_score=27)])
    assert "duplicate_schedule_game_id" in categories(result)
    assert not result.is_valid


def test_signed_yardage_and_null_penalties_are_valid():
    rows = [
        stat(passing_yards=-5, rushing_yards=-2, penalties=None, penalty_yards=None),
        stat("PHI", "DAL", passing_yards=-1, rushing_yards=-3, penalties="", penalty_yards=""),
    ]
    assert plan(stat_rows=rows).is_valid


def test_historical_aliases_resolve_via_supplied_identities():
    game = schedule(game_id="2018_01_OAK_STL", season=2018, away_team="OAK", home_team="STL")
    rows = [stat(game_id=game["game_id"], season=2018, team="OAK", opponent_team="STL"),
            stat(game_id=game["game_id"], season=2018, team="STL", opponent_team="OAK")]
    assert plan([game], rows).is_valid


def test_unplayed_schedule_with_statistics_is_reported():
    game = schedule(home_score=None, away_score=None, overtime=None)
    assert "statistics_for_unplayed_game" in categories(plan([game]))
