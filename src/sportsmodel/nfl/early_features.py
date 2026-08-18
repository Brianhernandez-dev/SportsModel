from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from sportsmodel.nfl.features import (
    HistoricalNflTeamGame,
    NFLFeatureDataProvider,
)
from sportsmodel.nfl.models import NflGame, NflSeasonType


NFL_EARLY_MONEYLINE_FEATURE_SCHEMA_VERSION = "nfl_moneyline_early_0.1.0"
NFL_EARLY_ROUTE_CURRENT_GAME_THRESHOLD = 3

NFL_EARLY_MONEYLINE_FEATURE_NAMES = (
    "prior_season_games_played_difference",
    "prior_season_win_percentage_difference",
    "prior_season_average_point_differential_difference",
    "prior_season_average_turnover_differential_difference",
    "current_season_prior_games_played_difference",
    "current_season_win_percentage_difference",
    "current_season_average_points_for_difference",
    "current_season_average_points_against_difference",
    "current_season_average_turnover_differential_difference",
    "minimum_current_season_prior_games",
    "neutral_site",
)


class NFLMoneylineRoute(StrEnum):
    EARLY = "early"
    MATURE = "mature"


def select_nfl_moneyline_route(
    home_current_prior_games: int,
    away_current_prior_games: int,
) -> NFLMoneylineRoute:
    if home_current_prior_games < 0 or away_current_prior_games < 0:
        raise ValueError("current-season prior-game counts cannot be negative")
    if (
        home_current_prior_games >= NFL_EARLY_ROUTE_CURRENT_GAME_THRESHOLD
        and away_current_prior_games >= NFL_EARLY_ROUTE_CURRENT_GAME_THRESHOLD
    ):
        return NFLMoneylineRoute.MATURE
    return NFLMoneylineRoute.EARLY


@dataclass(frozen=True)
class NFLEarlyTeamChannel:
    games_played: int
    win_percentage: float | None
    average_points_for: float | None
    average_points_against: float | None
    average_point_differential: float | None
    average_turnover_differential: float | None
    source_game_ids: tuple[int, ...]
    source_kickoffs: tuple[datetime, ...]

    @property
    def available(self) -> bool:
        return self.games_played > 0


@dataclass(frozen=True)
class NFLEarlyTeamFeatureVector:
    team_id: int
    feature_cutoff: datetime
    prior_season: NFLEarlyTeamChannel
    current_season: NFLEarlyTeamChannel


@dataclass(frozen=True)
class NFLEarlyGameFeatureVector:
    target_game_id: int
    target_kickoff: datetime
    target_season: int
    target_season_type: NflSeasonType
    home_team_id: int
    away_team_id: int
    feature_cutoff: datetime
    feature_schema_version: str
    home: NFLEarlyTeamFeatureVector
    away: NFLEarlyTeamFeatureVector
    minimum_current_prior_games: int
    neutral_site: bool
    route: NFLMoneylineRoute
    feature_names: tuple[str, ...]
    feature_values: tuple[float | int | None, ...]


class NFLEarlyTeamFeatureBuilder:
    """Build separate prior-regular and current-season PIT channels."""

    def build(
        self,
        *,
        team_id: int,
        target_game: NflGame,
        provider: NFLFeatureDataProvider,
    ) -> NFLEarlyTeamFeatureVector:
        prior_complete = provider.get_team_history(
            team_id=team_id,
            season=target_game.season - 1,
        )
        prior_regular = tuple(
            item
            for item in prior_complete
            if item.game.season_type is NflSeasonType.REGULAR
        )
        current = provider.get_team_history(
            team_id=team_id,
            season=target_game.season,
        )
        return NFLEarlyTeamFeatureVector(
            team_id=team_id,
            feature_cutoff=provider.feature_cutoff,
            prior_season=_aggregate_channel(prior_regular),
            current_season=_aggregate_channel(current),
        )


class NFLEarlyGameFeatureVectorBuilder:
    def __init__(
        self,
        *,
        team_builder: NFLEarlyTeamFeatureBuilder | None = None,
    ) -> None:
        self.team_builder = team_builder or NFLEarlyTeamFeatureBuilder()

    def build(
        self,
        target_game: NflGame,
        *,
        provider: NFLFeatureDataProvider | None = None,
    ) -> NFLEarlyGameFeatureVector:
        provider = provider or NFLFeatureDataProvider(target_game)
        if provider.target_game != target_game:
            raise ValueError("NFL feature provider target must match the target game")
        home = self.team_builder.build(
            team_id=target_game.home_team_id,
            target_game=target_game,
            provider=provider,
        )
        away = self.team_builder.build(
            team_id=target_game.away_team_id,
            target_game=target_game,
            provider=provider,
        )
        minimum = min(
            home.current_season.games_played,
            away.current_season.games_played,
        )
        route = select_nfl_moneyline_route(
            home.current_season.games_played,
            away.current_season.games_played,
        )
        values: tuple[float | int | None, ...] = (
            home.prior_season.games_played - away.prior_season.games_played,
            _difference(
                home.prior_season.win_percentage,
                away.prior_season.win_percentage,
            ),
            _difference(
                home.prior_season.average_point_differential,
                away.prior_season.average_point_differential,
            ),
            _difference(
                home.prior_season.average_turnover_differential,
                away.prior_season.average_turnover_differential,
            ),
            home.current_season.games_played - away.current_season.games_played,
            _difference(
                home.current_season.win_percentage,
                away.current_season.win_percentage,
            ),
            _difference(
                home.current_season.average_points_for,
                away.current_season.average_points_for,
            ),
            _difference(
                home.current_season.average_points_against,
                away.current_season.average_points_against,
            ),
            _difference(
                home.current_season.average_turnover_differential,
                away.current_season.average_turnover_differential,
            ),
            minimum,
            int(target_game.neutral_site),
        )
        return NFLEarlyGameFeatureVector(
            target_game_id=target_game.game_id,
            target_kickoff=target_game.scheduled_start_time,
            target_season=target_game.season,
            target_season_type=target_game.season_type,
            home_team_id=target_game.home_team_id,
            away_team_id=target_game.away_team_id,
            feature_cutoff=provider.feature_cutoff,
            feature_schema_version=NFLEarlyFeatureSchema.VERSION,
            home=home,
            away=away,
            minimum_current_prior_games=minimum,
            neutral_site=target_game.neutral_site,
            route=route,
            feature_names=NFL_EARLY_MONEYLINE_FEATURE_NAMES,
            feature_values=values,
        )


class NFLEarlyFeatureSchema:
    VERSION = NFL_EARLY_MONEYLINE_FEATURE_SCHEMA_VERSION
    NAMES = NFL_EARLY_MONEYLINE_FEATURE_NAMES


def _aggregate_channel(
    games: tuple[HistoricalNflTeamGame, ...],
) -> NFLEarlyTeamChannel:
    count = len(games)
    wins = sum(item.points_for > item.points_against for item in games)
    ties = sum(item.points_for == item.points_against for item in games)
    return NFLEarlyTeamChannel(
        games_played=count,
        win_percentage=(wins + 0.5 * ties) / count if count else None,
        average_points_for=_average([item.points_for for item in games]),
        average_points_against=_average([item.points_against for item in games]),
        average_point_differential=_average(
            [item.points_for - item.points_against for item in games]
        ),
        average_turnover_differential=_average(
            [item.takeaways - item.turnovers for item in games]
        ),
        source_game_ids=tuple(item.game.game_id for item in games),
        source_kickoffs=tuple(item.game.scheduled_start_time for item in games),
    )


def _average(values: list[int]) -> float | None:
    return sum(values) / len(values) if values else None


def _difference(left: float | None, right: float | None) -> float | None:
    if left is None or right is None:
        return None
    return left - right
