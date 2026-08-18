from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass

from sportsmodel.nfl.early_features import (
    NFLEarlyGameFeatureVector,
    NFLEarlyGameFeatureVectorBuilder,
    NFLMoneylineRoute,
)
from sportsmodel.nfl.features import NFLFeatureDataProvider
from sportsmodel.nfl.models import NflGame, NflGameStatus


NFL_EARLY_DEVELOPMENT_SEASON_FROM = 2019
NFL_EARLY_DEVELOPMENT_SEASON_TO = 2024


@dataclass(frozen=True)
class NFLEarlyMoneylineDatasetBuildResult:
    rows: tuple[dict[str, object], ...]
    games_received: int
    ties_skipped: int
    nonfinal_games_skipped: int
    mature_route_games_skipped: int


class NFLEarlyMoneylineTrainingDatasetBuilder:
    """Build the guarded 2019-2024 early-route Moneyline population."""

    def __init__(
        self,
        *,
        vector_builder: NFLEarlyGameFeatureVectorBuilder | None = None,
        provider_factory: Callable[[NflGame], NFLFeatureDataProvider] = (
            NFLFeatureDataProvider
        ),
        season_from: int = NFL_EARLY_DEVELOPMENT_SEASON_FROM,
        season_to: int = NFL_EARLY_DEVELOPMENT_SEASON_TO,
    ) -> None:
        if season_from < NFL_EARLY_DEVELOPMENT_SEASON_FROM:
            raise ValueError("early dataset cannot include seasons before 2019")
        if season_to > NFL_EARLY_DEVELOPMENT_SEASON_TO:
            raise ValueError("early dataset cannot access seasons after 2024")
        if season_from > season_to:
            raise ValueError("season_from cannot exceed season_to")
        self.vector_builder = vector_builder or NFLEarlyGameFeatureVectorBuilder()
        self.provider_factory = provider_factory
        self.season_from = season_from
        self.season_to = season_to

    def build(
        self,
        games: Iterable[NflGame],
    ) -> NFLEarlyMoneylineDatasetBuildResult:
        ordered_games = tuple(sorted(
            games,
            key=lambda game: (game.scheduled_start_time, game.game_id),
        ))
        for game in ordered_games:
            if not self.season_from <= game.season <= self.season_to:
                raise ValueError(
                    "early dataset target season is outside the guarded range "
                    f"{self.season_from}-{self.season_to}"
                )

        rows: list[dict[str, object]] = []
        ties = 0
        nonfinal = 0
        mature = 0
        for game in ordered_games:
            if game.status is not NflGameStatus.FINAL:
                nonfinal += 1
                continue
            assert game.home_score is not None and game.away_score is not None
            if game.home_score == game.away_score:
                ties += 1
                continue
            vector = self.vector_builder.build(
                game,
                provider=self.provider_factory(game),
            )
            if vector.route is NFLMoneylineRoute.MATURE:
                mature += 1
                continue
            rows.append(_dataset_row(game, vector))
        return NFLEarlyMoneylineDatasetBuildResult(
            rows=tuple(rows),
            games_received=len(ordered_games),
            ties_skipped=ties,
            nonfinal_games_skipped=nonfinal,
            mature_route_games_skipped=mature,
        )


def _dataset_row(
    game: NflGame,
    vector: NFLEarlyGameFeatureVector,
) -> dict[str, object]:
    row: dict[str, object] = {
        "target_game_id": vector.target_game_id,
        "target_kickoff": vector.target_kickoff,
        "target_season": vector.target_season,
        "target_season_type": vector.target_season_type.value,
        "home_team_id": vector.home_team_id,
        "away_team_id": vector.away_team_id,
        "feature_cutoff": vector.feature_cutoff,
        "feature_schema_version": vector.feature_schema_version,
        "target_tie": False,
        "route": vector.route.value,
        "minimum_current_prior_games": vector.minimum_current_prior_games,
        "neutral_site": vector.neutral_site,
        "feature_names": vector.feature_names,
        "feature_values": vector.feature_values,
        "home_win": game.home_score > game.away_score,
    }
    for side, team in (("home", vector.home), ("away", vector.away)):
        prior = team.prior_season
        current = team.current_season
        row.update({
            f"{side}_prior_season_available": prior.available,
            f"{side}_prior_season_games_played": prior.games_played,
            f"{side}_prior_season_win_percentage": prior.win_percentage,
            f"{side}_prior_season_average_point_differential": (
                prior.average_point_differential
            ),
            f"{side}_prior_season_average_turnover_differential": (
                prior.average_turnover_differential
            ),
            f"{side}_prior_season_source_game_ids": prior.source_game_ids,
            f"{side}_prior_season_source_kickoffs": prior.source_kickoffs,
            f"{side}_current_season_prior_games": current.games_played,
            f"{side}_current_season_win_percentage": current.win_percentage,
            f"{side}_current_season_average_points_for": (
                current.average_points_for
            ),
            f"{side}_current_season_average_points_against": (
                current.average_points_against
            ),
            f"{side}_current_season_average_point_differential": (
                current.average_point_differential
            ),
            f"{side}_current_season_average_turnover_differential": (
                current.average_turnover_differential
            ),
            f"{side}_current_season_source_game_ids": current.source_game_ids,
            f"{side}_current_season_source_kickoffs": current.source_kickoffs,
        })
    for name, value in zip(vector.feature_names, vector.feature_values, strict=True):
        row[name] = value
    return row
