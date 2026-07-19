from __future__ import annotations

from typing import Any

from sportsmodel.models.parsed_boxscore import ParsedBoxScore
from sportsmodel.models.team_game_statistics import TeamGameStatistics


def parse_team_statistics(
    boxscore: dict[str, Any],
    *,
    game_id: int,
    team_ids_by_mlb_id: dict[int, int],
) -> tuple[TeamGameStatistics, ...]:
    """
    Parse team batting and pitching statistics.
    """

    parsed_teams: list[TeamGameStatistics] = []

    for side in ("away", "home"):
        team_data = boxscore["teams"][side]

        mlb_team_id = int(team_data["team"]["id"])
        team_id = team_ids_by_mlb_id[mlb_team_id]

        batting = team_data["teamStats"]["batting"]
        pitching = team_data["teamStats"]["pitching"]
        fielding = team_data["teamStats"]["fielding"]

        parsed_teams.append(
            TeamGameStatistics(
                game_id=game_id,
                team_id=team_id,
                is_home=side == "home",
                runs=batting["runs"],
                hits=batting["hits"],
                errors=fielding["errors"],
                at_bats=batting["atBats"],
                plate_appearances=batting.get("plateAppearances"),
                doubles=batting["doubles"],
                triples=batting["triples"],
                home_runs=batting["homeRuns"],
                walks=batting["baseOnBalls"],
                intentional_walks=batting["intentionalWalks"],
                strikeouts=batting["strikeOuts"],
                hit_by_pitch=batting["hitByPitch"],
                sacrifice_flies=batting["sacFlies"],
                stolen_bases=batting["stolenBases"],
                caught_stealing=batting["caughtStealing"],
                pitching_outs=pitching["outs"],
                runs_allowed=pitching["runs"],
                earned_runs_allowed=pitching["earnedRuns"],
                hits_allowed=pitching["hits"],
                home_runs_allowed=pitching["homeRuns"],
                walks_allowed=pitching["baseOnBalls"],
                strikeouts_recorded=pitching["strikeOuts"],
                left_on_base=batting.get("leftOnBase"),
                double_plays=batting.get("groundIntoDoublePlay"),
                source_name="mlb_stats_api",
            )
        )

    return tuple(parsed_teams)


def parse_pitcher_statistics(
    boxscore: dict[str, Any],
) -> tuple:
    """
    Parse individual pitcher statistics.
    """

    raise NotImplementedError


def parse_game_metadata(
    live_feed: dict[str, Any],
) -> tuple[int, bool]:
    """
    Parse game metadata from the live feed.
    """

    game = live_feed["gameData"]["game"]

    game_number = int(game["gameNumber"])

    double_header = game["doubleHeader"] == "Y"

    return (
        game_number,
        double_header,
    )


def parse_boxscore(
    boxscore: dict[str, Any],
    live_feed: dict[str, Any],
) -> ParsedBoxScore:
    """
    Parse MLB API responses into immutable SportsModel models.
    """

    raise NotImplementedError