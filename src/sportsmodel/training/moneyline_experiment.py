from dataclasses import dataclass

from sportsmodel.training.matchup_features import (
    MatchupFeatureTransformer,
    TrainedMatchupMoneylineModel,
    transform_to_matchup_difference_dataset,
)
from sportsmodel.training.moneyline_baseline import (
    DEFAULT_REGULARIZATION_CANDIDATES,
    DEFAULT_TEST_FRACTION,
    DEFAULT_TOP_FEATURE_COUNT,
    DEFAULT_TUNING_SPLITS,
    MoneylineBaselineEvaluation,
    MoneylineTrainingDataset,
    RegularizationTuningResult,
    train_tuned_moneyline_baseline,
)


@dataclass(frozen=True)
class MoneylineExperimentVariant:
    """
    Result for one feature representation.
    """

    name: str

    input_feature_count: int

    evaluation: MoneylineBaselineEvaluation

    tuning: RegularizationTuningResult


@dataclass(frozen=True)
class MoneylineModelComparison:
    """
    Raw and matchup models evaluated on one outer test window.
    """

    raw: MoneylineExperimentVariant

    matchup: MoneylineExperimentVariant

    matchup_transformer: MatchupFeatureTransformer

    def __post_init__(self) -> None:
        raw_evaluation = self.raw.evaluation
        matchup_evaluation = self.matchup.evaluation

        comparable_values = (
            (
                raw_evaluation.training_rows,
                matchup_evaluation.training_rows,
            ),
            (
                raw_evaluation.test_rows,
                matchup_evaluation.test_rows,
            ),
            (
                raw_evaluation.training_start_time,
                matchup_evaluation.training_start_time,
            ),
            (
                raw_evaluation.training_end_time,
                matchup_evaluation.training_end_time,
            ),
            (
                raw_evaluation.test_start_time,
                matchup_evaluation.test_start_time,
            ),
            (
                raw_evaluation.test_end_time,
                matchup_evaluation.test_end_time,
            ),
        )

        if any(
            raw_value != matchup_value
            for raw_value, matchup_value
            in comparable_values
        ):
            raise ValueError(
                "Raw and matchup experiments must use the same "
                "chronological train/test partition."
            )

    @property
    def matchup_model(
        self,
    ) -> TrainedMatchupMoneylineModel:
        """
        Return the matchup model with its source transformer.
        """

        return TrainedMatchupMoneylineModel(
            transformer=self.matchup_transformer,
            model=self.matchup.evaluation.artifact,
        )


def compare_raw_and_matchup_moneyline_models(
    dataset: MoneylineTrainingDataset,
    *,
    test_fraction: float = DEFAULT_TEST_FRACTION,
    top_feature_count: int = DEFAULT_TOP_FEATURE_COUNT,
    regularization_candidates: tuple[
        float,
        ...,
    ] = DEFAULT_REGULARIZATION_CANDIDATES,
    validation_splits: int = DEFAULT_TUNING_SPLITS,
) -> MoneylineModelComparison:
    """
    Tune and evaluate raw and matchup-difference representations.

    Each representation tunes regularization using only the outer
    training partition. Both are then evaluated on the same untouched
    chronological outer test partition.
    """

    raw_evaluation, raw_tuning = (
        train_tuned_moneyline_baseline(
            dataset,
            test_fraction=test_fraction,
            top_feature_count=top_feature_count,
            regularization_candidates=(
                regularization_candidates
            ),
            validation_splits=validation_splits,
        )
    )

    matchup_dataset, transformer = (
        transform_to_matchup_difference_dataset(
            dataset
        )
    )

    matchup_evaluation, matchup_tuning = (
        train_tuned_moneyline_baseline(
            matchup_dataset,
            test_fraction=test_fraction,
            top_feature_count=top_feature_count,
            regularization_candidates=(
                regularization_candidates
            ),
            validation_splits=validation_splits,
        )
    )

    return MoneylineModelComparison(
        raw=MoneylineExperimentVariant(
            name="raw",
            input_feature_count=len(
                dataset.feature_names
            ),
            evaluation=raw_evaluation,
            tuning=raw_tuning,
        ),
        matchup=MoneylineExperimentVariant(
            name="matchup_difference",
            input_feature_count=len(
                matchup_dataset.feature_names
            ),
            evaluation=matchup_evaluation,
            tuning=matchup_tuning,
        ),
        matchup_transformer=transformer,
    )
