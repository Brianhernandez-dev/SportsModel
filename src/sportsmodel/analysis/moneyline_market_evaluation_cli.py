import argparse
from decimal import Decimal

from sportsmodel.analysis.moneyline_market_evaluation_service import (
    evaluate_moneyline_prediction_run,
)


def main(
    argv: list[str] | None = None,
) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)

    try:
        result = (
            evaluate_moneyline_prediction_run(
                prediction_run_id=(
                    arguments.prediction_run_id
                ),
                odds_ingestion_run_id=(
                    arguments.odds_run_id
                ),
            )
        )
    except Exception as error:
        print(
            "Moneyline market evaluation failed: "
            f"{type(error).__name__}: {error}"
        )
        return 1

    print("=" * 88)
    print(
        "SportsModel MLB Moneyline "
        "Market Evaluation"
    )
    print("=" * 88)
    print(
        f"Prediction run ID:  "
        f"{result.prediction_run_id}"
    )
    print(
        f"Odds run ID:        "
        f"{result.odds_ingestion_run_id}"
    )
    print(
        f"Policy version:     "
        f"{result.policy_version}"
    )
    print(
        f"Predictions loaded: "
        f"{result.predictions_loaded}"
    )
    print(
        f"Evaluations saved:  "
        f"{result.evaluations_saved}"
    )
    print(
        f"Paper candidates:   "
        f"{result.paper_candidates}"
    )

    for rank, evaluation in enumerate(
        result.evaluations,
        start=1,
    ):
        print()
        print("-" * 88)
        print(
            f"{rank}. "
            f"{evaluation.away_team_name} at "
            f"{evaluation.home_team_name}"
        )
        print(
            "Selection:          "
            f"{evaluation.selection_name}"
        )
        print(
            "Model probability:  "
            f"{_format_percent(evaluation.model_probability)}"
        )
        print(
            "Market no-vig:      "
            f"{_format_percent(evaluation.market_no_vig_probability)}"
        )
        print(
            "Model-market edge:  "
            f"{_format_points(evaluation.model_market_edge)}"
        )
        print(
            "Best stored price:  "
            f"{evaluation.price:+d} at "
            f"{evaluation.sportsbook_name}"
        )
        print(
            "Break-even:         "
            f"{_format_percent(evaluation.implied_probability)}"
        )
        print(
            "Model-price edge:   "
            f"{_format_points(evaluation.model_price_edge)}"
        )
        print(
            "Model EV:           "
            f"{_format_percent(evaluation.model_expected_value)}"
        )
        print(
            "Sportsbooks:        "
            f"{evaluation.sportsbook_count}"
        )
        print(
            "Paper candidate:    "
            f"{evaluation.qualifies_as_paper_candidate}"
        )

        if evaluation.disqualification_reasons:
            print(
                "Reasons:            "
                + ", ".join(
                    evaluation
                    .disqualification_reasons
                )
            )

    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate one stored MLB Moneyline "
            "prediction run against one stored odds run."
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


def _format_percent(
    value: Decimal,
) -> str:
    return f"{float(value):.2%}"


def _format_points(
    value: Decimal,
) -> str:
    return (
        f"{float(value * Decimal('100')):+.2f} pp"
    )


if __name__ == "__main__":
    raise SystemExit(main())
