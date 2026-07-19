from abc import ABC, abstractmethod
from datetime import datetime

from sportsmodel.models.historical_team_game import (
    HistoricalTeamGame,
)


class TeamStatisticsRepository(ABC):
    """
    Read-only repository for historical team statistics.

    All methods must return point-in-time data only. Callers are
    responsible for supplying the appropriate cutoff timestamp.
    """

    @abstractmethod
    def get_completed_games_before(
        self,
        *,
        team_id: int,
        cutoff_time: datetime,
        limit: int,
    ) -> tuple[HistoricalTeamGame, ...]:
        """
        Return completed games for the specified team that occurred
        before the supplied cutoff time.

        Games are returned newest first.
        """