from datetime import datetime, timedelta, timezone

import pytest

from sportsmodel.database.nfl_moneyline_prediction_repository import (
    list_nfl_prediction_targets,
)
from sportsmodel.nfl.models import NflSeasonType


class _Cursor:
    def __init__(self, rows) -> None:
        self.rows = rows
        self.query = None
        self.parameters = None

    def execute(self, query, parameters=None) -> None:
        self.query = query
        self.parameters = parameters

    def fetchall(self):
        return self.rows


@pytest.mark.parametrize("season_type", ["regular", "postseason"])
def test_prediction_targets_explicitly_select_supported_season_types(
    season_type,
) -> None:
    kickoff = datetime(2026, 9, 13, 20, tzinfo=timezone.utc)
    cursor = _Cursor((
        (1, 2026, season_type, 1, "Week 1", kickoff, 10, 20,
         "unplayed", None, None, None, False),
    ))

    targets = list_nfl_prediction_targets(
        cursor,
        season=2026,
        slate_start_time=kickoff - timedelta(hours=1),
        slate_end_time=kickoff + timedelta(hours=1),
        official_eligible_only=True,
    )

    assert targets[0].season_type is NflSeasonType(season_type)
    normalized_query = " ".join(cursor.query.split()).lower()
    assert "nfl.season_type in ('regular', 'postseason')" in normalized_query
    assert "preseason" not in normalized_query


def test_prediction_preview_selector_does_not_apply_official_season_type_gate() -> None:
    kickoff = datetime(2026, 8, 13, 20, tzinfo=timezone.utc)
    cursor = _Cursor((
        (1, 2026, "preseason", 1, "Preseason 1", kickoff, 10, 20,
         "unplayed", None, None, None, False),
    ))

    targets = list_nfl_prediction_targets(
        cursor,
        season=2026,
        slate_start_time=kickoff - timedelta(hours=1),
        slate_end_time=kickoff + timedelta(hours=1),
        official_eligible_only=False,
    )

    assert targets[0].season_type is NflSeasonType.PRESEASON
    normalized_query = " ".join(cursor.query.split()).lower()
    assert "nfl.season_type in" not in normalized_query
