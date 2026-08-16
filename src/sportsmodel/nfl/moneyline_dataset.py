from dataclasses import dataclass
from collections.abc import Callable, Iterable

from sportsmodel.nfl.features import (
    NFLFeatureDataProvider,
    NFLGameFeatureVectorBuilder,
    NFLTeamFeatureVector,
)
from sportsmodel.nfl.models import NflGame, NflGameStatus


@dataclass(frozen=True)
class NFLMoneylineDatasetBuildResult:
    rows: tuple[dict[str, object], ...]
    games_received: int
    ties_skipped: int
    nonfinal_games_skipped: int


class NFLMoneylineTrainingDatasetBuilder:
    """Build inspectable PIT rows; ties and non-final games are explicitly excluded."""

    def __init__(self, *, vector_builder: NFLGameFeatureVectorBuilder | None = None,
                 provider_factory: Callable[[NflGame], NFLFeatureDataProvider] = NFLFeatureDataProvider):
        self.vector_builder = vector_builder or NFLGameFeatureVectorBuilder()
        self.provider_factory = provider_factory

    def build(self, games: Iterable[NflGame]) -> NFLMoneylineDatasetBuildResult:
        rows, received, ties, nonfinal = [], 0, 0, 0
        ordered_games = sorted(
            games,
            key=lambda game: (game.scheduled_start_time, game.game_id),
        )
        for game in ordered_games:
            received += 1
            if game.status is not NflGameStatus.FINAL:
                nonfinal += 1
                continue
            assert game.home_score is not None and game.away_score is not None
            if game.home_score == game.away_score:
                ties += 1
                continue
            vector = self.vector_builder.build(game, provider=self.provider_factory(game))
            rows.append({
                "target_game_id": vector.target_game_id, "target_kickoff": vector.target_kickoff,
                "home_team_id": vector.home_team_id, "away_team_id": vector.away_team_id,
                "feature_cutoff": vector.feature_cutoff,
                "feature_schema_version": vector.feature_schema_version,
                "home_prior_games_used": vector.home.prior_games_used,
                "away_prior_games_used": vector.away.prior_games_used,
                "home_win_percentage": vector.home.win_percentage,
                "away_win_percentage": vector.away.win_percentage,
                "home_average_points_for": vector.home.average_points_for,
                "away_average_points_for": vector.away.average_points_for,
                "home_average_points_against": vector.home.average_points_against,
                "away_average_points_against": vector.away.average_points_against,
                "home_average_point_differential": vector.home.average_point_differential,
                "away_average_point_differential": vector.away.average_point_differential,
                "home_average_passing_yards": vector.home.average_passing_yards,
                "away_average_passing_yards": vector.away.average_passing_yards,
                "home_average_passing_yards_allowed": vector.home.average_passing_yards_allowed,
                "away_average_passing_yards_allowed": vector.away.average_passing_yards_allowed,
                "home_average_rushing_yards": vector.home.average_rushing_yards,
                "away_average_rushing_yards": vector.away.average_rushing_yards,
                "home_average_rushing_yards_allowed": vector.home.average_rushing_yards_allowed,
                "away_average_rushing_yards_allowed": vector.away.average_rushing_yards_allowed,
                "home_average_turnovers": vector.home.average_turnovers,
                "away_average_turnovers": vector.away.average_turnovers,
                "home_average_takeaways": vector.home.average_takeaways,
                "away_average_takeaways": vector.away.average_takeaways,
                "home_average_turnover_differential": vector.home.average_turnover_differential,
                "away_average_turnover_differential": vector.away.average_turnover_differential,
                **_rolling_columns("home", vector.home),
                **_rolling_columns("away", vector.away),
                "home_win": game.home_score > game.away_score,
            })
        return NFLMoneylineDatasetBuildResult(tuple(rows), received, ties, nonfinal)


def _rolling_columns(
    prefix: str,
    features: NFLTeamFeatureVector,
) -> dict[str, object]:
    columns: dict[str, object] = {}
    for window, rolling in ((3, features.rolling_3), (5, features.rolling_5)):
        base = f"{prefix}_rolling_{window}"
        columns[f"{base}_games_used"] = rolling.games_used
        columns[f"{base}_average_points_for"] = rolling.average_points_for
        columns[f"{base}_average_points_against"] = rolling.average_points_against
        columns[f"{base}_average_point_differential"] = rolling.average_point_differential
        columns[f"{base}_average_turnover_differential"] = rolling.average_turnover_differential
    return columns
