from sportsmodel.database.completed_game_repository import (
    GET_COMPLETED_GAMES_QUERY,
)


def test_completed_game_query_requires_complete_boxscore_data() -> None:
    assert (
        "FROM team_game_statistics AS team_stats"
        in GET_COMPLETED_GAMES_QUERY
    )

    assert (
        "team_stats.game_id = g.game_id"
        in GET_COMPLETED_GAMES_QUERY
    )

    assert (
        "FROM player_game_pitching_statistics AS starter_stats"
        in GET_COMPLETED_GAMES_QUERY
    )

    assert (
        "starter_stats.is_starter IS TRUE"
        in GET_COMPLETED_GAMES_QUERY
    )

    assert GET_COMPLETED_GAMES_QUERY.count(
        ") = 2"
    ) >= 2
