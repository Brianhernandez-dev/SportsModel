from __future__ import annotations

import argparse
from datetime import datetime

from sportsmodel.nfl.moneyline_forward_evaluation import (
    NFLForwardEvaluationGroup,
    NFLForwardMetricConfidenceIntervals,
    NFLForwardProbabilityMetrics,
    NFLMoneylineForwardEvaluationReport,
    evaluate_nfl_moneyline_forward,
)
from sportsmodel.nfl.moneyline_prediction import (
    NFL_MONEYLINE_EVALUATION_PROTOCOL_VERSION,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Read-only evaluation of immutable NFL forward predictions."
    )
    parser.add_argument("--season", required=True, type=int)
    parser.add_argument(
        "--protocol",
        default=NFL_MONEYLINE_EVALUATION_PROTOCOL_VERSION,
    )
    parser.add_argument("--slate-start", type=_utc_datetime)
    parser.add_argument("--slate-end", type=_utc_datetime)
    parser.add_argument("--route", choices=("early", "mature"))
    parser.add_argument(
        "--preview",
        action="store_true",
        help="Report preview observations instead of official evidence.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    report = evaluate_nfl_moneyline_forward(
        season=arguments.season,
        protocol_version=arguments.protocol,
        run_type="preview" if arguments.preview else "official",
        slate_start_time=arguments.slate_start,
        slate_end_time=arguments.slate_end,
        route=arguments.route,
    )
    print(format_nfl_moneyline_forward_report(report))
    return 0


def format_nfl_moneyline_forward_report(
    report: NFLMoneylineForwardEvaluationReport,
) -> str:
    lines = [
        "NFL MONEYLINE FORWARD EVALUATION (READ ONLY)",
        f"season={report.season} protocol={report.protocol_version} "
        f"run_type={report.run_type} route={report.route_filter or 'all'}",
        f"slate_start={_datetime_text(report.slate_start_time)} "
        f"slate_end={_datetime_text(report.slate_end_time)}",
        f"run_keys={','.join(report.run_keys) or 'none'}",
        "prediction_set_sha256s="
        f"{','.join(report.prediction_set_sha256s) or 'none'}",
        "model_versions="
        f"{','.join(report.model_specification_versions) or 'none'}",
        f"model_fingerprints={','.join(report.model_fingerprints) or 'none'}",
        "routing_distribution "
        f"total={report.route_distribution.total} "
        f"early={report.route_distribution.early_count} "
        f"early_pct={_number(report.route_distribution.early_percentage)} "
        f"mature={report.route_distribution.mature_count} "
        f"mature_pct={_number(report.route_distribution.mature_percentage)}",
        _format_group(report.overall),
    ]
    lines.extend(_format_group(group) for group in report.routes)
    lines.extend(
        _format_group(group)
        for group in report.early_history_groups
        if group.total
    )
    return "\n".join(lines)


def _format_group(group: NFLForwardEvaluationGroup) -> str:
    return (
        f"[{group.label}] total={group.total} resolved={group.resolved} "
        f"pending={group.pending} ties_excluded={group.ties_excluded} "
        f"model({_format_metrics(group.model)}) "
        f"baseline({_format_metrics(group.baseline)}) "
        f"model_minus_baseline_accuracy={_number(group.accuracy_difference)} "
        f"model_minus_baseline_log_loss={_number(group.log_loss_difference)} "
        f"model_minus_baseline_brier={_number(group.brier_difference)} "
        f"model_95ci={_format_intervals(group.model_confidence_intervals)} "
        "model_minus_baseline_95ci="
        f"{_format_intervals(group.difference_confidence_intervals)}"
    )


def _format_metrics(metrics: NFLForwardProbabilityMetrics) -> str:
    return (
        f"n={metrics.count} accuracy={_number(metrics.accuracy)} "
        f"log_loss={_number(metrics.log_loss)} "
        f"brier={_number(metrics.brier_score)} "
        f"auc={_number(metrics.roc_auc)} "
        f"predicted_mean={_number(metrics.mean_home_win_probability)} "
        f"actual_home_rate={_number(metrics.actual_home_win_rate)} "
        f"ece={_number(metrics.expected_calibration_error)}"
    )


def _number(value: float | None) -> str:
    return "NA" if value is None else f"{value:.6f}"


def _format_intervals(
    intervals: NFLForwardMetricConfidenceIntervals | None,
) -> str:
    if intervals is None:
        return "NA"
    return (
        f"accuracy[{_number(intervals.accuracy.lower)},"
        f"{_number(intervals.accuracy.upper)}];"
        f"log_loss[{_number(intervals.log_loss.lower)},"
        f"{_number(intervals.log_loss.upper)}];"
        f"brier[{_number(intervals.brier_score.lower)},"
        f"{_number(intervals.brier_score.upper)}]"
    )


def _datetime_text(value: datetime | None) -> str:
    return "none" if value is None else value.isoformat()


def _utc_datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be an ISO-8601 timestamp") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise argparse.ArgumentTypeError("must include an explicit UTC offset")
    if parsed.utcoffset().total_seconds() != 0:
        raise argparse.ArgumentTypeError("must use UTC (+00:00 or Z)")
    return parsed
