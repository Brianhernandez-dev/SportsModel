from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from math import exp, isclose, nan
from pathlib import Path
from typing import Any

from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

from sportsmodel.database.bullpen_statistics_repository import (
    PostgresBullpenStatisticsRepository,
)
from sportsmodel.database.connection import get_connection
from sportsmodel.database.pitcher_statistics_repository import (
    PostgresPitcherStatisticsRepository,
)
from sportsmodel.database.team_statistics_repository import (
    PostgresTeamStatisticsRepository,
)
from sportsmodel.features.datasets.feature_flattener import (
    flatten_game_feature_vector,
)
from sportsmodel.features.generation_service import FeatureGenerationService
from sportsmodel.models.baseball_game import BaseballGame
from sportsmodel.predictions.moneyline_service import (
    LoadedMoneylineModelPackage,
    load_moneyline_model_package,
)
from sportsmodel.training.matchup_features import TrainedMatchupMoneylineModel


DEFAULT_MODEL_ROOT = Path("data/models")
DEFAULT_RECONSTRUCTION_TOLERANCE = 1e-9
CONTRIBUTION_CATEGORIES = (
    "batting",
    "team_pitching",
    "bullpen",
    "starting_pitcher",
    "other",
)

ConnectionFactory = Callable[[], Any]
ModelPackageLoader = Callable[[Path], LoadedMoneylineModelPackage]


@dataclass(frozen=True)
class StoredMoneylinePredictionExplanationInput:
    prediction_id: int
    prediction_run_id: int
    game_id: int
    mlb_game_id: int | None
    game_start_time: datetime
    prediction_time: datetime
    home_team_id: int
    away_team_id: int
    home_team_name: str
    away_team_name: str
    predicted_team_id: int
    predicted_team_name: str
    opponent_team_id: int
    opponent_team_name: str
    home_starting_pitcher_id: int | None
    away_starting_pitcher_id: int | None
    home_starting_pitcher_mlb_id: int | None
    away_starting_pitcher_mlb_id: int | None
    home_starting_pitcher_name: str | None
    away_starting_pitcher_name: str | None
    persisted_missing_raw_value_count: int
    stored_home_win_probability: Decimal
    stored_predicted_probability: Decimal
    model_version: str
    feature_schema_version: str
    model_artifact_sha256: str
    model_training_cutoff: datetime | None


@dataclass(frozen=True)
class MoneylineFeatureContribution:
    feature_name: str
    category: str
    imputed_value: float
    standardized_value: float
    coefficient: float
    contribution: float
    is_missing_indicator: bool


@dataclass(frozen=True)
class MoneylineContributionBreakdown:
    reconstructed_home_win_probability: float
    model_intercept: float
    feature_logit_total: float
    final_logit: float
    transformed_missing_feature_names: tuple[str, ...]
    active_missing_feature_names: tuple[str, ...]
    inactive_missing_feature_names: tuple[str, ...]
    contributions: tuple[MoneylineFeatureContribution, ...]
    category_totals: tuple[tuple[str, float], ...]


@dataclass(frozen=True)
class MoneylinePredictionExplanation:
    prediction: StoredMoneylinePredictionExplanationInput
    authoritative: bool
    reconstruction_tolerance: float
    probability_delta: float
    raw_feature_count: int
    raw_missing_feature_names: tuple[str, ...]
    transformed_missing_feature_names: tuple[str, ...]
    active_missing_feature_names: tuple[str, ...]
    inactive_missing_feature_names: tuple[str, ...]
    regenerated_missing_raw_value_count: int
    model_intercept: float
    feature_logit_total: float
    final_logit: float
    reconstructed_home_win_probability: float
    contributions: tuple[MoneylineFeatureContribution, ...]
    category_totals: tuple[tuple[str, float], ...]

    @property
    def home_contributions(self) -> tuple[MoneylineFeatureContribution, ...]:
        return tuple(
            sorted(
                (item for item in self.contributions if item.contribution > 0),
                key=lambda item: item.contribution,
                reverse=True,
            )
        )

    @property
    def away_contributions(self) -> tuple[MoneylineFeatureContribution, ...]:
        return tuple(
            sorted(
                (item for item in self.contributions if item.contribution < 0),
                key=lambda item: item.contribution,
            )
        )

    @property
    def starting_pitcher_contributions(
        self,
    ) -> tuple[MoneylineFeatureContribution, ...]:
        return tuple(
            item
            for item in self.contributions
            if item.category == "starting_pitcher"
        )

    @property
    def starting_pitcher_total(self) -> float:
        return sum(
            item.contribution for item in self.starting_pitcher_contributions
        )


def explain_moneyline_prediction(
    *,
    prediction_id: int,
    connection_factory: ConnectionFactory = get_connection,
    model_root: Path = DEFAULT_MODEL_ROOT,
    feature_generation_service: FeatureGenerationService | None = None,
    model_package_loader: ModelPackageLoader = load_moneyline_model_package,
    reconstruction_tolerance: float = DEFAULT_RECONSTRUCTION_TOLERANCE,
) -> MoneylinePredictionExplanation:
    """Reconstruct one stored prediction using only frozen files and the DB.

    The absolute tolerance is 1e-9 by default. This covers the maximum
    rounding introduced by the persisted NUMERIC(12,10) probability while
    remaining strict enough to detect material feature-history drift.
    """

    _validate_positive_identifier(prediction_id)
    if reconstruction_tolerance <= 0:
        raise ValueError("Reconstruction tolerance must be greater than zero.")

    stored = _load_stored_prediction(
        prediction_id=prediction_id,
        connection_factory=connection_factory,
    )
    package = _load_and_validate_associated_model(
        stored=stored,
        model_root=model_root,
        model_package_loader=model_package_loader,
    )
    game = BaseballGame(
        game_id=stored.game_id,
        game_start_time=stored.game_start_time,
        home_team_id=stored.home_team_id,
        away_team_id=stored.away_team_id,
    )
    resolved_feature_service = (
        feature_generation_service
        if feature_generation_service is not None
        else _build_read_only_feature_service(connection_factory)
    )
    feature_vector = resolved_feature_service.generate_for_game_record(
        game=game,
        cutoff_time=stored.prediction_time,
        home_starting_pitcher_id=stored.home_starting_pitcher_id,
        away_starting_pitcher_id=stored.away_starting_pitcher_id,
    )
    if feature_vector.feature_schema_version != stored.feature_schema_version:
        raise RuntimeError(
            "Reconstructed feature schema does not match the prediction run."
        )

    raw_features = flatten_game_feature_vector(feature_vector)
    expected_names = package.model.transformer.source_feature_names
    if tuple(raw_features) != expected_names:
        raise RuntimeError(
            "Reconstructed raw feature columns do not match the frozen model."
        )

    raw_missing = tuple(
        name for name, value in raw_features.items() if value is None
    )
    breakdown = calculate_moneyline_contributions(
        package.model,
        raw_features,
    )
    stored_probability = float(stored.stored_home_win_probability)
    delta = breakdown.reconstructed_home_win_probability - stored_probability
    authoritative = (
        abs(delta) <= reconstruction_tolerance
        and len(raw_missing) == stored.persisted_missing_raw_value_count
    )

    return MoneylinePredictionExplanation(
        prediction=stored,
        authoritative=authoritative,
        reconstruction_tolerance=reconstruction_tolerance,
        probability_delta=delta,
        raw_feature_count=len(raw_features),
        raw_missing_feature_names=raw_missing,
        transformed_missing_feature_names=(
            breakdown.transformed_missing_feature_names
        ),
        active_missing_feature_names=(
            breakdown.active_missing_feature_names
        ),
        inactive_missing_feature_names=(
            breakdown.inactive_missing_feature_names
        ),
        regenerated_missing_raw_value_count=len(raw_missing),
        model_intercept=breakdown.model_intercept,
        feature_logit_total=breakdown.feature_logit_total,
        final_logit=breakdown.final_logit,
        reconstructed_home_win_probability=(
            breakdown.reconstructed_home_win_probability
        ),
        contributions=breakdown.contributions,
        category_totals=breakdown.category_totals,
    )


def calculate_moneyline_contributions(
    model: TrainedMatchupMoneylineModel,
    raw_feature_values: Mapping[str, bool | int | float | None],
) -> MoneylineContributionBreakdown:
    """Apply the frozen pipeline and decompose its exact linear logit."""

    transformer = model.transformer
    missing_source_names = tuple(
        name for name in transformer.source_feature_names
        if name not in raw_feature_values
    )
    if missing_source_names:
        raise ValueError(
            "Raw explanation feature mapping is missing required features: "
            f"{missing_source_names}"
        )

    source_values = tuple(
        None if raw_feature_values[name] is None else float(raw_feature_values[name])
        for name in transformer.source_feature_names
    )
    transformed_values = transformer.transform_values(source_values)
    transformed_mapping = dict(
        zip(transformer.output_feature_names, transformed_values, strict=True)
    )
    transformed_missing = tuple(
        name for name, value in transformed_mapping.items() if value is None
    )

    baseline = model.model
    active_missing = tuple(
        name
        for name in transformed_missing
        if name in baseline.active_feature_names
    )
    inactive_missing = tuple(
        name
        for name in transformed_missing
        if name not in baseline.active_feature_names
    )
    imputer, scaler, classifier = _validated_pipeline_components(
        baseline.pipeline
    )
    active_values = [
        nan if transformed_mapping[name] is None else transformed_mapping[name]
        for name in baseline.active_feature_names
    ]
    imputed_row = imputer.transform([active_values])
    standardized_row = scaler.transform(imputed_row)
    output_names = tuple(
        str(name)
        for name in imputer.get_feature_names_out(baseline.active_feature_names)
    )
    coefficients = classifier.coef_[0]
    if not (
        len(output_names)
        == len(imputed_row[0])
        == len(standardized_row[0])
        == len(coefficients)
    ):
        raise RuntimeError(
            "Frozen preprocessing output does not match classifier coefficients."
        )

    contributions = tuple(
        MoneylineFeatureContribution(
            feature_name=name,
            category=categorize_moneyline_feature(name),
            imputed_value=float(imputed),
            standardized_value=float(standardized),
            coefficient=float(coefficient),
            contribution=float(standardized * coefficient),
            is_missing_indicator=name.startswith("missingindicator_"),
        )
        for name, imputed, standardized, coefficient in zip(
            output_names,
            imputed_row[0],
            standardized_row[0],
            coefficients,
            strict=True,
        )
    )
    intercept = float(classifier.intercept_[0])
    feature_total = sum(item.contribution for item in contributions)
    final_logit = intercept + feature_total
    probability = model.predict_home_win_probability(raw_feature_values)
    probability_from_logit = _sigmoid(final_logit)
    if not isclose(probability, probability_from_logit, abs_tol=1e-12):
        raise RuntimeError(
            "Contribution logit does not reproduce the frozen model probability."
        )

    category_totals = tuple(
        (
            category,
            sum(
                item.contribution
                for item in contributions
                if item.category == category
            ),
        )
        for category in CONTRIBUTION_CATEGORIES
    )
    return MoneylineContributionBreakdown(
        reconstructed_home_win_probability=probability,
        model_intercept=intercept,
        feature_logit_total=feature_total,
        final_logit=final_logit,
        transformed_missing_feature_names=transformed_missing,
        active_missing_feature_names=active_missing,
        inactive_missing_feature_names=inactive_missing,
        contributions=contributions,
        category_totals=category_totals,
    )


def categorize_moneyline_feature(feature_name: str) -> str:
    """Map model and missing-indicator features to reporting categories."""

    normalized = feature_name.removeprefix("missingindicator_")
    normalized = normalized.removeprefix("matchup_")
    if normalized.startswith("batting_"):
        return "batting"
    if normalized.startswith("pitching_"):
        return "team_pitching"
    if normalized.startswith("bullpen_"):
        return "bullpen"
    if normalized.startswith("starting_pitcher_"):
        return "starting_pitcher"
    return "other"


def _validated_pipeline_components(pipeline: Any) -> tuple[
    SimpleImputer,
    StandardScaler,
    LogisticRegression,
]:
    try:
        imputer = pipeline.named_steps["imputer"]
        scaler = pipeline.named_steps["scaler"]
        classifier = pipeline.named_steps["classifier"]
    except (AttributeError, KeyError) as error:
        raise TypeError("Unsupported Moneyline model pipeline structure.") from error
    if not isinstance(imputer, SimpleImputer) or not isinstance(
        scaler, StandardScaler
    ) or not isinstance(classifier, LogisticRegression):
        raise TypeError("Unsupported Moneyline model pipeline component type.")
    if imputer.strategy != "median" or not imputer.add_indicator:
        raise ValueError("Frozen Moneyline imputer contract is not supported.")
    if len(classifier.coef_) != 1 or len(classifier.intercept_) != 1:
        raise ValueError("Moneyline explanation requires binary logistic regression.")
    return imputer, scaler, classifier


def _load_stored_prediction(
    *,
    prediction_id: int,
    connection_factory: ConnectionFactory,
) -> StoredMoneylinePredictionExplanationInput:
    connection = connection_factory()
    try:
        connection.set_session(readonly=True)
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    prediction.moneyline_game_prediction_id,
                    prediction.moneyline_prediction_run_id,
                    prediction.game_id,
                    prediction.mlb_game_id,
                    prediction.game_start_time,
                    prediction.prediction_time,
                    prediction.home_team_id,
                    prediction.away_team_id,
                    home_team.team_name,
                    away_team.team_name,
                    prediction.predicted_team_id,
                    prediction.predicted_probability,
                    prediction.home_starting_pitcher_id,
                    prediction.away_starting_pitcher_id,
                    prediction.home_starting_pitcher_mlb_id,
                    prediction.away_starting_pitcher_mlb_id,
                    home_pitcher.full_name,
                    away_pitcher.full_name,
                    prediction.missing_raw_value_count,
                    prediction.home_win_probability,
                    run.model_version,
                    run.feature_schema_version,
                    run.model_artifact_sha256,
                    run.model_training_cutoff,
                    run.status,
                    game.game_date,
                    game.home_team_id,
                    game.away_team_id
                FROM moneyline_game_predictions AS prediction
                JOIN moneyline_prediction_runs AS run
                  ON run.moneyline_prediction_run_id =
                     prediction.moneyline_prediction_run_id
                JOIN games AS game ON game.game_id = prediction.game_id
                JOIN teams AS home_team
                  ON home_team.team_id = prediction.home_team_id
                JOIN teams AS away_team
                  ON away_team.team_id = prediction.away_team_id
                LEFT JOIN baseball_players AS home_pitcher
                  ON home_pitcher.baseball_player_id =
                     prediction.home_starting_pitcher_id
                LEFT JOIN baseball_players AS away_pitcher
                  ON away_pitcher.baseball_player_id =
                     prediction.away_starting_pitcher_id
                WHERE prediction.moneyline_game_prediction_id = %s;
                """,
                (prediction_id,),
            )
            row = cursor.fetchone()
        if row is None:
            raise LookupError(f"Moneyline prediction {prediction_id} was not found.")
        if row[24] != "completed":
            raise ValueError("Moneyline prediction run must be completed.")
        if row[25] != row[4] or row[26] != row[6] or row[27] != row[7]:
            raise RuntimeError(
                "Canonical game identity no longer matches the stored prediction."
            )
        if row[10] == row[6]:
            predicted_team_name = row[8]
            opponent_team_id = row[7]
            opponent_team_name = row[9]
        elif row[10] == row[7]:
            predicted_team_name = row[9]
            opponent_team_id = row[6]
            opponent_team_name = row[8]
        else:
            raise RuntimeError(
                "Stored predicted team is not part of the prediction matchup."
            )
        return StoredMoneylinePredictionExplanationInput(
            prediction_id=row[0],
            prediction_run_id=row[1],
            game_id=row[2],
            mlb_game_id=row[3],
            game_start_time=row[4],
            prediction_time=row[5],
            home_team_id=row[6],
            away_team_id=row[7],
            home_team_name=row[8],
            away_team_name=row[9],
            predicted_team_id=row[10],
            predicted_team_name=predicted_team_name,
            opponent_team_id=opponent_team_id,
            opponent_team_name=opponent_team_name,
            home_starting_pitcher_id=row[12],
            away_starting_pitcher_id=row[13],
            home_starting_pitcher_mlb_id=row[14],
            away_starting_pitcher_mlb_id=row[15],
            home_starting_pitcher_name=row[16],
            away_starting_pitcher_name=row[17],
            persisted_missing_raw_value_count=row[18],
            stored_home_win_probability=row[19],
            stored_predicted_probability=row[11],
            model_version=row[20],
            feature_schema_version=row[21],
            model_artifact_sha256=row[22],
            model_training_cutoff=row[23],
        )
    finally:
        connection.close()


def _load_and_validate_associated_model(
    *,
    stored: StoredMoneylinePredictionExplanationInput,
    model_root: Path,
    model_package_loader: ModelPackageLoader,
) -> LoadedMoneylineModelPackage:
    resolved_root = model_root.resolve()
    model_directory = (resolved_root / stored.model_version).resolve()
    if model_directory.parent != resolved_root:
        raise ValueError("Stored model version does not identify a safe model path.")
    package = model_package_loader(model_directory)
    if (
        package.model_version != stored.model_version
        or package.feature_schema_version != stored.feature_schema_version
        or package.model_artifact_sha256 != stored.model_artifact_sha256
        or package.model_training_cutoff != stored.model_training_cutoff
    ):
        raise RuntimeError(
            "Frozen model package identity does not match the prediction run."
        )
    return package


def _build_read_only_feature_service(
    connection_factory: ConnectionFactory,
) -> FeatureGenerationService:
    read_only_factory = _read_only_connection_factory(connection_factory)
    return FeatureGenerationService(
        team_statistics_repository=PostgresTeamStatisticsRepository(
            connection_factory=read_only_factory
        ),
        pitcher_statistics_repository=PostgresPitcherStatisticsRepository(
            connection_factory=read_only_factory
        ),
        bullpen_statistics_repository=PostgresBullpenStatisticsRepository(
            connection_factory=read_only_factory
        ),
    )


def _read_only_connection_factory(
    connection_factory: ConnectionFactory,
) -> ConnectionFactory:
    def connect() -> Any:
        connection = connection_factory()
        connection.set_session(readonly=True)
        return connection

    return connect


def _validate_positive_identifier(value: int) -> None:
    if isinstance(value, bool) or value <= 0:
        raise ValueError("Prediction ID must be greater than zero.")


def _sigmoid(value: float) -> float:
    if value >= 0:
        return 1.0 / (1.0 + exp(-value))
    exponent = exp(value)
    return exponent / (1.0 + exponent)
