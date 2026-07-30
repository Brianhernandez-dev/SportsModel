import argparse

from sportsmodel.auditing.moneyline_live_pipeline import (
    audit_moneyline_live_pipeline,
)


def main(
    argv: list[str] | None = None,
) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)

    try:
        audit = audit_moneyline_live_pipeline(
            prediction_run_id=(
                arguments.prediction_run_id
            ),
            odds_ingestion_run_id=(
                arguments.odds_run_id
            ),
            policy_version=(
                arguments.policy_version
            ),
        )
    except Exception as error:
        print(
            "Moneyline live pipeline audit failed: "
            f"{type(error).__name__}: {error}"
        )
        return 1

    print("=" * 88)
    print(
        "SportsModel MLB Moneyline "
        "Live Pipeline Audit"
    )
    print("=" * 88)
    print(
        f"Prediction run ID:    "
        f"{audit.prediction_run_id}"
    )
    print(
        f"Prediction status:    "
        f"{audit.prediction_run_status}"
    )
    print(
        f"Odds run ID:          "
        f"{audit.odds_ingestion_run_id}"
    )
    print(
        f"Odds status:          "
        f"{audit.odds_ingestion_run_status}"
    )
    print(
        f"Policy version:       "
        f"{audit.policy_version}"
    )
    print()
    print(
        f"Predictions:          "
        f"{audit.predictions}"
    )
    print(
        f"Prediction games:     "
        f"{audit.prediction_games}"
    )
    print(
        f"Odds snapshots:       "
        f"{audit.odds_snapshots}"
    )
    print(
        f"Odds games:           "
        f"{audit.odds_games}"
    )
    print(
        f"Evaluations:          "
        f"{audit.evaluations}"
    )
    print(
        f"Evaluated predictions:"
        f" {audit.evaluated_predictions}"
    )
    print(
        f"Paper candidates:     "
        f"{audit.paper_candidates}"
    )
    print(
        f"Settlements:          "
        f"{audit.settlements}"
    )
    print(
        f"Pending candidates:   "
        f"{audit.pending_candidates}"
    )
    print()
    print(
        f"Duplicate games:      "
        f"{audit.duplicate_prediction_games}"
    )
    print(
        f"Duplicate evaluations:"
        f" {audit.duplicate_evaluations}"
    )
    print(
        f"Duplicate settlements:"
        f" {audit.duplicate_settlements}"
    )
    print()
    print(
        f"Pipeline state:       "
        f"{audit.pipeline_state}"
    )

    if audit.integrity_issues:
        print(
            "Integrity issues:     "
            + ", ".join(
                audit.integrity_issues
            )
        )
    else:
        print(
            "Integrity issues:     None"
        )

    if audit.pipeline_state == "invalid":
        return 1

    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Audit one stored MLB Moneyline "
            "prediction-to-settlement pipeline."
        )
    )

    parser.add_argument(
        "--prediction-run-id",
        type=_parse_positive_integer,
        required=True,
    )

    parser.add_argument(
        "--odds-run-id",
        type=_parse_positive_integer,
        required=True,
    )

    parser.add_argument(
        "--policy-version",
        default="1.0.0",
    )

    return parser


def _parse_positive_integer(
    value: str,
) -> int:
    try:
        parsed_value = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            "Identifier must be an integer."
        ) from error

    if parsed_value <= 0:
        raise argparse.ArgumentTypeError(
            "Identifier must be greater than zero."
        )

    return parsed_value


if __name__ == "__main__":
    raise SystemExit(main())
