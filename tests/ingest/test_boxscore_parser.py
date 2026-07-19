from sportsmodel.ingest.boxscore_parser import (
    parse_game_metadata,
    parse_team_statistics,
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