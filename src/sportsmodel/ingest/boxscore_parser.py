from __future__ import annotations

from typing import Any

from sportsmodel.models.parsed_boxscore import ParsedBoxScore
from sportsmodel.models.player_game_pitching_statistics import (
    PitchingDecision,
    PlayerGamePitchingStatistics,
)
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
    *,
    game_id: int,
    team_ids_by_mlb_id: dict[int, int],
    player_ids_by_mlb_id: dict[int, int],
) -> tuple[PlayerGamePitchingStatistics, ...]:
    """
    Parse pitcher appearance statistics.

    Pitchers are processed in the appearance order supplied by MLB.
    """

    parsed_pitchers: list[PlayerGamePitchingStatistics] = []

    for side in ("away", "home"):
        team_data = boxscore["teams"][side]

        mlb_team_id = int(team_data["team"]["id"])
        team_id = team_ids_by_mlb_id[mlb_team_id]

        players = team_data["players"]

        for appearance_order, mlb_player_id in enumerate(
            team_data["pitchers"],
            start=1,
        ):
            player = players[f"ID{mlb_player_id}"]
            pitching = player.get("stats", {}).get("pitching")

            if not pitching:
                continue

            baseball_player_id = player_ids_by_mlb_id[
                int(mlb_player_id)
            ]

            win_recorded = pitching.get("wins", 0) > 0
            loss_recorded = pitching.get("losses", 0) > 0
            save_recorded = pitching.get("saves", 0) > 0
            hold_recorded = pitching.get("holds", 0) > 0
            blown_save_recorded = pitching.get("blownSaves", 0) > 0

            decision: PitchingDecision | None = None

            if win_recorded:
                decision = PitchingDecision.WIN
            elif loss_recorded:
                decision = PitchingDecision.LOSS
            elif save_recorded:
                decision = PitchingDecision.SAVE
            elif hold_recorded:
                decision = PitchingDecision.HOLD
            elif blown_save_recorded:
                decision = PitchingDecision.BLOWN_SAVE

            parsed_pitchers.append(
                PlayerGamePitchingStatistics(
                    game_id=game_id,
                    team_id=team_id,
                    baseball_player_id=baseball_player_id,
                    appearance_order=appearance_order,
                    is_starter=appearance_order == 1,
                    pitching_outs=pitching["outs"],
                    batters_faced=pitching.get("battersFaced"),
                    hits_allowed=pitching["hits"],
                    runs_allowed=pitching["runs"],
                    earned_runs_allowed=pitching["earnedRuns"],
                    home_runs_allowed=pitching["homeRuns"],
                    walks_allowed=pitching["baseOnBalls"],
                    intentional_walks_allowed=pitching.get(
                        "intentionalWalks",
                        0,
                    ),
                    strikeouts=pitching["strikeOuts"],
                    hit_batters=pitching.get(
                        "hitBatsmen",
                        pitching.get("hitByPitch", 0),
                    ),
                    pitches_thrown=pitching.get(
                        "numberOfPitches",
                        pitching.get("pitchesThrown"),
                    ),
                    strikes_thrown=pitching.get("strikes"),
                    decision=decision,
                    save_recorded=save_recorded,
                    hold_recorded=hold_recorded,
                    blown_save_recorded=blown_save_recorded,
                    source_name="mlb_stats_api",
                )
            )

    return tuple(parsed_pitchers)


def parse_game_metadata(
    live_feed: dict[str, Any],
) -> tuple[int, bool]:
    """
    Parse game metadata from the live feed.
    """

    game = live_feed["gameData"]["game"]

    game_number = int(game["gameNumber"])
    double_header = game["doubleHeader"] == "Y"

    return game_number, double_header


def parse_boxscore(
    boxscore: dict[str, Any],
    live_feed: dict[str, Any],
) -> ParsedBoxScore:
    """
    Parse MLB API responses into immutable SportsModel models.
    """

    raise NotImplementedError