from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sportsmodel.database.nfl_team_game_statistics_repository import (
    NflTeamHistoryRepository,
    PostgresNflTeamHistoryRepository,
)
from sportsmodel.nfl.models import NflGame, NflTeamGameStatistics


NFL_MONEYLINE_FEATURE_SCHEMA_VERSION = "nfl_moneyline_0.2.0"


@dataclass(frozen=True)
class HistoricalNflTeamGame:
    game: NflGame
    team_statistics: NflTeamGameStatistics
    opponent_statistics: NflTeamGameStatistics

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
        if self.opponent_statistics.game_id != self.game.game_id:
            raise ValueError("historical NFL opponent statistics must match the canonical game")
        expected_opponent_id = (
            self.game.away_team_id
            if self.team_statistics.team_id == self.game.home_team_id
            else self.game.home_team_id
        )
        if self.opponent_statistics.team_id != expected_opponent_id:
            raise ValueError(
                "historical NFL opponent statistics must represent the canonical opponent"
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

    @property
    def turnovers(self) -> int:
        return (
            self.team_statistics.passing_interceptions
            + self.team_statistics.fumbles_lost
        )

    @property
    def takeaways(self) -> int:
        return (
            self.opponent_statistics.passing_interceptions
            + self.opponent_statistics.fumbles_lost
        )


@dataclass(frozen=True)
class NFLRollingTeamFeatures:
    games_used: int
    average_points_for: float | None
    average_points_against: float | None
    average_point_differential: float | None
    average_turnover_differential: float | None


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
    average_point_differential: float | None
    average_passing_yards: float | None
    average_passing_yards_allowed: float | None
    average_rushing_yards: float | None
    average_rushing_yards_allowed: float | None
    average_turnovers: float | None
    average_takeaways: float | None
    average_turnover_differential: float | None
    rolling_3: NFLRollingTeamFeatures
    rolling_5: NFLRollingTeamFeatures


class NFLTeamFeatureBuilder:
    def build(self, *, team_id: int, target_game: NflGame, provider: NFLFeatureDataProvider) -> NFLTeamFeatureVector:
        games = provider.get_team_history(
            team_id=team_id,
            season=target_game.season,
        )
        count = len(games)
        wins = sum(game.points_for > game.points_against for game in games)
        ties = sum(game.points_for == game.points_against for game in games)
        season = _aggregate_team_games(games)
        return NFLTeamFeatureVector(
            team_id=team_id, feature_cutoff=provider.feature_cutoff,
            prior_games_used=count,
            win_percentage=(wins + 0.5 * ties) / count if count else None,
            average_points_for=season.average_points_for,
            average_points_against=season.average_points_against,
            average_point_differential=season.average_point_differential,
            average_passing_yards=_average(
                [game.team_statistics.passing_yards for game in games]
            ),
            average_passing_yards_allowed=_average(
                [game.opponent_statistics.passing_yards for game in games]
            ),
            average_rushing_yards=_average(
                [game.team_statistics.rushing_yards for game in games]
            ),
            average_rushing_yards_allowed=_average(
                [game.opponent_statistics.rushing_yards for game in games]
            ),
            average_turnovers=_average([game.turnovers for game in games]),
            average_takeaways=_average([game.takeaways for game in games]),
            average_turnover_differential=season.average_turnover_differential,
            rolling_3=_aggregate_team_games(games[:3]),
            rolling_5=_aggregate_team_games(games[:5]),
        )


def _aggregate_team_games(
    games: tuple[HistoricalNflTeamGame, ...],
) -> NFLRollingTeamFeatures:
    return NFLRollingTeamFeatures(
        games_used=len(games),
        average_points_for=_average([game.points_for for game in games]),
        average_points_against=_average([game.points_against for game in games]),
        average_point_differential=_average(
            [game.points_for - game.points_against for game in games]
        ),
        average_turnover_differential=_average(
            [game.takeaways - game.turnovers for game in games]
        ),
    )


def _average(values: list[int]) -> float | None:
    return sum(values) / len(values) if values else None


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
