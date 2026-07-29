import csv
from dataclasses import dataclass
from datetime import datetime
from math import nan
from pathlib import Path
from statistics import fmean
from typing import Mapping

import joblib
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    brier_score_loss,
    log_loss,
    roc_auc_score,
)
from sklearn.model_selection import TimeSeriesSplit
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


METADATA_COLUMNS = frozenset(
    {
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
)

DEFAULT_TEST_FRACTION = 0.20
DEFAULT_TOP_FEATURE_COUNT = 15
DEFAULT_REGULARIZATION_C = 1.0
DEFAULT_REGULARIZATION_CANDIDATES = (
    0.01,
    0.03,
    0.10,
    0.30,
    1.00,
    3.00,
    10.00,
)
DEFAULT_TUNING_SPLITS = 4
MODEL_ARTIFACT_FORMAT_VERSION = "1.1.0"


@dataclass(frozen=True)
class MoneylineTrainingExample:
    """
    One chronologically ordered Moneyline training example.
    """

    game_id: int

    game_start_time: datetime

    home_team_won: bool

    feature_values: tuple[float | None, ...]


@dataclass(frozen=True)
class MoneylineTrainingDataset:
    """
    Parsed numeric Moneyline dataset with a stable feature schema.
    """

    feature_schema_version: str

    feature_names: tuple[str, ...]

    examples: tuple[MoneylineTrainingExample, ...]


@dataclass(frozen=True)
class ChronologicalMoneylineSplit:
    """
    Chronological train/test partition.

    The test set always contains the latest games.
    """

    training_examples: tuple[MoneylineTrainingExample, ...]

    test_examples: tuple[MoneylineTrainingExample, ...]


@dataclass(frozen=True)
class ClassificationMetrics:
    """
    Binary probability-model evaluation metrics.
    """

    accuracy: float

    log_loss: float

    brier_score: float

    roc_auc: float | None


@dataclass(frozen=True)
class FeatureCoefficient:
    """
    Standardized logistic-regression feature coefficient.
    """

    feature_name: str

    coefficient: float


@dataclass(frozen=True)
class RegularizationCandidateResult:
    """
    Chronological validation result for one regularization value.
    """

    regularization_c: float

    fold_log_losses: tuple[float, ...]

    mean_log_loss: float


@dataclass(frozen=True)
class RegularizationTuningResult:
    """
    Result of selecting logistic-regression regularization.
    """

    selected_c: float

    validation_splits: int

    candidates: tuple[
        RegularizationCandidateResult,
        ...,
    ]


@dataclass(frozen=True)
class TrainedMoneylineBaseline:
    """
    Fitted Moneyline baseline model and preprocessing metadata.
    """

    feature_schema_version: str

    active_feature_names: tuple[str, ...]

    dropped_all_missing_features: tuple[str, ...]

    dropped_constant_features: tuple[str, ...]

    dropped_duplicate_features: tuple[str, ...]

    regularization_c: float

    training_rows: int

    training_end_time: datetime

    pipeline: Pipeline

    def predict_home_win_probability(
        self,
        feature_values: Mapping[
            str,
            bool | int | float | None,
        ],
    ) -> float:
        """
        Predict the home-team win probability for one feature mapping.
        """

        missing_features = tuple(
            feature_name
            for feature_name in self.active_feature_names
            if feature_name not in feature_values
        )

        if missing_features:
            raise ValueError(
                "Prediction feature mapping is missing required "
                f"features: {missing_features}"
            )

        row = [
            _normalize_prediction_value(
                feature_values[feature_name]
            )
            for feature_name in self.active_feature_names
        ]

        probabilities = self.pipeline.predict_proba([row])

        return float(probabilities[0][1])


@dataclass(frozen=True)
class PersistedMoneylineBaseline:
    """
    Versioned serialized Moneyline model artifact.
    """

    artifact_format_version: str

    model: TrainedMoneylineBaseline


@dataclass(frozen=True)
class MoneylineBaselineEvaluation:
    """
    Evaluation result for the fitted Moneyline baseline.
    """

    training_rows: int

    test_rows: int

    training_start_time: datetime

    training_end_time: datetime

    test_start_time: datetime

    test_end_time: datetime

    training_home_win_rate: float

    model_metrics: ClassificationMetrics

    naive_baseline_metrics: ClassificationMetrics

    top_positive_coefficients: tuple[FeatureCoefficient, ...]

    top_negative_coefficients: tuple[FeatureCoefficient, ...]

    artifact: TrainedMoneylineBaseline


def save_trained_moneyline_baseline(
    model: TrainedMoneylineBaseline,
    path: Path,
) -> None:
    """
    Serialize a fitted Moneyline model and preprocessing pipeline.
    """

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    persisted_model = PersistedMoneylineBaseline(
        artifact_format_version=(
            MODEL_ARTIFACT_FORMAT_VERSION
        ),
        model=model,
    )

    joblib.dump(
        persisted_model,
        path,
    )


def load_trained_moneyline_baseline(
    path: Path,
) -> TrainedMoneylineBaseline:
    """
    Load and validate a serialized Moneyline model artifact.
    """

    persisted_model = joblib.load(path)

    if not isinstance(
        persisted_model,
        PersistedMoneylineBaseline,
    ):
        raise TypeError(
            "Serialized artifact is not a persisted Moneyline "
            "baseline model."
        )

    if (
        persisted_model.artifact_format_version
        != MODEL_ARTIFACT_FORMAT_VERSION
    ):
        raise ValueError(
            "Unsupported Moneyline model artifact format: "
            f"{persisted_model.artifact_format_version}"
        )

    return persisted_model.model


def load_moneyline_training_csv(
    path: Path,
) -> MoneylineTrainingDataset:
    """
    Load and validate a generated Moneyline training CSV.
    """

    with path.open(
        newline="",
        encoding="utf-8",
    ) as input_file:
        reader = csv.DictReader(input_file)

        if reader.fieldnames is None:
            raise ValueError(
                "Moneyline training CSV does not contain a header."
            )

        field_names = tuple(reader.fieldnames)

        missing_columns = tuple(
            column
            for column in METADATA_COLUMNS
            if column not in field_names
        )

        if missing_columns:
            raise ValueError(
                "Moneyline training CSV is missing required "
                f"columns: {missing_columns}"
            )

        feature_names = tuple(
            column
            for column in field_names
            if column not in METADATA_COLUMNS
        )

        if not feature_names:
            raise ValueError(
                "Moneyline training CSV contains no feature columns."
            )

        examples: list[MoneylineTrainingExample] = []
        schema_versions: set[str] = set()

        for row_number, row in enumerate(
            reader,
            start=2,
        ):
            schema_version = (
                row["feature_schema_version"].strip()
            )

            if not schema_version:
                raise ValueError(
                    "Feature schema version cannot be empty at "
                    f"CSV row {row_number}."
                )

            schema_versions.add(schema_version)

            game_id = _parse_positive_integer(
                value=row["game_id"],
                field_name="game_id",
                row_number=row_number,
            )

            game_start_time = _parse_datetime(
                value=row["game_start_time"],
                field_name="game_start_time",
                row_number=row_number,
            )

            home_team_won = _parse_boolean(
                value=row["home_team_won"],
                field_name="home_team_won",
                row_number=row_number,
            )

            parsed_features = tuple(
                _parse_feature_value(
                    value=row[feature_name],
                    feature_name=feature_name,
                    row_number=row_number,
                )
                for feature_name in feature_names
            )

            examples.append(
                MoneylineTrainingExample(
                    game_id=game_id,
                    game_start_time=game_start_time,
                    home_team_won=home_team_won,
                    feature_values=parsed_features,
                )
            )

    if not examples:
        raise ValueError(
            "Moneyline training CSV contains no rows."
        )

    if len(schema_versions) != 1:
        raise ValueError(
            "Moneyline training CSV contains multiple feature "
            f"schema versions: {sorted(schema_versions)}"
        )

    ordered_examples = tuple(
        sorted(
            examples,
            key=lambda example: (
                example.game_start_time,
                example.game_id,
            ),
        )
    )

    return MoneylineTrainingDataset(
        feature_schema_version=schema_versions.pop(),
        feature_names=feature_names,
        examples=ordered_examples,
    )


def chronological_train_test_split(
    dataset: MoneylineTrainingDataset,
    *,
    test_fraction: float = DEFAULT_TEST_FRACTION,
) -> ChronologicalMoneylineSplit:
    """
    Split the latest chronological block into the test set.
    """

    if not 0 < test_fraction < 1:
        raise ValueError(
            "Test fraction must be greater than zero and less "
            "than one."
        )

    if len(dataset.examples) < 4:
        raise ValueError(
            "At least four examples are required for a "
            "chronological train/test split."
        )

    test_count = max(
        1,
        round(
            len(dataset.examples)
            * test_fraction
        ),
    )

    training_count = (
        len(dataset.examples)
        - test_count
    )

    if training_count <= 0:
        raise ValueError(
            "Chronological split produced no training examples."
        )

    return ChronologicalMoneylineSplit(
        training_examples=dataset.examples[
            :training_count
        ],
        test_examples=dataset.examples[
            training_count:
        ],
    )


def fit_moneyline_baseline(
    dataset: MoneylineTrainingDataset,
    *,
    regularization_c: float = DEFAULT_REGULARIZATION_C,
) -> TrainedMoneylineBaseline:
    """
    Fit a selected Moneyline model on every dataset example.

    Model selection and out-of-sample evaluation must be completed
    separately before this function is used to create a forward-
    prediction artifact.
    """

    if regularization_c <= 0:
        raise ValueError(
            "Regularization C must be greater than zero."
        )

    training_examples = dataset.examples

    if len(training_examples) < 2:
        raise ValueError(
            "At least two training examples are required."
        )

    training_targets = [
        example.home_team_won
        for example in training_examples
    ]

    if len(set(training_targets)) < 2:
        raise ValueError(
            "Training examples must contain both target classes."
        )

    (
        active_indexes,
        active_feature_names,
        dropped_all_missing_features,
        dropped_constant_features,
        dropped_duplicate_features,
    ) = _select_training_features(
        feature_names=dataset.feature_names,
        training_examples=training_examples,
    )

    if not active_feature_names:
        raise ValueError(
            "No usable training features remain after filtering."
        )

    training_matrix = _build_feature_matrix(
        examples=training_examples,
        active_indexes=active_indexes,
    )

    pipeline = _build_pipeline(
        regularization_c=regularization_c,
    )

    pipeline.fit(
        training_matrix,
        training_targets,
    )

    return TrainedMoneylineBaseline(
        feature_schema_version=(
            dataset.feature_schema_version
        ),
        active_feature_names=active_feature_names,
        dropped_all_missing_features=(
            dropped_all_missing_features
        ),
        dropped_constant_features=(
            dropped_constant_features
        ),
        dropped_duplicate_features=(
            dropped_duplicate_features
        ),
        regularization_c=regularization_c,
        training_rows=len(training_examples),
        training_end_time=(
            training_examples[-1].game_start_time
        ),
        pipeline=pipeline,
    )


def train_moneyline_baseline(
    dataset: MoneylineTrainingDataset,
    *,
    test_fraction: float = DEFAULT_TEST_FRACTION,
    top_feature_count: int = DEFAULT_TOP_FEATURE_COUNT,
    regularization_c: float = DEFAULT_REGULARIZATION_C,
) -> MoneylineBaselineEvaluation:
    """
    Train and evaluate a regularized logistic-regression baseline.
    """

    if top_feature_count <= 0:
        raise ValueError(
            "Top feature count must be greater than zero."
        )

    if regularization_c <= 0:
        raise ValueError(
            "Regularization C must be greater than zero."
        )

    split = chronological_train_test_split(
        dataset,
        test_fraction=test_fraction,
    )

    (
        active_indexes,
        active_feature_names,
        dropped_all_missing_features,
        dropped_constant_features,
        dropped_duplicate_features,
    ) = _select_training_features(
        feature_names=dataset.feature_names,
        training_examples=split.training_examples,
    )

    if not active_feature_names:
        raise ValueError(
            "No usable training features remain after filtering."
        )

    training_matrix = _build_feature_matrix(
        examples=split.training_examples,
        active_indexes=active_indexes,
    )

    test_matrix = _build_feature_matrix(
        examples=split.test_examples,
        active_indexes=active_indexes,
    )

    training_targets = [
        example.home_team_won
        for example in split.training_examples
    ]

    test_targets = [
        example.home_team_won
        for example in split.test_examples
    ]

    pipeline = _build_pipeline(
        regularization_c=regularization_c,
    )

    pipeline.fit(
        training_matrix,
        training_targets,
    )

    model_probabilities = [
        float(probability)
        for probability in pipeline.predict_proba(
            test_matrix
        )[:, 1]
    ]

    model_predictions = [
        bool(prediction)
        for prediction in pipeline.predict(
            test_matrix
        )
    ]

    training_home_win_rate = (
        sum(training_targets)
        / len(training_targets)
    )

    naive_probabilities = [
        training_home_win_rate
        for _ in test_targets
    ]

    naive_predictions = [
        training_home_win_rate >= 0.5
        for _ in test_targets
    ]

    coefficients = _extract_coefficients(
        pipeline=pipeline,
        active_feature_names=active_feature_names,
    )

    positive_coefficients = tuple(
        sorted(
            (
                coefficient
                for coefficient in coefficients
                if coefficient.coefficient > 0
            ),
            key=lambda coefficient: (
                coefficient.coefficient
            ),
            reverse=True,
        )[:top_feature_count]
    )

    negative_coefficients = tuple(
        sorted(
            (
                coefficient
                for coefficient in coefficients
                if coefficient.coefficient < 0
            ),
            key=lambda coefficient: (
                coefficient.coefficient
            ),
        )[:top_feature_count]
    )

    training_examples = split.training_examples
    test_examples = split.test_examples

    artifact = TrainedMoneylineBaseline(
        feature_schema_version=(
            dataset.feature_schema_version
        ),
        active_feature_names=active_feature_names,
        dropped_all_missing_features=(
            dropped_all_missing_features
        ),
        dropped_constant_features=(
            dropped_constant_features
        ),
        dropped_duplicate_features=(
            dropped_duplicate_features
        ),
        regularization_c=regularization_c,
        training_rows=len(training_examples),
        training_end_time=(
            training_examples[-1].game_start_time
        ),
        pipeline=pipeline,
    )

    return MoneylineBaselineEvaluation(
        training_rows=len(training_examples),
        test_rows=len(test_examples),
        training_start_time=(
            training_examples[0].game_start_time
        ),
        training_end_time=(
            training_examples[-1].game_start_time
        ),
        test_start_time=(
            test_examples[0].game_start_time
        ),
        test_end_time=(
            test_examples[-1].game_start_time
        ),
        training_home_win_rate=(
            training_home_win_rate
        ),
        model_metrics=_calculate_metrics(
            targets=test_targets,
            predictions=model_predictions,
            probabilities=model_probabilities,
        ),
        naive_baseline_metrics=_calculate_metrics(
            targets=test_targets,
            predictions=naive_predictions,
            probabilities=naive_probabilities,
        ),
        top_positive_coefficients=(
            positive_coefficients
        ),
        top_negative_coefficients=(
            negative_coefficients
        ),
        artifact=artifact,
    )


def tune_moneyline_regularization(
    dataset: MoneylineTrainingDataset,
    *,
    test_fraction: float = DEFAULT_TEST_FRACTION,
    regularization_candidates: tuple[
        float,
        ...,
    ] = DEFAULT_REGULARIZATION_CANDIDATES,
    validation_splits: int = DEFAULT_TUNING_SPLITS,
) -> RegularizationTuningResult:
    """
    Select regularization using expanding chronological folds.

    Only the outer training partition participates in tuning. The latest
    outer test partition remains excluded until final evaluation.
    """

    _validate_regularization_candidates(
        regularization_candidates
    )

    if validation_splits < 2:
        raise ValueError(
            "Validation split count must be at least two."
        )

    outer_split = chronological_train_test_split(
        dataset,
        test_fraction=test_fraction,
    )

    tuning_examples = outer_split.training_examples

    if len(tuning_examples) <= validation_splits:
        raise ValueError(
            "Not enough training examples for the requested "
            "chronological validation splits."
        )

    splitter = TimeSeriesSplit(
        n_splits=validation_splits,
    )

    candidate_results: list[
        RegularizationCandidateResult
    ] = []

    for regularization_c in regularization_candidates:
        fold_log_losses: list[float] = []

        for training_indexes, validation_indexes in (
            splitter.split(tuning_examples)
        ):
            fold_training_examples = tuple(
                tuning_examples[index]
                for index in training_indexes
            )

            fold_validation_examples = tuple(
                tuning_examples[index]
                for index in validation_indexes
            )

            (
                active_indexes,
                active_feature_names,
                _,
                _,
                _,
            ) = _select_training_features(
                feature_names=dataset.feature_names,
                training_examples=(
                    fold_training_examples
                ),
            )

            if not active_feature_names:
                raise ValueError(
                    "No usable features remain in a tuning fold."
                )

            training_targets = [
                example.home_team_won
                for example in fold_training_examples
            ]

            if len(set(training_targets)) < 2:
                raise ValueError(
                    "A tuning fold contains only one training "
                    "target class."
                )

            validation_targets = [
                example.home_team_won
                for example in fold_validation_examples
            ]

            pipeline = _build_pipeline(
                regularization_c=regularization_c,
            )

            pipeline.fit(
                _build_feature_matrix(
                    examples=fold_training_examples,
                    active_indexes=active_indexes,
                ),
                training_targets,
            )

            validation_probabilities = [
                float(probability)
                for probability in pipeline.predict_proba(
                    _build_feature_matrix(
                        examples=fold_validation_examples,
                        active_indexes=active_indexes,
                    )
                )[:, 1]
            ]

            fold_log_losses.append(
                float(
                    log_loss(
                        validation_targets,
                        validation_probabilities,
                        labels=[
                            False,
                            True,
                        ],
                    )
                )
            )

        candidate_results.append(
            RegularizationCandidateResult(
                regularization_c=regularization_c,
                fold_log_losses=tuple(
                    fold_log_losses
                ),
                mean_log_loss=fmean(
                    fold_log_losses
                ),
            )
        )

    selected_candidate = min(
        candidate_results,
        key=lambda candidate: (
            candidate.mean_log_loss,
            candidate.regularization_c,
        ),
    )

    return RegularizationTuningResult(
        selected_c=(
            selected_candidate.regularization_c
        ),
        validation_splits=validation_splits,
        candidates=tuple(candidate_results),
    )


def train_tuned_moneyline_baseline(
    dataset: MoneylineTrainingDataset,
    *,
    test_fraction: float = DEFAULT_TEST_FRACTION,
    top_feature_count: int = DEFAULT_TOP_FEATURE_COUNT,
    regularization_candidates: tuple[
        float,
        ...,
    ] = DEFAULT_REGULARIZATION_CANDIDATES,
    validation_splits: int = DEFAULT_TUNING_SPLITS,
) -> tuple[
    MoneylineBaselineEvaluation,
    RegularizationTuningResult,
]:
    """
    Tune regularization and evaluate the selected model.
    """

    tuning_result = tune_moneyline_regularization(
        dataset,
        test_fraction=test_fraction,
        regularization_candidates=(
            regularization_candidates
        ),
        validation_splits=validation_splits,
    )

    evaluation = train_moneyline_baseline(
        dataset,
        test_fraction=test_fraction,
        top_feature_count=top_feature_count,
        regularization_c=tuning_result.selected_c,
    )

    return evaluation, tuning_result


def _validate_regularization_candidates(
    candidates: tuple[float, ...],
) -> None:
    if not candidates:
        raise ValueError(
            "At least one regularization candidate is required."
        )

    if any(candidate <= 0 for candidate in candidates):
        raise ValueError(
            "Regularization candidates must be greater than zero."
        )

    if len(candidates) != len(set(candidates)):
        raise ValueError(
            "Regularization candidates must be unique."
        )


def _select_training_features(
    *,
    feature_names: tuple[str, ...],
    training_examples: tuple[
        MoneylineTrainingExample,
        ...,
    ],
) -> tuple[
    tuple[int, ...],
    tuple[str, ...],
    tuple[str, ...],
    tuple[str, ...],
    tuple[str, ...],
]:
    active_indexes: list[int] = []
    active_feature_names: list[str] = []
    dropped_all_missing: list[str] = []
    dropped_constant: list[str] = []
    dropped_duplicate: list[str] = []
    observed_signatures: dict[
        tuple[float | None, ...],
        str,
    ] = {}

    for index, feature_name in enumerate(
        feature_names
    ):
        values = [
            example.feature_values[index]
            for example in training_examples
        ]

        nonmissing_values = [
            value
            for value in values
            if value is not None
        ]

        if not nonmissing_values:
            dropped_all_missing.append(
                feature_name
            )
            continue

        has_missing_values = (
            len(nonmissing_values)
            != len(values)
        )

        if (
            not has_missing_values
            and len(set(nonmissing_values)) == 1
        ):
            dropped_constant.append(
                feature_name
            )
            continue

        value_signature = tuple(values)

        if value_signature in observed_signatures:
            dropped_duplicate.append(
                feature_name
            )
            continue

        observed_signatures[value_signature] = (
            feature_name
        )

        active_indexes.append(index)
        active_feature_names.append(
            feature_name
        )

    return (
        tuple(active_indexes),
        tuple(active_feature_names),
        tuple(dropped_all_missing),
        tuple(dropped_constant),
        tuple(dropped_duplicate),
    )


def _build_feature_matrix(
    *,
    examples: tuple[
        MoneylineTrainingExample,
        ...,
    ],
    active_indexes: tuple[int, ...],
) -> list[list[float]]:
    return [
        [
            (
                nan
                if example.feature_values[index] is None
                else example.feature_values[index]
            )
            for index in active_indexes
        ]
        for example in examples
    ]


def _build_pipeline(
    *,
    regularization_c: float,
) -> Pipeline:
    return Pipeline(
        steps=[
            (
                "imputer",
                SimpleImputer(
                    strategy="median",
                    add_indicator=True,
                ),
            ),
            (
                "scaler",
                StandardScaler(),
            ),
            (
                "classifier",
                LogisticRegression(
                    C=regularization_c,
                    solver="lbfgs",
                    max_iter=5000,
                    random_state=42,
                ),
            ),
        ]
    )


def _calculate_metrics(
    *,
    targets: list[bool],
    predictions: list[bool],
    probabilities: list[float],
) -> ClassificationMetrics:
    roc_auc: float | None

    try:
        roc_auc = float(
            roc_auc_score(
                targets,
                probabilities,
            )
        )
    except ValueError:
        roc_auc = None

    return ClassificationMetrics(
        accuracy=float(
            accuracy_score(
                targets,
                predictions,
            )
        ),
        log_loss=float(
            log_loss(
                targets,
                probabilities,
                labels=[
                    False,
                    True,
                ],
            )
        ),
        brier_score=float(
            brier_score_loss(
                targets,
                probabilities,
            )
        ),
        roc_auc=roc_auc,
    )


def _extract_coefficients(
    *,
    pipeline: Pipeline,
    active_feature_names: tuple[str, ...],
) -> tuple[FeatureCoefficient, ...]:
    imputer = pipeline.named_steps["imputer"]
    classifier = pipeline.named_steps["classifier"]

    transformed_feature_names = tuple(
        str(feature_name)
        for feature_name in imputer.get_feature_names_out(
            active_feature_names
        )
    )

    coefficients = classifier.coef_[0]

    if len(transformed_feature_names) != len(
        coefficients
    ):
        raise RuntimeError(
            "Transformed feature names do not match model "
            "coefficient count."
        )

    return tuple(
        FeatureCoefficient(
            feature_name=feature_name,
            coefficient=float(coefficient),
        )
        for feature_name, coefficient in zip(
            transformed_feature_names,
            coefficients,
            strict=True,
        )
    )


def _parse_positive_integer(
    *,
    value: str,
    field_name: str,
    row_number: int,
) -> int:
    try:
        parsed_value = int(value)
    except ValueError as exception:
        raise ValueError(
            f"{field_name} must be an integer at CSV row "
            f"{row_number}."
        ) from exception

    if parsed_value <= 0:
        raise ValueError(
            f"{field_name} must be greater than zero at CSV "
            f"row {row_number}."
        )

    return parsed_value


def _parse_datetime(
    *,
    value: str,
    field_name: str,
    row_number: int,
) -> datetime:
    try:
        parsed_value = datetime.fromisoformat(
            value.strip()
        )
    except ValueError as exception:
        raise ValueError(
            f"{field_name} must be an ISO datetime at CSV row "
            f"{row_number}."
        ) from exception

    if (
        parsed_value.tzinfo is None
        or parsed_value.utcoffset() is None
    ):
        raise ValueError(
            f"{field_name} must be timezone-aware at CSV row "
            f"{row_number}."
        )

    return parsed_value


def _parse_boolean(
    *,
    value: str,
    field_name: str,
    row_number: int,
) -> bool:
    normalized_value = value.strip().lower()

    if normalized_value == "true":
        return True

    if normalized_value == "false":
        return False

    raise ValueError(
        f"{field_name} must be true or false at CSV row "
        f"{row_number}."
    )


def _parse_feature_value(
    *,
    value: str,
    feature_name: str,
    row_number: int,
) -> float | None:
    normalized_value = value.strip()

    if not normalized_value:
        return None

    lowercase_value = normalized_value.lower()

    if lowercase_value == "true":
        return 1.0

    if lowercase_value == "false":
        return 0.0

    try:
        return float(normalized_value)
    except ValueError as exception:
        raise ValueError(
            "Feature values must be numeric, boolean, or empty. "
            f"Invalid value for {feature_name!r} at CSV row "
            f"{row_number}: {normalized_value!r}"
        ) from exception


def _normalize_prediction_value(
    value: bool | int | float | None,
) -> float:
    if value is None:
        return nan

    return float(value)
