from __future__ import annotations

import argparse
from datetime import date, datetime
from uuid import UUID, uuid4

from sportsmodel.nfl.moneyline_prediction import (
    NFL_MONEYLINE_EVALUATION_PROTOCOL_VERSION,
    NFLMoneylinePredictionRunType,
)
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
    run_key = parser.add_mutually_exclusive_group()
    run_key.add_argument("--run-key", type=UUID)
    run_key.add_argument(
        "--generate-run-key",
        action="store_true",
        help="Generate and prominently print a new UUID for this write.",
    )
    parser.add_argument(
        "--preflight", "--dry-run", dest="dry_run", action="store_true",
        help="Run inference and official-conflict checks with zero writes.",
    )
    parser.add_argument(
        "--confirm-official",
        action="store_true",
        help="Required deliberate acknowledgement for an official write.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    if arguments.dry_run and arguments.generate_run_key:
        parser.error("--generate-run-key is only valid for persisted runs")
    if (
        not arguments.dry_run
        and arguments.run_key is None
        and not arguments.generate_run_key
    ):
        parser.error(
            "--run-key or --generate-run-key is required for persisted runs"
        )
    if arguments.confirm_official and not arguments.official:
        parser.error("--confirm-official is only valid with --official")
    if arguments.official and not arguments.dry_run and not arguments.confirm_official:
        parser.error("official writes require --confirm-official")
    run_type = (
        NFLMoneylinePredictionRunType.OFFICIAL
        if arguments.official
        else NFLMoneylinePredictionRunType.PREVIEW
    )
    run_key = uuid4() if arguments.generate_run_key else arguments.run_key
    if arguments.generate_run_key:
        print(f"GENERATED RUN KEY: {run_key}")
    try:
        result = execute_nfl_moneyline_prediction_run(
            season=arguments.season,
            target_date=arguments.target_date or arguments.slate_start.date(),
            slate_start_time=arguments.slate_start,
            slate_end_time=arguments.slate_end,
            run_type=run_type,
            run_key=run_key,
            dry_run=arguments.dry_run,
        )
    except (LookupError, ValueError) as error:
        if arguments.official and arguments.dry_run:
            print(f"BLOCKER: {error}")
            print("OFFICIAL RUN BLOCKED")
            return 2
        raise
    label = "PREFLIGHT" if result.dry_run else "PERSISTED"
    print(f"{label}: {len(result.inference_results)} NFL prediction(s)")
    print(
        "protocol="
        f"{NFL_MONEYLINE_EVALUATION_PROTOCOL_VERSION} "
        f"season={arguments.season} "
        f"slate_start={arguments.slate_start.isoformat()} "
        f"slate_end={arguments.slate_end.isoformat()}"
    )
    if result.run is not None:
        print(
            f"run_id={result.run.prediction_run_id} "
            f"run_key={result.run.run_key} status={result.run.status.value} "
            f"target_count={result.run.target_count} "
            f"prediction_count={result.run.prediction_count}"
        )
    persisted_by_game = {
        prediction.inference.game_id: prediction
        for prediction in result.predictions
    }
    team_abbreviations = dict(result.team_abbreviations)
    official_existing_game_ids = set(result.official_existing_game_ids)
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
            "away_team="
            f"{team_abbreviations.get(inference.away_team_id, inference.away_team_id)} "
            "home_team="
            f"{team_abbreviations.get(inference.home_team_id, inference.home_team_id)} "
            f"home_prior_games={inference.home_current_prior_games} "
            f"away_prior_games={inference.away_current_prior_games} "
            f"route={inference.selected_route.value} "
            f"model={inference.model_specification_version} "
            f"feature_schema={inference.feature_schema_version} "
            f"home_probability={probability:.6f} "
            f"predicted_side={predicted_side.value} "
            "official_exists="
            f"{inference.game_id in official_existing_game_ids} "
            f"feature_sha256={inference.feature_vector_fingerprint}"
        )
    print(f"slate_sha256={result.slate_fingerprint}")
    print(f"source_snapshot_sha256={result.source_snapshot_sha256}")
    print(f"prediction_set_sha256={result.prediction_set_sha256}")
    if arguments.official and result.dry_run:
        blockers = []
        if not result.inference_results:
            blockers.append("slate contains no eligible unplayed targets")
        if result.official_existing_game_ids:
            blockers.append(
                "official observations already exist for game IDs: "
                f"{result.official_existing_game_ids}"
            )
        for blocker in blockers:
            print(f"BLOCKER: {blocker}")
        print("OFFICIAL RUN BLOCKED" if blockers else "READY FOR OFFICIAL RUN")
        return 2 if blockers else 0
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
