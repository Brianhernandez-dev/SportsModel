"""Dry-run-first CLI for one official NFL Moneyline market evaluation."""

from __future__ import annotations

import argparse

from sportsmodel.nfl.manual_market_evaluation import (
    ManualMarketEvaluationGuardError,
    ManualMarketEvaluationResult,
    execute_manual_market_evaluation,
)
from sportsmodel.nfl.market_evaluation import (
    OfficialMarketEvaluationConflictError,
    OfficialMarketEvaluationError,
    OfficialMarketEvaluationPreview,
)


EXIT_LIVE_SUCCESS = 0
EXIT_INVALID_OPERATOR_ARGUMENTS = 2
EXIT_DRY_RUN_ELIGIBLE = 10
EXIT_PROTOCOL_INELIGIBLE = 20
EXIT_INSUFFICIENT_MARKET_COVERAGE = 21
EXIT_SOURCE_GRAPH_CONFLICT = 22
EXIT_DATABASE_OR_INFRASTRUCTURE_FAILURE = 30


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Preview or deliberately create one official NFL Moneyline market "
            "evaluation from already-persisted evidence. Default: read-only."
        )
    )
    parser.add_argument(
        "--prediction-id",
        required=True,
        type=_positive_identifier,
        help="Persisted nfl_moneyline_game_prediction_id.",
    )
    parser.add_argument(
        "--odds-run-id",
        required=True,
        type=_positive_identifier,
        help="Persisted completed NFL entry odds_ingestion_run_id.",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Opt in to creating immutable official evaluation evidence.",
    )
    parser.add_argument(
        "--confirm-create-evaluation",
        action="store_true",
        help="Second required acknowledgement for a live evaluation write.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    try:
        result = execute_manual_market_evaluation(
            prediction_id=arguments.prediction_id,
            odds_ingestion_run_id=arguments.odds_run_id,
            live=arguments.live,
            confirm_create_evaluation=(
                arguments.confirm_create_evaluation
            ),
        )
    except ManualMarketEvaluationGuardError as error:
        _print_failure(
            mode="LIVE GUARD",
            code="invalid_operator_arguments",
            message=str(error),
            writes="ZERO",
        )
        return EXIT_INVALID_OPERATOR_ARGUMENTS
    except OfficialMarketEvaluationConflictError as error:
        _print_failure(
            mode=_mode(arguments.live),
            code=error.code,
            message=str(error),
            writes=_failure_write_summary(arguments.live, error),
        )
        return EXIT_SOURCE_GRAPH_CONFLICT
    except OfficialMarketEvaluationError as error:
        _print_failure(
            mode=_mode(arguments.live),
            code=error.code,
            message=str(error),
            writes=_failure_write_summary(arguments.live, error),
        )
        if error.code == "insufficient_coverage":
            return EXIT_INSUFFICIENT_MARKET_COVERAGE
        if error.code in {"schema_incompatible", "persistence_error"}:
            return EXIT_DATABASE_OR_INFRASTRUCTURE_FAILURE
        return EXIT_PROTOCOL_INELIGIBLE
    except Exception as error:
        _print_failure(
            mode=_mode(arguments.live),
            code="database_or_infrastructure_failure",
            message=(
                "Unexpected database/infrastructure failure "
                f"({type(error).__name__}); inspect protected operator logs."
            ),
            writes="UNKNOWN - VERIFY DATABASE STATE",
        )
        return EXIT_DATABASE_OR_INFRASTRUCTURE_FAILURE

    _print_result(result)
    return (
        EXIT_DRY_RUN_ELIGIBLE
        if result.dry_run
        else EXIT_LIVE_SUCCESS
    )


def _print_result(result: ManualMarketEvaluationResult) -> None:
    preview = result.preview
    print("=" * 72)
    print("SportsModel NFL Official Market Evaluation")
    print("=" * 72)
    print(f"MODE: {'DRY RUN - READ ONLY' if result.dry_run else 'LIVE WRITE'}")
    print("ELIGIBILITY: PASS")
    print("Provider calls: ZERO")
    print(f"Database writes: {'ZERO' if result.dry_run else 'AUTHORIZED'}")
    print(
        f"Prediction: id={preview.prediction_id} "
        f"run_id={preview.prediction_run_id}"
    )
    print(
        f"Route/model: {preview.selected_route} / "
        f"{preview.model_specification_version}"
    )
    print(f"Feature schema: {preview.feature_schema_version}")
    print(f"Routing contract: {preview.routing_contract_version}")
    print(
        f"Canonical game: id={preview.game_id} "
        f"{preview.away_team_abbreviation}({preview.away_team_id}) at "
        f"{preview.home_team_abbreviation}({preview.home_team_id})"
    )
    print(
        f"Selected team: {preview.selected_team_abbreviation}"
        f"({preview.selected_team_id}) side={preview.selected_side}"
    )
    print(f"Stored model probability: {preview.selected_model_probability}")
    print(f"Prediction time: {preview.prediction_created_at.isoformat()}")
    print(f"Odds run ID: {preview.odds_ingestion_run_id}")
    print(f"Odds request time: {preview.request_started_at.isoformat()}")
    print(f"Trusted receipt time: {preview.response_received_at.isoformat()}")
    print(
        "Prediction-to-receipt gap seconds: "
        f"{preview.prediction_to_receipt_seconds}"
    )
    print(f"Kickoff: {preview.kickoff.isoformat()}")
    print(f"Contributor count: {preview.contributor_count}")
    print(f"Excluded providers: {_format_exclusions(preview)}")
    print(
        "Consensus selected probability: "
        f"{preview.consensus_no_vig_selected_probability}"
    )
    print(
        "Best price/provider: "
        f"{preview.best_american_price} / "
        f"{preview.best_price_provider.provider_bookmaker_key}"
        f"({preview.best_price_provider.provider_identity_id})"
    )
    print(f"Market edge: {preview.market_edge}")
    print(f"Model EV: {preview.model_expected_value}")
    print(f"Source graph SHA-256: {preview.source_graph_fingerprint}")
    print(
        "Market protocol: "
        f"{preview.market_evaluation_protocol_version} / "
        f"{preview.market_evaluation_protocol_fingerprint}"
    )
    print(
        "Prediction protocol: "
        f"{preview.prediction_protocol_version} / "
        f"{preview.prediction_protocol_fingerprint}"
    )
    if result.dry_run:
        action = (
            f"RETURN EXISTING evaluation_id={preview.existing_evaluation_id}"
            if preview.idempotent
            else "CREATE ONE NEW IMMUTABLE EVALUATION"
        )
        print(f"WOULD: {action}")
        print("No evaluation attempt or evidence row was created.")
        return
    execution = result.execution
    if execution is None:
        raise AssertionError("live result unexpectedly lacks execution evidence")
    print(f"Evaluation attempt ID: {execution.evaluation_run_id}")
    print(f"Evaluation ID: {execution.evaluation.evaluation_id}")
    print(f"Idempotent existing graph: {execution.idempotent}")


def _format_exclusions(preview: OfficialMarketEvaluationPreview) -> str:
    if not preview.exclusions:
        return "NONE"
    return ", ".join(
        f"{item.provider.provider_bookmaker_key}"
        f"({item.provider.provider_identity_id}):{item.reason_code}"
        for item in preview.exclusions
    )


def _print_failure(
    *,
    mode: str,
    code: str,
    message: str,
    writes: str,
) -> None:
    print("SportsModel NFL Official Market Evaluation")
    print(f"MODE: {mode}")
    print("ELIGIBILITY: FAIL")
    print(f"Failure code: {code}")
    print(f"Reason: {message}")
    print("Provider calls: ZERO")
    print(f"Database writes: {writes}")
    print("No odds recapture or provider retry was attempted.")


def _failure_write_summary(
    live: bool,
    error: OfficialMarketEvaluationError,
) -> str:
    if not live:
        return "ZERO"
    if error.evaluation_run_id is None:
        return "ZERO"
    return f"FAILED ATTEMPT ONLY (evaluation_run_id={error.evaluation_run_id})"


def _mode(live: bool) -> str:
    return "LIVE WRITE" if live else "DRY RUN - READ ONLY"


def _positive_identifier(value: str) -> int:
    try:
        identifier = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            "must be a positive integer"
        ) from error
    if identifier <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return identifier


if __name__ == "__main__":
    raise SystemExit(main())
