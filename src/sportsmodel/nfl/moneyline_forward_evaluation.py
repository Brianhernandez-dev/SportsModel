from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import math
from random import Random
from statistics import fmean
from typing import Any, Callable

from sklearn.metrics import roc_auc_score

from sportsmodel.database.connection import get_connection
from sportsmodel.database.nfl_moneyline_forward_evaluation_repository import (
    NFLMoneylineForwardEvidence,
    list_nfl_moneyline_forward_evidence,
)
from sportsmodel.nfl.moneyline_prediction import (
    NFL_MONEYLINE_EVALUATION_PROTOCOL_VERSION,
)


ConnectionFactory = Callable[[], Any]
NFL_FORWARD_CALIBRATION_BIN_COUNT = 10
NFL_FORWARD_BOOTSTRAP_ITERATIONS = 500
NFL_FORWARD_BOOTSTRAP_SEED = 20260820
_LOG_EPSILON = 1e-15


@dataclass(frozen=True)
class NFLForwardCalibrationBin:
    lower: float
    upper: float
    count: int
    mean_probability: float
    actual_home_win_rate: float


@dataclass(frozen=True)
class NFLForwardProbabilityMetrics:
    count: int
    accuracy: float | None
    log_loss: float | None
    brier_score: float | None
    roc_auc: float | None
    mean_home_win_probability: float | None
    actual_home_win_rate: float | None
    expected_calibration_error: float | None
    calibration_bins: tuple[NFLForwardCalibrationBin, ...]


@dataclass(frozen=True)
class NFLForwardConfidenceInterval:
    lower: float
    upper: float


@dataclass(frozen=True)
class NFLForwardMetricConfidenceIntervals:
    accuracy: NFLForwardConfidenceInterval
    log_loss: NFLForwardConfidenceInterval
    brier_score: NFLForwardConfidenceInterval
    roc_auc: NFLForwardConfidenceInterval | None


@dataclass(frozen=True)
class NFLForwardEvaluationGroup:
    label: str
    total: int
    resolved: int
    pending: int
    ties_excluded: int
    model: NFLForwardProbabilityMetrics
    baseline: NFLForwardProbabilityMetrics
    accuracy_difference: float | None
    log_loss_difference: float | None
    brier_difference: float | None
    model_confidence_intervals: NFLForwardMetricConfidenceIntervals | None
    difference_confidence_intervals: NFLForwardMetricConfidenceIntervals | None


@dataclass(frozen=True)
class NFLForwardRouteDistribution:
    total: int
    early_count: int
    mature_count: int
    early_percentage: float | None
    mature_percentage: float | None


@dataclass(frozen=True)
class NFLMoneylineForwardEvaluationReport:
    season: int
    protocol_version: str
    run_type: str
    slate_start_time: datetime | None
    slate_end_time: datetime | None
    route_filter: str | None
    run_keys: tuple[str, ...]
    prediction_set_sha256s: tuple[str, ...]
    model_specification_versions: tuple[str, ...]
    model_fingerprints: tuple[str, ...]
    route_distribution: NFLForwardRouteDistribution
    overall: NFLForwardEvaluationGroup
    routes: tuple[NFLForwardEvaluationGroup, ...]
    early_history_groups: tuple[NFLForwardEvaluationGroup, ...]


def evaluate_nfl_moneyline_forward(
    *,
    season: int,
    protocol_version: str = NFL_MONEYLINE_EVALUATION_PROTOCOL_VERSION,
    run_type: str = "official",
    slate_start_time: datetime | None = None,
    slate_end_time: datetime | None = None,
    route: str | None = None,
    connection_factory: ConnectionFactory = get_connection,
) -> NFLMoneylineForwardEvaluationReport:
    _validate_filters(
        season=season,
        protocol_version=protocol_version,
        run_type=run_type,
        slate_start_time=slate_start_time,
        slate_end_time=slate_end_time,
        route=route,
    )
    connection = connection_factory()
    try:
        connection.set_session(
            isolation_level="REPEATABLE READ",
            readonly=True,
        )
        with connection.cursor() as cursor:
            evidence = list_nfl_moneyline_forward_evidence(
                cursor,
                season=season,
                protocol_version=protocol_version,
                run_type=run_type,
                slate_start_time=slate_start_time,
                slate_end_time=slate_end_time,
                route=route,
            )
        connection.rollback()
    finally:
        connection.close()

    for item in evidence:
        _validate_evidence(item)
    routes = tuple(
        _evaluate_group(name, tuple(item for item in evidence if item.route == name))
        for name in ("early", "mature")
        if route is None or route == name
    )
    early = tuple(item for item in evidence if item.route == "early")
    early_history_groups = tuple(
        _evaluate_group(
            f"early_min_prior_{prior}",
            tuple(
                item for item in early
                if min(item.home_prior_games, item.away_prior_games) == prior
            ),
        )
        for prior in range(3)
    )
    return NFLMoneylineForwardEvaluationReport(
        season=season,
        protocol_version=protocol_version,
        run_type=run_type,
        slate_start_time=slate_start_time,
        slate_end_time=slate_end_time,
        route_filter=route,
        run_keys=tuple(sorted({str(item.run_key) for item in evidence})),
        prediction_set_sha256s=tuple(sorted({
            item.prediction_set_sha256 for item in evidence
        })),
        model_specification_versions=tuple(sorted({
            item.model_specification_version for item in evidence
        })),
        model_fingerprints=tuple(sorted({
            item.model_fingerprint for item in evidence
        })),
        route_distribution=_route_distribution(evidence),
        overall=_evaluate_group("combined", evidence),
        routes=routes,
        early_history_groups=early_history_groups,
    )


def _route_distribution(
    evidence: tuple[NFLMoneylineForwardEvidence, ...],
) -> NFLForwardRouteDistribution:
    total = len(evidence)
    early_count = sum(item.route == "early" for item in evidence)
    mature_count = sum(item.route == "mature" for item in evidence)
    return NFLForwardRouteDistribution(
        total=total,
        early_count=early_count,
        mature_count=mature_count,
        early_percentage=(100 * early_count / total if total else None),
        mature_percentage=(100 * mature_count / total if total else None),
    )


def _evaluate_group(
    label: str,
    evidence: tuple[NFLMoneylineForwardEvidence, ...],
) -> NFLForwardEvaluationGroup:
    resolved = tuple(
        item for item in evidence
        if item.game_status == "final" and item.home_score != item.away_score
    )
    ties = sum(
        item.game_status == "final" and item.home_score == item.away_score
        for item in evidence
    )
    pending = len(evidence) - len(resolved) - ties
    targets = tuple(item.home_score > item.away_score for item in resolved)
    model_probabilities = tuple(float(item.home_win_probability) for item in resolved)
    baseline_probabilities = tuple(
        float(item.baseline_home_win_probability) for item in resolved
    )
    thresholds = tuple(float(item.classification_threshold) for item in resolved)
    model = _metrics(targets, model_probabilities, thresholds)
    baseline = _metrics(targets, baseline_probabilities, thresholds)
    model_intervals, difference_intervals = _bootstrap_intervals(
        targets,
        model_probabilities,
        baseline_probabilities,
        thresholds,
    )
    return NFLForwardEvaluationGroup(
        label=label,
        total=len(evidence),
        resolved=len(resolved),
        pending=pending,
        ties_excluded=ties,
        model=model,
        baseline=baseline,
        accuracy_difference=_difference(model.accuracy, baseline.accuracy),
        log_loss_difference=_difference(model.log_loss, baseline.log_loss),
        brier_difference=_difference(model.brier_score, baseline.brier_score),
        model_confidence_intervals=model_intervals,
        difference_confidence_intervals=difference_intervals,
    )


def _metrics(
    targets: tuple[bool, ...],
    probabilities: tuple[float, ...],
    thresholds: tuple[float, ...],
) -> NFLForwardProbabilityMetrics:
    count = len(targets)
    if not count:
        return NFLForwardProbabilityMetrics(
            count=0,
            accuracy=None,
            log_loss=None,
            brier_score=None,
            roc_auc=None,
            mean_home_win_probability=None,
            actual_home_win_rate=None,
            expected_calibration_error=None,
            calibration_bins=(),
        )
    labels = tuple(1.0 if value else 0.0 for value in targets)
    bins = _calibration_bins(labels, probabilities)
    accuracy, log_loss_value, brier, auc = _raw_metric_values(
        targets, probabilities, thresholds
    )
    return NFLForwardProbabilityMetrics(
        count=count,
        accuracy=accuracy,
        log_loss=log_loss_value,
        brier_score=brier,
        roc_auc=auc,
        mean_home_win_probability=fmean(probabilities),
        actual_home_win_rate=fmean(labels),
        expected_calibration_error=sum(
            item.count / count
            * abs(item.mean_probability - item.actual_home_win_rate)
            for item in bins
        ),
        calibration_bins=bins,
    )


def _raw_metric_values(
    targets: tuple[bool, ...],
    probabilities: tuple[float, ...],
    thresholds: tuple[float, ...],
) -> tuple[float, float, float, float | None]:
    count = len(targets)
    labels = tuple(1.0 if value else 0.0 for value in targets)
    predictions = tuple(
        probability >= threshold
        for probability, threshold in zip(probabilities, thresholds, strict=True)
    )
    bounded = tuple(
        min(max(probability, _LOG_EPSILON), 1 - _LOG_EPSILON)
        for probability in probabilities
    )
    auc = None
    if len(set(targets)) == 2:
        auc = float(roc_auc_score(targets, probabilities))
    return (
        sum(a == b for a, b in zip(predictions, targets, strict=True)) / count,
        -sum(
            label * math.log(probability)
            + (1 - label) * math.log(1 - probability)
            for label, probability in zip(labels, bounded, strict=True)
        ) / count,
        sum(
            (probability - label) ** 2
            for probability, label in zip(probabilities, labels, strict=True)
        ) / count,
        auc,
    )


def _bootstrap_intervals(
    targets: tuple[bool, ...],
    model_probabilities: tuple[float, ...],
    baseline_probabilities: tuple[float, ...],
    thresholds: tuple[float, ...],
) -> tuple[
    NFLForwardMetricConfidenceIntervals | None,
    NFLForwardMetricConfidenceIntervals | None,
]:
    if not targets:
        return None, None
    random = Random(NFL_FORWARD_BOOTSTRAP_SEED)
    indexes = tuple(range(len(targets)))
    model_samples = []
    difference_samples = []
    for _ in range(NFL_FORWARD_BOOTSTRAP_ITERATIONS):
        sampled = tuple(random.choice(indexes) for _ in indexes)
        sample_targets = tuple(targets[index] for index in sampled)
        sample_thresholds = tuple(thresholds[index] for index in sampled)
        model = _raw_metric_values(
            sample_targets,
            tuple(model_probabilities[index] for index in sampled),
            sample_thresholds,
        )
        baseline = _raw_metric_values(
            sample_targets,
            tuple(baseline_probabilities[index] for index in sampled),
            sample_thresholds,
        )
        model_samples.append(model)
        difference_samples.append(tuple(
            model[index] - baseline[index] for index in range(3)
        ))
    auc_values = [item[3] for item in model_samples if item[3] is not None]
    return (
        NFLForwardMetricConfidenceIntervals(
            accuracy=_interval([item[0] for item in model_samples]),
            log_loss=_interval([item[1] for item in model_samples]),
            brier_score=_interval([item[2] for item in model_samples]),
            roc_auc=_interval(auc_values) if auc_values else None,
        ),
        NFLForwardMetricConfidenceIntervals(
            accuracy=_interval([item[0] for item in difference_samples]),
            log_loss=_interval([item[1] for item in difference_samples]),
            brier_score=_interval([item[2] for item in difference_samples]),
            roc_auc=None,
        ),
    )


def _interval(values: list[float]) -> NFLForwardConfidenceInterval:
    ordered = sorted(values)
    return NFLForwardConfidenceInterval(
        lower=_percentile(ordered, 0.025),
        upper=_percentile(ordered, 0.975),
    )


def _percentile(ordered: list[float], quantile: float) -> float:
    position = quantile * (len(ordered) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _calibration_bins(
    labels: tuple[float, ...], probabilities: tuple[float, ...],
) -> tuple[NFLForwardCalibrationBin, ...]:
    result = []
    for index in range(NFL_FORWARD_CALIBRATION_BIN_COUNT):
        lower = index / NFL_FORWARD_CALIBRATION_BIN_COUNT
        upper = (index + 1) / NFL_FORWARD_CALIBRATION_BIN_COUNT
        values = tuple(
            (label, probability)
            for label, probability in zip(labels, probabilities, strict=True)
            if lower <= probability < upper
            or (index == NFL_FORWARD_CALIBRATION_BIN_COUNT - 1 and probability == 1)
        )
        if values:
            result.append(NFLForwardCalibrationBin(
                lower=lower,
                upper=upper,
                count=len(values),
                mean_probability=fmean(item[1] for item in values),
                actual_home_win_rate=fmean(item[0] for item in values),
            ))
    return tuple(result)


def _validate_evidence(item: NFLMoneylineForwardEvidence) -> None:
    problems = []
    if item.prediction_created_at >= item.target_kickoff:
        problems.append("prediction was not created strictly before kickoff")
    if item.target_kickoff != item.canonical_kickoff:
        problems.append("canonical kickoff differs from prediction evidence")
    if (
        item.home_team_id != item.canonical_home_team_id
        or item.away_team_id != item.canonical_away_team_id
    ):
        problems.append("canonical team identity differs from prediction evidence")
    expected_side = (
        "home"
        if item.home_win_probability >= item.classification_threshold
        else "away"
    )
    if item.predicted_side != expected_side:
        problems.append("predicted side differs from persisted probability")
    if item.game_status == "final" and (
        item.home_score is None or item.away_score is None
    ):
        problems.append("final canonical game has missing scores")
    if problems:
        raise ValueError(
            f"invalid NFL prediction evidence {item.prediction_id}: "
            + "; ".join(problems)
        )


def _validate_filters(
    *, season: int, protocol_version: str, run_type: str,
    slate_start_time: datetime | None, slate_end_time: datetime | None,
    route: str | None,
) -> None:
    if isinstance(season, bool) or season < 2026:
        raise ValueError("NFL forward evaluation season must be 2026 or later")
    if not protocol_version.strip():
        raise ValueError("protocol version is required")
    if run_type not in {"official", "preview"}:
        raise ValueError("run type must be official or preview")
    if route not in {None, "early", "mature"}:
        raise ValueError("route must be early or mature")
    for value in (slate_start_time, slate_end_time):
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("slate filters must be timezone-aware")
    if (
        slate_start_time is not None
        and slate_end_time is not None
        and slate_start_time >= slate_end_time
    ):
        raise ValueError("slate start must be before slate end")


def _difference(left: float | None, right: float | None) -> float | None:
    return None if left is None or right is None else left - right
