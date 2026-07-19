from sportsmodel.models.parsed_boxscore import ParsedBoxScore


def test_parsed_boxscore_creation() -> None:
    parsed = ParsedBoxScore(
        game_pk=777159,
        game_number=1,
        double_header=False,
        team_statistics=(),
        pitcher_statistics=(),
    )

    assert parsed.game_pk == 777159
    assert parsed.game_number == 1
    assert parsed.double_header is False
    assert parsed.team_statistics == ()
    assert parsed.pitcher_statistics == ()