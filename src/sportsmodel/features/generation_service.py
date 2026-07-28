from datetime import datetime

from sportsmodel.database.bullpen_statistics_repository import (
    BullpenStatisticsRepository,
)
from sportsmodel.database.game_repository import (
    GameRepository,
    PostgresGameRepository,
)
from sportsmodel.database.pitcher_statistics_repository import (
    PitcherStatisticsRepository,
)
from sportsmodel.database.team_statistics_repository import (
    TeamStatisticsRepository,
)
from sportsmodel.features.builders.game_feature_vector import (
    GameFeatureVectorBuilder,
)
from sportsmodel.features.context import (
    FeatureGenerationContext,
)
from sportsmodel.features.provider import (
    FeatureDataProvider,
)
from sportsmodel.models.baseball_game import (
    BaseballGame,
)
from sportsmodel.models.game_feature_vector import (
    GameFeatureVector,
)


class FeatureGenerationService:
    """
    Coordinate point-in-time feature generation for MLB games.

    This service is the application-facing entry point for constructing
    complete game feature vectors. Scripts, dataset generators, prediction
    workflows, and backtests should call this service rather than assembling
    repositories, providers, and builders independently.
    """

    def __init__(
        self,
        *,
        game_repository: GameRepository | None = None,
        team_statistics_repository: (
            TeamStatisticsRepository | None
        ) = None,
        pitcher_statistics_repository: (
            PitcherStatisticsRepository | None
        ) = None,
        bullpen_statistics_repository: (
            BullpenStatisticsRepository | None
        ) = None,
        game_feature_vector_builder: (
            GameFeatureVectorBuilder | None
        ) = None,
    ) -> None:
        self._game_repository = (
            game_repository
            if game_repository is not None
            else PostgresGameRepository()
        )
        self._team_statistics_repository = (
            team_statistics_repository
        )
        self._pitcher_statistics_repository = (
            pitcher_statistics_repository
        )
        self._bullpen_statistics_repository = (
            bullpen_statistics_repository
        )
        self._game_feature_vector_builder = (
            game_feature_vector_builder
            if game_feature_vector_builder is not None
            else GameFeatureVectorBuilder()
        )

    def generate(
        self,
        context: FeatureGenerationContext,
    ) -> GameFeatureVector:
        """
        Generate a complete feature vector from an explicit context.
        """

        provider = FeatureDataProvider(
            context,
            team_statistics_repository=(
                self._team_statistics_repository
            ),
            pitcher_statistics_repository=(
                self._pitcher_statistics_repository
            ),
            bullpen_statistics_repository=(
                self._bullpen_statistics_repository
            ),
        )

        return self._game_feature_vector_builder.build(
            context,
            provider,
        )

    def generate_for_game(
        self,
        *,
        game_id: int,
        cutoff_time: datetime,
        home_starting_pitcher_id: int | None = None,
        away_starting_pitcher_id: int | None = None,
    ) -> GameFeatureVector:
        """
        Load a game and generate its point-in-time feature vector.
        """

        if game_id <= 0:
            raise ValueError(
                "Game ID must be greater than zero."
            )

        game = self._game_repository.get_by_id(
            game_id=game_id,
        )

        if game is None:
            raise LookupError(
                f"Game {game_id} was not found."
            )

        return self.generate_for_game_record(
            game=game,
            cutoff_time=cutoff_time,
            home_starting_pitcher_id=(
                home_starting_pitcher_id
            ),
            away_starting_pitcher_id=(
                away_starting_pitcher_id
            ),
        )

    def generate_for_game_record(
        self,
        *,
        game: BaseballGame,
        cutoff_time: datetime,
        home_starting_pitcher_id: int | None = None,
        away_starting_pitcher_id: int | None = None,
    ) -> GameFeatureVector:
        """
        Generate a feature vector for an already-loaded game.
        """

        context = FeatureGenerationContext(
            game_id=game.game_id,
            game_start_time=game.game_start_time,
            cutoff_time=cutoff_time,
            home_team_id=game.home_team_id,
            away_team_id=game.away_team_id,
            home_starting_pitcher_id=(
                home_starting_pitcher_id
            ),
            away_starting_pitcher_id=(
                away_starting_pitcher_id
            ),
        )

        return self.generate(context)
