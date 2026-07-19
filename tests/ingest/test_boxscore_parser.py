import sportsmodel.ingest.boxscore_parser as boxscore_parser

from sportsmodel.ingest.boxscore_parser import (
    parse_game_metadata,
    parse_pitcher_statistics,
    parse_team_statistics,
)
from sportsmodel.models.player_game_pitching_statistics import (
    PitchingDecision,
)


def test_parse_game_metadata() -> None:
    live_feed = {
        "gameData": {
            "game": {
                "gameNumber": 2,
                "doubleHeader": "Y",
            }
        }
    }

    game_number, double_header = parse_game_metadata(live_feed)

    assert game_number == 2
    assert double_header is True


def test_parse_team_statistics() -> None:
    boxscore = {
        "teams": {
            "away": {
                "team": {"id": 1},
                "teamStats": {
                    "batting": {
                        "runs": 5,
                        "hits": 9,
                        "atBats": 34,
                        "plateAppearances": 38,
                        "doubles": 2,
                        "triples": 1,
                        "homeRuns": 1,
                        "baseOnBalls": 3,
                        "intentionalWalks": 0,
                        "strikeOuts": 8,
                        "hitByPitch": 1,
                        "sacFlies": 0,
                        "stolenBases": 2,
                        "caughtStealing": 1,
                        "leftOnBase": 7,
                        "groundIntoDoublePlay": 1,
                    },
                    "pitching": {
                        "outs": 27,
                        "runs": 3,
                        "earnedRuns": 3,
                        "hits": 7,
                        "homeRuns": 1,
                        "baseOnBalls": 2,
                        "strikeOuts": 10,
                    },
                    "fielding": {
                        "errors": 1,
                    },
                },
            },
            "home": {
                "team": {"id": 2},
                "teamStats": {
                    "batting": {
                        "runs": 3,
                        "hits": 7,
                        "atBats": 32,
                        "plateAppearances": 35,
                        "doubles": 1,
                        "triples": 0,
                        "homeRuns": 1,
                        "baseOnBalls": 2,
                        "intentionalWalks": 1,
                        "strikeOuts": 10,
                        "hitByPitch": 0,
                        "sacFlies": 1,
                        "stolenBases": 0,
                        "caughtStealing": 0,
                        "leftOnBase": 5,
                        "groundIntoDoublePlay": 2,
                    },
                    "pitching": {
                        "outs": 27,
                        "runs": 5,
                        "earnedRuns": 4,
                        "hits": 9,
                        "homeRuns": 1,
                        "baseOnBalls": 3,
                        "strikeOuts": 8,
                    },
                    "fielding": {
                        "errors": 0,
                    },
                },
            },
        }
    }

    result = parse_team_statistics(
        boxscore,
        game_id=10,
        team_ids_by_mlb_id={
            1: 101,
            2: 102,
        },
    )

    assert len(result) == 2

    away_team, home_team = result

    assert away_team.game_id == 10
    assert away_team.team_id == 101
    assert away_team.is_home is False
    assert away_team.runs == 5
    assert away_team.hits == 9
    assert away_team.errors == 1
    assert away_team.at_bats == 34
    assert away_team.plate_appearances == 38
    assert away_team.doubles == 2
    assert away_team.triples == 1
    assert away_team.home_runs == 1
    assert away_team.walks == 3
    assert away_team.intentional_walks == 0
    assert away_team.strikeouts == 8
    assert away_team.hit_by_pitch == 1
    assert away_team.sacrifice_flies == 0
    assert away_team.stolen_bases == 2
    assert away_team.caught_stealing == 1
    assert away_team.pitching_outs == 27
    assert away_team.runs_allowed == 3
    assert away_team.earned_runs_allowed == 3
    assert away_team.hits_allowed == 7
    assert away_team.home_runs_allowed == 1
    assert away_team.walks_allowed == 2
    assert away_team.strikeouts_recorded == 10
    assert away_team.left_on_base == 7
    assert away_team.double_plays == 1
    assert away_team.source_name == "mlb_stats_api"

    assert home_team.game_id == 10
    assert home_team.team_id == 102
    assert home_team.is_home is True
    assert home_team.runs == 3
    assert home_team.hits == 7
    assert home_team.errors == 0
    assert home_team.pitching_outs == 27
    assert home_team.runs_allowed == 5
    assert home_team.earned_runs_allowed == 4
    assert home_team.source_name == "mlb_stats_api"


def test_parse_pitcher_statistics() -> None:
    boxscore = {
        "teams": {
            "away": {
                "team": {"id": 1},
                "pitchers": [100, 101],
                "players": {
                    "ID100": {
                        "person": {
                            "id": 100,
                            "fullName": "Away Starter",
                        },
                        "stats": {
                            "pitching": {
                                "outs": 15,
                                "battersFaced": 22,
                                "hits": 7,
                                "runs": 2,
                                "earnedRuns": 2,
                                "homeRuns": 1,
                                "baseOnBalls": 2,
                                "intentionalWalks": 0,
                                "strikeOuts": 6,
                                "hitBatsmen": 1,
                                "numberOfPitches": 88,
                                "strikes": 51,
                                "wins": 1,
                                "losses": 0,
                                "saves": 0,
                                "holds": 0,
                                "blownSaves": 0,
                            }
                        },
                    },
                    "ID101": {
                        "person": {
                            "id": 101,
                            "fullName": "Away Reliever",
                        },
                        "stats": {
                            "pitching": {
                                "outs": 12,
                                "battersFaced": 13,
                                "hits": 1,
                                "runs": 0,
                                "earnedRuns": 0,
                                "homeRuns": 0,
                                "baseOnBalls": 0,
                                "intentionalWalks": 0,
                                "strikeOuts": 4,
                                "hitBatsmen": 0,
                                "numberOfPitches": 42,
                                "strikes": 29,
                                "wins": 0,
                                "losses": 0,
                                "saves": 0,
                                "holds": 1,
                                "blownSaves": 0,
                            }
                        },
                    },
                },
            },
            "home": {
                "team": {"id": 2},
                "pitchers": [200],
                "players": {
                    "ID200": {
                        "person": {
                            "id": 200,
                            "fullName": "Home Starter",
                        },
                        "stats": {
                            "pitching": {
                                "outs": 27,
                                "battersFaced": 38,
                                "hits": 9,
                                "runs": 5,
                                "earnedRuns": 4,
                                "homeRuns": 1,
                                "baseOnBalls": 3,
                                "intentionalWalks": 1,
                                "strikeOuts": 8,
                                "hitBatsmen": 0,
                                "numberOfPitches": 105,
                                "strikes": 67,
                                "wins": 0,
                                "losses": 1,
                                "saves": 0,
                                "holds": 0,
                                "blownSaves": 0,
                            }
                        },
                    },
                },
            },
        }
    }

    result = parse_pitcher_statistics(
        boxscore,
        game_id=10,
        team_ids_by_mlb_id={
            1: 101,
            2: 102,
        },
        player_ids_by_mlb_id={
            100: 1001,
            101: 1002,
            200: 2001,
        },
    )

    assert len(result) == 3

    away_starter, away_reliever, home_starter = result

    assert away_starter.game_id == 10
    assert away_starter.team_id == 101
    assert away_starter.baseball_player_id == 1001
    assert away_starter.appearance_order == 1
    assert away_starter.is_starter is True
    assert away_starter.pitching_outs == 15
    assert away_starter.batters_faced == 22
    assert away_starter.hits_allowed == 7
    assert away_starter.runs_allowed == 2
    assert away_starter.earned_runs_allowed == 2
    assert away_starter.home_runs_allowed == 1
    assert away_starter.walks_allowed == 2
    assert away_starter.intentional_walks_allowed == 0
    assert away_starter.strikeouts == 6
    assert away_starter.hit_batters == 1
    assert away_starter.pitches_thrown == 88
    assert away_starter.strikes_thrown == 51
    assert away_starter.decision == PitchingDecision.WIN
    assert away_starter.save_recorded is False
    assert away_starter.hold_recorded is False
    assert away_starter.blown_save_recorded is False
    assert away_starter.source_name == "mlb_stats_api"

    assert away_reliever.game_id == 10
    assert away_reliever.team_id == 101
    assert away_reliever.baseball_player_id == 1002
    assert away_reliever.appearance_order == 2
    assert away_reliever.is_starter is False
    assert away_reliever.pitching_outs == 12
    assert away_reliever.decision == PitchingDecision.HOLD
    assert away_reliever.save_recorded is False
    assert away_reliever.hold_recorded is True
    assert away_reliever.blown_save_recorded is False

    assert home_starter.game_id == 10
    assert home_starter.team_id == 102
    assert home_starter.baseball_player_id == 2001
    assert home_starter.appearance_order == 1
    assert home_starter.is_starter is True
    assert home_starter.pitching_outs == 27
    assert home_starter.decision == PitchingDecision.LOSS
    assert home_starter.save_recorded is False
    assert home_starter.hold_recorded is False
    assert home_starter.blown_save_recorded is False
    assert home_starter.source_name == "mlb_stats_api"


def test_parse_boxscore_orchestrates_component_parsers(
    monkeypatch,
) -> None:
    boxscore = {"boxscore": "payload"}
    live_feed = {"live_feed": "payload"}

    expected_team_statistics = (object(), object())
    expected_pitcher_statistics = (object(), object(), object())

    captured_calls: dict[str, object] = {}

    def fake_parse_game_metadata(
        received_live_feed,
    ) -> tuple[int, bool]:
        captured_calls["live_feed"] = received_live_feed
        return 2, True

    def fake_parse_team_statistics(
        received_boxscore,
        *,
        game_id: int,
        team_ids_by_mlb_id: dict[int, int],
    ):
        captured_calls["team_boxscore"] = received_boxscore
        captured_calls["team_game_id"] = game_id
        captured_calls["team_ids_by_mlb_id"] = team_ids_by_mlb_id

        return expected_team_statistics

    def fake_parse_pitcher_statistics(
        received_boxscore,
        *,
        game_id: int,
        team_ids_by_mlb_id: dict[int, int],
        player_ids_by_mlb_id: dict[int, int],
    ):
        captured_calls["pitcher_boxscore"] = received_boxscore
        captured_calls["pitcher_game_id"] = game_id
        captured_calls[
            "pitcher_team_ids_by_mlb_id"
        ] = team_ids_by_mlb_id
        captured_calls[
            "player_ids_by_mlb_id"
        ] = player_ids_by_mlb_id

        return expected_pitcher_statistics

    monkeypatch.setattr(
        boxscore_parser,
        "parse_game_metadata",
        fake_parse_game_metadata,
    )
    monkeypatch.setattr(
        boxscore_parser,
        "parse_team_statistics",
        fake_parse_team_statistics,
    )
    monkeypatch.setattr(
        boxscore_parser,
        "parse_pitcher_statistics",
        fake_parse_pitcher_statistics,
    )

    team_ids_by_mlb_id = {
        1: 101,
        2: 102,
    }
    player_ids_by_mlb_id = {
        100: 1001,
        200: 2001,
    }

    result = boxscore_parser.parse_boxscore(
        boxscore=boxscore,
        live_feed=live_feed,
        game_pk=777159,
        game_id=10,
        team_ids_by_mlb_id=team_ids_by_mlb_id,
        player_ids_by_mlb_id=player_ids_by_mlb_id,
    )

    assert result.game_pk == 777159
    assert result.game_number == 2
    assert result.double_header is True
    assert result.team_statistics is expected_team_statistics
    assert result.pitcher_statistics is expected_pitcher_statistics

    assert captured_calls["live_feed"] is live_feed
    assert captured_calls["team_boxscore"] is boxscore
    assert captured_calls["team_game_id"] == 10
    assert (
        captured_calls["team_ids_by_mlb_id"]
        is team_ids_by_mlb_id
    )

    assert captured_calls["pitcher_boxscore"] is boxscore
    assert captured_calls["pitcher_game_id"] == 10
    assert (
        captured_calls["pitcher_team_ids_by_mlb_id"]
        is team_ids_by_mlb_id
    )
    assert (
        captured_calls["player_ids_by_mlb_id"]
        is player_ids_by_mlb_id
    )