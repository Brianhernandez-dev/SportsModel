from datetime import datetime, timezone

import pytest

from sportsmodel.nfl.models import (
    NflGameSourceRecord,
    NflGameStatus,
    NflSeasonType,
)


def test_postseason_tie_is_invalid_but_regular_tie_is_valid() -> None:
    values = dict(
        source_name="nflverse",
        external_game_id="example",
        season=2025,
        week=22,
        week_label="Super Bowl",
        scheduled_start_time=datetime(2026, 2, 1, tzinfo=timezone.utc),
        home_external_team_id="1",
        away_external_team_id="2",
        status=NflGameStatus.FINAL,
        home_score=20,
        away_score=20,
        overtime=True,
        neutral_site=True,
    )
    regular = NflGameSourceRecord(
        **values, season_type=NflSeasonType.REGULAR
    )
    assert regular.home_score == regular.away_score
    with pytest.raises(ValueError, match="postseason games cannot end in a tie"):
        NflGameSourceRecord(
            **values, season_type=NflSeasonType.POSTSEASON
        )
