from dataclasses import dataclass
from collections.abc import Callable, Iterable

from sportsmodel.nfl.features import NFLFeatureDataProvider, NFLGameFeatureVectorBuilder
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
                "home_win": game.home_score > game.away_score,
            })
        return NFLMoneylineDatasetBuildResult(tuple(rows), received, ties, nonfinal)
