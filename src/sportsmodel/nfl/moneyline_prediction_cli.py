from __future__ import annotations

import argparse
from datetime import date, datetime
from uuid import UUID

from sportsmodel.nfl.moneyline_prediction import NFLMoneylinePredictionRunType
from sportsmodel.nfl.moneyline_prediction_service import (
    execute_nfl_moneyline_prediction_run,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create immutable 2026+ NFL Moneyline predictions."
    )
    parser.add_argument("--season", required=True, type=int)
    parser.add_argument(
        "--target-date",
        type=date.fromisoformat,
        help="Operational YYYY-MM-DD label; defaults to UTC slate start date.",
    )
    parser.add_argument(
        "--slate-start", required=True, type=_utc_datetime,
        help="Inclusive UTC ISO-8601 slate start.",
    )
    parser.add_argument(
        "--slate-end", required=True, type=_utc_datetime,
        help="Exclusive UTC ISO-8601 slate end.",
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--official", action="store_true")
    mode.add_argument("--preview", action="store_true")
    parser.add_argument("--run-key", type=UUID)
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    if not arguments.dry_run and arguments.run_key is None:
        parser.error("--run-key is required unless --dry-run is used")
    run_type = (
        NFLMoneylinePredictionRunType.OFFICIAL
        if arguments.official
        else NFLMoneylinePredictionRunType.PREVIEW
    )
    result = execute_nfl_moneyline_prediction_run(
        season=arguments.season,
        target_date=arguments.target_date or arguments.slate_start.date(),
        slate_start_time=arguments.slate_start,
        slate_end_time=arguments.slate_end,
        run_type=run_type,
        run_key=arguments.run_key,
        dry_run=arguments.dry_run,
    )
    label = "DRY RUN" if result.dry_run else "PERSISTED"
    print(f"{label}: {len(result.inference_results)} NFL prediction(s)")
    if result.run is not None:
        print(
            f"run_id={result.run.prediction_run_id} "
            f"run_key={result.run.run_key} status={result.run.status.value}"
        )
    persisted_by_game = {
        prediction.inference.game_id: prediction
        for prediction in result.predictions
    }
    for inference in result.inference_results:
        persisted = persisted_by_game.get(inference.game_id)
        probability = (
            persisted.model_home_win_probability
            if persisted is not None
            else inference.model_home_win_probability
        )
        predicted_side = (
            persisted.predicted_side
            if persisted is not None
            else inference.predicted_side
        )
        print(
            f"game_id={inference.game_id} "
            f"kickoff={inference.target_kickoff.isoformat()} "
            f"route={inference.selected_route.value} "
            f"home_probability={probability:.6f} "
            f"predicted_side={predicted_side.value} "
            f"feature_sha256={inference.feature_vector_fingerprint}"
        )
    print(f"slate_sha256={result.slate_fingerprint}")
    print(f"source_snapshot_sha256={result.source_snapshot_sha256}")
    print(f"prediction_set_sha256={result.prediction_set_sha256}")
    return 0


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
