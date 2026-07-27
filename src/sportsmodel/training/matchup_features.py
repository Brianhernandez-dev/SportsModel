from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

import joblib

from sportsmodel.training.moneyline_baseline import (
    MoneylineTrainingDataset,
    MoneylineTrainingExample,
    TrainedMoneylineBaseline,
)


HOME_FEATURE_PREFIX = "home_"
AWAY_FEATURE_PREFIX = "away_"
MATCHUP_FEATURE_TRANSFORM_VERSION = "1.0.0"
MATCHUP_MODEL_ARTIFACT_FORMAT_VERSION = "1.0.0"


@dataclass(frozen=True)
class MatchupFeatureDefinition:
    """
    Definition for one transformed matchup feature.

    A paired definition subtracts the away value from the home value.
    An unpaired definition passes one source feature through unchanged.
    """

    output_name: str

    home_index: int | None = None

    away_index: int | None = None

    passthrough_index: int | None = None

    def __post_init__(self) -> None:
        if not self.output_name.strip():
            raise ValueError(
                "Matchup feature output name cannot be empty."
            )

        is_pair = (
            self.home_index is not None
            and self.away_index is not None
            and self.passthrough_index is None
        )

        is_passthrough = (
            self.home_index is None
            and self.away_index is None
            and self.passthrough_index is not None
        )

        if not is_pair and not is_passthrough:
            raise ValueError(
                "Matchup feature definition must represent either "
                "one home/away pair or one passthrough feature."
            )


@dataclass(frozen=True)
class MatchupFeatureTransformer:
    """
    Transform raw home and away features into matchup differences.

    For every matching pair:

        matchup_feature = home_feature - away_feature

    Unpaired features are preserved as passthrough values.
    """

    source_feature_names: tuple[str, ...]

    definitions: tuple[MatchupFeatureDefinition, ...]

    @property
    def output_feature_names(self) -> tuple[str, ...]:
        return tuple(
            definition.output_name
            for definition in self.definitions
        )

    @property
    def paired_feature_count(self) -> int:
        return sum(
            definition.home_index is not None
            for definition in self.definitions
        )

    @property
    def passthrough_feature_count(self) -> int:
        return sum(
            definition.passthrough_index is not None
            for definition in self.definitions
        )

    @classmethod
    def from_feature_names(
        cls,
        feature_names: tuple[str, ...],
    ) -> "MatchupFeatureTransformer":
        """
        Build a deterministic transformation from a raw feature schema.
        """

        _validate_feature_names(feature_names)

        feature_indexes = {
            feature_name: index
            for index, feature_name in enumerate(
                feature_names
            )
        }

        home_names_by_suffix = {
            feature_name.removeprefix(
                HOME_FEATURE_PREFIX
            ): feature_name
            for feature_name in feature_names
            if feature_name.startswith(
                HOME_FEATURE_PREFIX
            )
        }

        away_names_by_suffix = {
            feature_name.removeprefix(
                AWAY_FEATURE_PREFIX
            ): feature_name
            for feature_name in feature_names
            if feature_name.startswith(
                AWAY_FEATURE_PREFIX
            )
        }

        emitted_suffixes: set[str] = set()
        emitted_source_names: set[str] = set()
        definitions: list[MatchupFeatureDefinition] = []

        for feature_name in feature_names:
            feature_suffix = _get_matchup_suffix(
                feature_name
            )

            if feature_suffix is None:
                definitions.append(
                    MatchupFeatureDefinition(
                        output_name=feature_name,
                        passthrough_index=(
                            feature_indexes[feature_name]
                        ),
                    )
                )
                emitted_source_names.add(feature_name)
                continue

            if feature_suffix in emitted_suffixes:
                continue

            home_name = home_names_by_suffix.get(
                feature_suffix
            )
            away_name = away_names_by_suffix.get(
                feature_suffix
            )

            if home_name is not None and away_name is not None:
                definitions.append(
                    MatchupFeatureDefinition(
                        output_name=(
                            "matchup_"
                            f"{feature_suffix}"
                            "_difference"
                        ),
                        home_index=feature_indexes[home_name],
                        away_index=feature_indexes[away_name],
                    )
                )

                emitted_suffixes.add(feature_suffix)
                emitted_source_names.update(
                    {
                        home_name,
                        away_name,
                    }
                )
                continue

            if feature_name not in emitted_source_names:
                definitions.append(
                    MatchupFeatureDefinition(
                        output_name=feature_name,
                        passthrough_index=(
                            feature_indexes[feature_name]
                        ),
                    )
                )
                emitted_source_names.add(feature_name)

        output_names = tuple(
            definition.output_name
            for definition in definitions
        )

        if len(output_names) != len(set(output_names)):
            raise ValueError(
                "Matchup transformation produced duplicate "
                "output feature names."
            )

        return cls(
            source_feature_names=feature_names,
            definitions=tuple(definitions),
        )

    def transform_values(
        self,
        values: tuple[float | None, ...],
    ) -> tuple[float | None, ...]:
        """
        Transform one raw feature vector.
        """

        if len(values) != len(self.source_feature_names):
            raise ValueError(
                "Feature value count does not match the source "
                "feature schema."
            )

        transformed_values: list[float | None] = []

        for definition in self.definitions:
            if definition.passthrough_index is not None:
                transformed_values.append(
                    values[definition.passthrough_index]
                )
                continue

            if (
                definition.home_index is None
                or definition.away_index is None
            ):
                raise RuntimeError(
                    "Invalid paired matchup feature definition."
                )

            home_value = values[definition.home_index]
            away_value = values[definition.away_index]

            if home_value is None or away_value is None:
                transformed_values.append(None)
                continue

            transformed_values.append(
                home_value - away_value
            )

        return tuple(transformed_values)

    def transform_dataset(
        self,
        dataset: MoneylineTrainingDataset,
    ) -> MoneylineTrainingDataset:
        """
        Transform every example while preserving chronology and targets.
        """

        if dataset.feature_names != self.source_feature_names:
            raise ValueError(
                "Dataset feature schema does not match the matchup "
                "transformer source schema."
            )

        transformed_examples = tuple(
            MoneylineTrainingExample(
                game_id=example.game_id,
                game_start_time=example.game_start_time,
                home_team_won=example.home_team_won,
                feature_values=self.transform_values(
                    example.feature_values
                ),
            )
            for example in dataset.examples
        )

        return MoneylineTrainingDataset(
            feature_schema_version=(
                dataset.feature_schema_version
            ),
            feature_names=self.output_feature_names,
            examples=transformed_examples,
        )


@dataclass(frozen=True)
class TrainedMatchupMoneylineModel:
    """
    Fitted Moneyline model with its raw-to-matchup transformer.
    """

    transformer: MatchupFeatureTransformer

    model: TrainedMoneylineBaseline

    def predict_home_win_probability(
        self,
        raw_feature_values: Mapping[
            str,
            bool | int | float | None,
        ],
    ) -> float:
        """
        Predict from the normal raw home and away feature mapping.
        """

        missing_features = tuple(
            feature_name
            for feature_name
            in self.transformer.source_feature_names
            if feature_name not in raw_feature_values
        )

        if missing_features:
            raise ValueError(
                "Raw prediction feature mapping is missing "
                f"required features: {missing_features}"
            )

        source_values = tuple(
            (
                None
                if raw_feature_values[feature_name] is None
                else float(
                    raw_feature_values[feature_name]
                )
            )
            for feature_name
            in self.transformer.source_feature_names
        )

        transformed_values = (
            self.transformer.transform_values(
                source_values
            )
        )

        transformed_mapping = dict(
            zip(
                self.transformer.output_feature_names,
                transformed_values,
                strict=True,
            )
        )

        return self.model.predict_home_win_probability(
            transformed_mapping
        )


@dataclass(frozen=True)
class PersistedMatchupMoneylineModel:
    """
    Versioned serialized matchup-model artifact.
    """

    artifact_format_version: str

    model: TrainedMatchupMoneylineModel


def save_trained_matchup_moneyline_model(
    model: TrainedMatchupMoneylineModel,
    path: Path,
) -> None:
    """
    Save the fitted matchup model and transformer together.
    """

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    joblib.dump(
        PersistedMatchupMoneylineModel(
            artifact_format_version=(
                MATCHUP_MODEL_ARTIFACT_FORMAT_VERSION
            ),
            model=model,
        ),
        path,
    )


def load_trained_matchup_moneyline_model(
    path: Path,
) -> TrainedMatchupMoneylineModel:
    """
    Load and validate a persisted matchup-model artifact.
    """

    persisted_model = joblib.load(path)

    if not isinstance(
        persisted_model,
        PersistedMatchupMoneylineModel,
    ):
        raise TypeError(
            "Serialized artifact is not a persisted matchup "
            "Moneyline model."
        )

    if (
        persisted_model.artifact_format_version
        != MATCHUP_MODEL_ARTIFACT_FORMAT_VERSION
    ):
        raise ValueError(
            "Unsupported matchup-model artifact format: "
            f"{persisted_model.artifact_format_version}"
        )

    return persisted_model.model


def transform_to_matchup_difference_dataset(
    dataset: MoneylineTrainingDataset,
) -> tuple[
    MoneylineTrainingDataset,
    MatchupFeatureTransformer,
]:
    """
    Build and apply the standard matchup-difference transformation.
    """

    transformer = MatchupFeatureTransformer.from_feature_names(
        dataset.feature_names
    )

    return (
        transformer.transform_dataset(dataset),
        transformer,
    )


def _get_matchup_suffix(
    feature_name: str,
) -> str | None:
    if feature_name.startswith(HOME_FEATURE_PREFIX):
        return feature_name.removeprefix(
            HOME_FEATURE_PREFIX
        )

    if feature_name.startswith(AWAY_FEATURE_PREFIX):
        return feature_name.removeprefix(
            AWAY_FEATURE_PREFIX
        )

    return None


def _validate_feature_names(
    feature_names: tuple[str, ...],
) -> None:
    if not feature_names:
        raise ValueError(
            "At least one source feature is required."
        )

    for feature_name in feature_names:
        if not feature_name.strip():
            raise ValueError(
                "Source feature names cannot be empty."
            )

    if len(feature_names) != len(set(feature_names)):
        raise ValueError(
            "Source feature names must be unique."
        )
