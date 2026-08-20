"""Route-independent, fit-free NFL Moneyline forward inference."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Callable

from sportsmodel.nfl.early_features import NFLEarlyTeamFeatureBuilder
from sportsmodel.nfl.features import (
    NFLFeatureDataProvider,
    NFLGameFeatureVectorBuilder,
    NFLTeamFeatureVector,
)
from sportsmodel.nfl.models import NflGame, NflGameStatus
from sportsmodel.nfl.moneyline_frozen import (
    FrozenNFLMoneylineArtifact,
    fingerprint_payload,
    load_frozen_nfl_early_artifact,
    load_frozen_nfl_mature_artifact,
    predict_frozen_home_win_probability,
)
from sportsmodel.nfl.moneyline_routing import (
    NFL_MONEYLINE_ROUTING_CONTRACT_VERSION,
    NFLMoneylineRoute,
    select_nfl_moneyline_route,
)


class NFLPredictedSide(StrEnum):
    HOME = "home"
    AWAY = "away"


@dataclass(frozen=True)
class NFLMoneylineInferenceResult:
    game_id: int
    target_kickoff: datetime
    season: int
    home_team_id: int
    away_team_id: int
    home_current_prior_games: int
    away_current_prior_games: int
    selected_route: NFLMoneylineRoute
    routing_contract_version: str
    model_specification_version: str
    feature_schema_version: str
    specification_fingerprint: str
    model_fingerprint: str
    ordered_feature_names: tuple[str, ...]
    ordered_feature_values: tuple[float | None, ...]
    feature_vector_fingerprint: str
    feature_cutoff: datetime
    latest_source_kickoff: datetime | None
    model_home_win_probability: float
    classification_threshold: float
    predicted_side: NFLPredictedSide
    frozen_empirical_home_baseline: float


ArtifactLoader = Callable[[], FrozenNFLMoneylineArtifact]


def infer_nfl_moneyline(
    target_game: NflGame,
    *,
    provider: NFLFeatureDataProvider | None = None,
    early_artifact_loader: ArtifactLoader = load_frozen_nfl_early_artifact,
    mature_artifact_loader: ArtifactLoader = load_frozen_nfl_mature_artifact,
) -> NFLMoneylineInferenceResult:
    """Infer one 2026+ unplayed game from immutable frozen parameters."""

    return _infer_nfl_moneyline(
        target_game,
        provider=provider,
        early_artifact_loader=early_artifact_loader,
        mature_artifact_loader=mature_artifact_loader,
        require_forward_target=True,
    )


def _infer_nfl_moneyline(
    target_game: NflGame,
    *,
    provider: NFLFeatureDataProvider | None = None,
    early_artifact_loader: ArtifactLoader = load_frozen_nfl_early_artifact,
    mature_artifact_loader: ArtifactLoader = load_frozen_nfl_mature_artifact,
    require_forward_target: bool,
) -> NFLMoneylineInferenceResult:
    _validate_target(target_game, require_forward_target=require_forward_target)
    resolved_provider = provider or NFLFeatureDataProvider(target_game)
    if resolved_provider.target_game != target_game:
        raise ValueError("NFL feature provider target must match inference target")

    home_history = resolved_provider.get_team_history(
        team_id=target_game.home_team_id,
        season=target_game.season,
    )
    away_history = resolved_provider.get_team_history(
        team_id=target_game.away_team_id,
        season=target_game.season,
    )
    home_count = len(home_history)
    away_count = len(away_history)
    route = select_nfl_moneyline_route(home_count, away_count)

    source_kickoffs = [
        item.game.scheduled_start_time
        for item in (*home_history, *away_history)
    ]
    if route is NFLMoneylineRoute.EARLY:
        artifact = early_artifact_loader()
        values, additional_kickoffs = _build_early_values(
            target_game,
            resolved_provider,
        )
        source_kickoffs.extend(additional_kickoffs)
    else:
        artifact = mature_artifact_loader()
        values = _build_mature_values(target_game, resolved_provider)

    if artifact.route is not route:
        raise ValueError("selected route does not match frozen artifact route")
    if len(values) != len(artifact.feature_names):
        raise ValueError("selected feature vector dimensionality drift")

    probability = predict_frozen_home_win_probability(artifact, values)
    predicted_side = (
        NFLPredictedSide.HOME
        if probability >= artifact.classification_threshold
        else NFLPredictedSide.AWAY
    )
    normalized_values = tuple(
        None if value is None else float(value)
        for value in values
    )
    vector_fingerprint = fingerprint_payload({
        "feature_schema_version": artifact.feature_schema_version,
        "ordered_feature_names": list(artifact.feature_names),
        "ordered_feature_values": list(normalized_values),
    })
    return NFLMoneylineInferenceResult(
        game_id=target_game.game_id,
        target_kickoff=target_game.scheduled_start_time,
        season=target_game.season,
        home_team_id=target_game.home_team_id,
        away_team_id=target_game.away_team_id,
        home_current_prior_games=home_count,
        away_current_prior_games=away_count,
        selected_route=route,
        routing_contract_version=NFL_MONEYLINE_ROUTING_CONTRACT_VERSION,
        model_specification_version=artifact.specification_version,
        feature_schema_version=artifact.feature_schema_version,
        specification_fingerprint=artifact.specification_fingerprint,
        model_fingerprint=artifact.model_fingerprint,
        ordered_feature_names=artifact.feature_names,
        ordered_feature_values=normalized_values,
        feature_vector_fingerprint=vector_fingerprint,
        feature_cutoff=resolved_provider.feature_cutoff,
        latest_source_kickoff=(
            max(source_kickoffs) if source_kickoffs else None
        ),
        model_home_win_probability=probability,
        classification_threshold=artifact.classification_threshold,
        predicted_side=predicted_side,
        frozen_empirical_home_baseline=artifact.training_home_win_rate,
    )


def _build_early_values(
    target_game: NflGame,
    provider: NFLFeatureDataProvider,
) -> tuple[tuple[float | int | None, ...], list[datetime]]:
    builder = NFLEarlyTeamFeatureBuilder()
    home = builder.build(
        team_id=target_game.home_team_id,
        target_game=target_game,
        provider=provider,
    )
    away = builder.build(
        team_id=target_game.away_team_id,
        target_game=target_game,
        provider=provider,
    )
    values = (
        home.prior_season.games_played - away.prior_season.games_played,
        _difference(
            home.prior_season.win_percentage,
            away.prior_season.win_percentage,
        ),
        _difference(
            home.prior_season.average_point_differential,
            away.prior_season.average_point_differential,
        ),
        _difference(
            home.prior_season.average_turnover_differential,
            away.prior_season.average_turnover_differential,
        ),
    )
    kickoffs = list(home.prior_season.source_kickoffs)
    kickoffs.extend(away.prior_season.source_kickoffs)
    return values, kickoffs


def _build_mature_values(
    target_game: NflGame,
    provider: NFLFeatureDataProvider,
) -> tuple[float | int | None, ...]:
    vector = NFLGameFeatureVectorBuilder().build(
        target_game,
        provider=provider,
    )
    home = vector.home
    away = vector.away
    return (
        min(home.prior_games_used, away.prior_games_used),
        home.prior_games_used - away.prior_games_used,
        _attribute_difference(home, away, "win_percentage"),
        _attribute_difference(home, away, "average_points_for"),
        _attribute_difference(home, away, "average_points_against"),
        _attribute_difference(home, away, "average_passing_yards"),
        _attribute_difference(
            home, away, "average_passing_yards_allowed"
        ),
        _attribute_difference(home, away, "average_rushing_yards"),
        _attribute_difference(
            home, away, "average_rushing_yards_allowed"
        ),
        _attribute_difference(home, away, "average_turnovers"),
        _attribute_difference(home, away, "average_takeaways"),
        home.rolling_3.games_used - away.rolling_3.games_used,
        _difference(
            home.rolling_3.average_points_for,
            away.rolling_3.average_points_for,
        ),
        _difference(
            home.rolling_3.average_points_against,
            away.rolling_3.average_points_against,
        ),
        _difference(
            home.rolling_3.average_turnover_differential,
            away.rolling_3.average_turnover_differential,
        ),
        home.rolling_5.games_used - away.rolling_5.games_used,
        _difference(
            home.rolling_5.average_points_for,
            away.rolling_5.average_points_for,
        ),
        _difference(
            home.rolling_5.average_points_against,
            away.rolling_5.average_points_against,
        ),
        _difference(
            home.rolling_5.average_turnover_differential,
            away.rolling_5.average_turnover_differential,
        ),
    )


def _attribute_difference(
    home: NFLTeamFeatureVector,
    away: NFLTeamFeatureVector,
    attribute: str,
) -> float | None:
    return _difference(getattr(home, attribute), getattr(away, attribute))


def _difference(
    home: float | None,
    away: float | None,
) -> float | None:
    if home is None or away is None:
        return None
    return home - away


def _validate_target(
    target_game: NflGame,
    *,
    require_forward_target: bool,
) -> None:
    if require_forward_target and target_game.season < 2026:
        raise ValueError(
            "production NFL inference accepts only 2026+ forward targets"
        )
    if target_game.status is not NflGameStatus.UNPLAYED:
        raise ValueError("NFL inference target must be unplayed")
    kickoff = target_game.scheduled_start_time
    if kickoff.tzinfo is None or kickoff.utcoffset() is None:
        raise ValueError("NFL inference target kickoff must be timezone-aware")
