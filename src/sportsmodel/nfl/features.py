from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sportsmodel.database.nfl_team_game_statistics_repository import (
    NflTeamHistoryRepository,
    PostgresNflTeamHistoryRepository,
)
from sportsmodel.nfl.models import NflGame, NflTeamGameStatistics


NFL_MONEYLINE_FEATURE_SCHEMA_VERSION = "nfl_moneyline_0.1.0"


@dataclass(frozen=True)
class HistoricalNflTeamGame:
    game: NflGame
    team_statistics: NflTeamGameStatistics

    def __post_init__(self) -> None:
        if self.team_statistics.game_id != self.game.game_id:
            raise ValueError("historical NFL statistics must match the canonical game")
        if self.team_statistics.team_id not in {
            self.game.home_team_id,
            self.game.away_team_id,
        }:
            raise ValueError(
                "historical NFL statistics team must be a canonical game participant"
            )

    @property
    def points_for(self) -> int:
        score = (self.game.home_score if self.team_statistics.team_id == self.game.home_team_id
                 else self.game.away_score)
        assert score is not None
        return score

    @property
    def points_against(self) -> int:
        score = (self.game.away_score if self.team_statistics.team_id == self.game.home_team_id
                 else self.game.home_score)
        assert score is not None
        return score


class NFLFeatureDataProvider:
    """Point-in-time access to completed NFL history for one target game."""

    def __init__(self, target_game: NflGame, *, repository: NflTeamHistoryRepository | None = None):
        self.target_game = target_game
        self.feature_cutoff = target_game.scheduled_start_time
        self._repository = repository or PostgresNflTeamHistoryRepository()
        self._cache: dict[tuple[int, int | None, int | None], tuple[HistoricalNflTeamGame, ...]] = {}

    def get_team_history(
        self, *, team_id: int, season: int | None = None, limit: int | None = None,
    ) -> tuple[HistoricalNflTeamGame, ...]:
        key = (team_id, season, limit)
        if key not in self._cache:
            history = self._repository.get_completed_games_before(
                team_id=team_id, cutoff_time=self.feature_cutoff,
                season=season, limit=limit,
            )
            if any(item.game.scheduled_start_time >= self.feature_cutoff for item in history):
                raise ValueError("NFL history repository returned a game at or after the feature cutoff")
            self._cache[key] = history
        return self._cache[key]


@dataclass(frozen=True)
class NFLTeamFeatureVector:
    team_id: int
    feature_cutoff: datetime
    prior_games_used: int
    win_percentage: float | None
    average_points_for: float | None
    average_points_against: float | None


class NFLTeamFeatureBuilder:
    def __init__(self, *, rolling_game_limit: int | None = None):
        if rolling_game_limit is not None and rolling_game_limit <= 0:
            raise ValueError("rolling_game_limit must be positive")
        self.rolling_game_limit = rolling_game_limit

    def build(self, *, team_id: int, target_game: NflGame, provider: NFLFeatureDataProvider) -> NFLTeamFeatureVector:
        games = provider.get_team_history(
            team_id=team_id, season=target_game.season, limit=self.rolling_game_limit,
        )
        count = len(games)
        wins = sum(game.points_for > game.points_against for game in games)
        ties = sum(game.points_for == game.points_against for game in games)
        return NFLTeamFeatureVector(
            team_id=team_id, feature_cutoff=provider.feature_cutoff,
            prior_games_used=count,
            win_percentage=(wins + 0.5 * ties) / count if count else None,
            average_points_for=sum(g.points_for for g in games) / count if count else None,
            average_points_against=sum(g.points_against for g in games) / count if count else None,
        )


@dataclass(frozen=True)
class NFLGameFeatureVector:
    target_game_id: int
    target_kickoff: datetime
    home_team_id: int
    away_team_id: int
    feature_cutoff: datetime
    feature_schema_version: str
    home: NFLTeamFeatureVector
    away: NFLTeamFeatureVector


class NFLGameFeatureVectorBuilder:
    def __init__(self, *, team_builder: NFLTeamFeatureBuilder | None = None):
        self.team_builder = team_builder or NFLTeamFeatureBuilder()

    def build(self, target_game: NflGame, *, provider: NFLFeatureDataProvider | None = None) -> NFLGameFeatureVector:
        provider = provider or NFLFeatureDataProvider(target_game)
        if provider.target_game != target_game:
            raise ValueError("NFL feature provider target must match the target game")
        home = self.team_builder.build(team_id=target_game.home_team_id, target_game=target_game, provider=provider)
        away = self.team_builder.build(team_id=target_game.away_team_id, target_game=target_game, provider=provider)
        return NFLGameFeatureVector(
            target_game_id=target_game.game_id,
            target_kickoff=target_game.scheduled_start_time,
            home_team_id=target_game.home_team_id, away_team_id=target_game.away_team_id,
            feature_cutoff=provider.feature_cutoff,
            feature_schema_version=NFL_MONEYLINE_FEATURE_SCHEMA_VERSION,
            home=home, away=away,
        )
