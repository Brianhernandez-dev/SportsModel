from datetime import datetime, timezone

import pytest

from sportsmodel.database.team_statistics_repository import (
    TeamStatisticsRepository,
)


def test_repository_is_abstract() -> None:
    with pytest.raises(TypeError):
        TeamStatisticsRepository()


class ExampleRepository(TeamStatisticsRepository):
    def get_completed_games_before(
        self,
        *,
        team_id: int,
        cutoff_time: datetime,
        limit: int,
    ):
        return ()


def test_repository_contract() -> None:
    repository = ExampleRepository()

    games = repository.get_completed_games_before(
        team_id=1,
        cutoff_time=datetime.now(timezone.utc),
        limit=5,
    )

    assert games == ()