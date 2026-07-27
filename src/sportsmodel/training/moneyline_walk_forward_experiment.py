from dataclasses import dataclass

from sportsmodel.training.matchup_features import (
    MatchupFeatureTransformer,
    transform_to_matchup_difference_dataset,
)
from sportsmodel.training.moneyline_baseline import (
    DEFAULT_TOP_FEATURE_COUNT,
    DEFAULT_TUNING_SPLITS,
    MoneylineTrainingDataset,
)
from sportsmodel.training.moneyline_walk_forward import (
    DEFAULT_CALIBRATION_BIN_WIDTH,
    DEFAULT_INITIAL_TRAINING_ROWS,
    DEFAULT_TEST_BLOCK_SIZE,
    MoneylineWalkForwardEvaluation,
    evaluate_moneyline_walk_forward,
)


DEFAULT_WALK_FORWARD_REGULARIZATION_CANDIDATES = (
    0.0001,
    0.0003,
    0.0010,
    0.0030,
    0.0100,
    0.0300,
    0.1000,
)


@dataclass(frozen=True)
class MoneylineWalkForwardVariant:
    """
    Walk-forward result for one feature representation.
    """

    name: str

    input_feature_count: int

    evaluation: MoneylineWalkForwardEvaluation


@dataclass(frozen=True)
class MoneylineWalkForwardComparison:
    """
    Raw and matchup representations evaluated on identical games.
    """

    raw: MoneylineWalkForwardVariant

    matchup: MoneylineWalkForwardVariant

    matchup_transformer: MatchupFeatureTransformer

    def __post_init__(self) -> None:
        raw_predictions = self.raw.evaluation.predictions
        matchup_predictions = (
            self.matchup.evaluation.predictions
        )

        raw_prediction_keys = tuple(
            (
                prediction.game_id,
                prediction.game_start_time,
            )
            for prediction in raw_predictions
        )

        matchup_prediction_keys = tuple(
            (
                prediction.game_id,
                prediction.game_start_time,
            )
            for prediction in matchup_predictions
        )

        if raw_prediction_keys != matchup_prediction_keys:
            raise ValueError(
                "Raw and matchup walk-forward evaluations must "
                "predict the same chronological games."
            )

        if (
            self.raw.evaluation.initial_training_rows
            != self.matchup.evaluation.initial_training_rows
        ):
            raise ValueError(
                "Raw and matchup evaluations must use the same "
                "initial training window."
            )

        if (
            self.raw.evaluation.test_block_size
            != self.matchup.evaluation.test_block_size
        ):
            raise ValueError(
                "Raw and matchup evaluations must use the same "
                "test block size."
            )


def compare_raw_and_matchup_walk_forward(
    dataset: MoneylineTrainingDataset,
    *,
    initial_training_rows: int = (
        DEFAULT_INITIAL_TRAINING_ROWS
    ),
    test_block_size: int = DEFAULT_TEST_BLOCK_SIZE,
    top_feature_count: int = DEFAULT_TOP_FEATURE_COUNT,
    regularization_candidates: tuple[
        float,
        ...,
    ] = DEFAULT_WALK_FORWARD_REGULARIZATION_CANDIDATES,
    validation_splits: int = DEFAULT_TUNING_SPLITS,
    calibration_bin_width: float = (
        DEFAULT_CALIBRATION_BIN_WIDTH
    ),
) -> MoneylineWalkForwardComparison:
    """
    Evaluate raw and matchup features over identical expanding folds.
    """

    raw_evaluation = evaluate_moneyline_walk_forward(
        dataset,
        initial_training_rows=initial_training_rows,
        test_block_size=test_block_size,
        top_feature_count=top_feature_count,
        regularization_candidates=(
            regularization_candidates
        ),
        validation_splits=validation_splits,
        calibration_bin_width=calibration_bin_width,
    )

    matchup_dataset, transformer = (
        transform_to_matchup_difference_dataset(
            dataset
        )
    )

    matchup_evaluation = evaluate_moneyline_walk_forward(
        matchup_dataset,
        initial_training_rows=initial_training_rows,
        test_block_size=test_block_size,
        top_feature_count=top_feature_count,
        regularization_candidates=(
            regularization_candidates
        ),
        validation_splits=validation_splits,
        calibration_bin_width=calibration_bin_width,
    )

    return MoneylineWalkForwardComparison(
        raw=MoneylineWalkForwardVariant(
            name="raw",
            input_feature_count=len(
                dataset.feature_names
            ),
            evaluation=raw_evaluation,
        ),
        matchup=MoneylineWalkForwardVariant(
            name="matchup_difference",
            input_feature_count=len(
                matchup_dataset.feature_names
            ),
            evaluation=matchup_evaluation,
        ),
        matchup_transformer=transformer,
    )
