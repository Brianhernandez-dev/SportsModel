from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import TypeAlias

from sportsmodel.features.datasets.feature_flattener import (
    FlatFeatureMapping,
    flatten_game_feature_vector,
)
from sportsmodel.features.generation_service import (
    FeatureGenerationService,
)
from sportsmodel.models.completed_game import CompletedGame
from sportsmodel.models.game_feature_vector import (
    GameFeatureVector,
)


TrainingValue: TypeAlias = (
    bool
    | int
    | float
    | str
    | datetime
    | None
)
TrainingRow: TypeAlias = dict[str, TrainingValue]

FeatureFlattener: TypeAlias = Callable[
    [GameFeatureVector],
    FlatFeatureMapping,
]


@dataclass(frozen=True)
class MoneylineDatasetBuildResult:
    """
    Result of building a Moneyline training dataset.
    """

    rows: tuple[TrainingRow, ...]

    completed_games_received: int

    tied_games_skipped: int

    @property
    def rows_generated(self) -> int:
        return len(self.rows)

    @property
    def feature_count(self) -> int:
        if not self.rows:
            return 0

        metadata_columns = {
            "game_id",
            "game_start_time",
            "feature_time",
            "feature_schema_version",
            "home_team_id",
            "away_team_id",
            "home_score",
            "away_score",
            "home_team_won",
        }

        return len(
            set(self.rows[0]) - metadata_columns
        )


class MoneylineTrainingDatasetBuilder:
    """
    Build point-in-time Moneyline training rows.

    Each completed game is converted into features using the scheduled
    game start as the cutoff. The final score is added only after the
    feature vector has been generated.
    """

    def __init__(
        self,
        *,
        feature_generation_service: (
            FeatureGenerationService | None
        ) = None,
        feature_flattener: FeatureFlattener = (
            flatten_game_feature_vector
        ),
    ) -> None:
        self._feature_generation_service = (
            feature_generation_service
            if feature_generation_service is not None
            else FeatureGenerationService()
        )
        self._feature_flattener = feature_flattener

    def build(
        self,
        completed_games: Iterable[CompletedGame],
    ) -> MoneylineDatasetBuildResult:
        rows: list[TrainingRow] = []
        completed_games_received = 0
        tied_games_skipped = 0
        expected_feature_names: tuple[str, ...] | None = None

        for completed_game in completed_games:
            completed_games_received += 1

            if (
                completed_game.home_score
                == completed_game.away_score
            ):
                tied_games_skipped += 1
                continue

            vector = (
                self._feature_generation_service
                .generate_for_game_record(
                    game=completed_game.game,
                    cutoff_time=(
                        completed_game.game.game_start_time
                    ),
                )
            )

            flattened = self._feature_flattener(vector)
            feature_names = tuple(flattened)

            if expected_feature_names is None:
                expected_feature_names = feature_names
            elif feature_names != expected_feature_names:
                raise ValueError(
                    "Flattened feature columns changed between games."
                )

            rows.append(
                _build_training_row(
                    completed_game=completed_game,
                    vector=vector,
                    flattened=flattened,
                )
            )

        return MoneylineDatasetBuildResult(
            rows=tuple(rows),
            completed_games_received=(
                completed_games_received
            ),
            tied_games_skipped=tied_games_skipped,
        )


def _build_training_row(
    *,
    completed_game: CompletedGame,
    vector: GameFeatureVector,
    flattened: FlatFeatureMapping,
) -> TrainingRow:
    row: TrainingRow = {
        "game_id": completed_game.game.game_id,
        "game_start_time": (
            completed_game.game.game_start_time
        ),
        "feature_time": vector.feature_time,
        "feature_schema_version": (
            vector.feature_schema_version
        ),
        "home_team_id": completed_game.game.home_team_id,
        "away_team_id": completed_game.game.away_team_id,
    }

    row.update(flattened)

    row.update(
        {
            "home_score": completed_game.home_score,
            "away_score": completed_game.away_score,
            "home_team_won": (
                completed_game.home_team_won
            ),
        }
    )

    return row
