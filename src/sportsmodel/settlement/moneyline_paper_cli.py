import argparse
from decimal import Decimal

from sportsmodel.settlement.moneyline_paper_service import (
    settle_moneyline_paper_candidate_run,
)


def main(
    argv: list[str] | None = None,
) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)

    try:
        result = (
            settle_moneyline_paper_candidate_run(
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
        )
    except Exception as error:
        print(
            "Moneyline paper settlement failed: "
            f"{type(error).__name__}: {error}"
        )
        return 1

    report = result.report

    print("=" * 88)
    print(
        "SportsModel MLB Moneyline "
        "Paper Settlement"
    )
    print("=" * 88)
    print(
        f"Prediction run ID:   "
        f"{result.prediction_run_id}"
    )
    print(
        f"Odds run ID:         "
        f"{result.odds_ingestion_run_id}"
    )
    print(
        f"Policy version:      "
        f"{result.policy_version}"
    )
    print(
        f"Candidates loaded:   "
        f"{report.candidates_loaded}"
    )
    print(
        f"Settlements saved:   "
        f"{report.settlements_saved}"
    )
    print(
        f"Pending candidates:  "
        f"{report.pending_candidates}"
    )

    for rank, settlement in enumerate(
        result.settlements,
        start=1,
    ):
        print()
        print("-" * 88)
        print(
            f"{rank}. "
            f"{settlement.away_team_name} at "
            f"{settlement.home_team_name}"
        )
        print(
            "Final score:         "
            f"{settlement.away_team_name} "
            f"{settlement.away_score}, "
            f"{settlement.home_team_name} "
            f"{settlement.home_score}"
        )
        print(
            "Selection:           "
            f"{settlement.selection_name} "
            f"({settlement.price:+d})"
        )
        print(
            "Model probability:   "
            f"{_format_percent(settlement.model_probability)}"
        )
        print(
            "Model EV:            "
            f"{_format_percent(settlement.model_expected_value)}"
        )
        print(
            "Outcome:             "
            f"{settlement.outcome.value.upper()}"
        )
        print(
            "Profit:              "
            f"{_format_units(settlement.profit_units)}"
        )

    print()
    print("=" * 88)
    print("Forward Paper Performance")
    print("=" * 88)
    print(
        f"Settled record:       "
        f"{report.wins}-"
        f"{report.losses}-"
        f"{report.pushes}"
    )
    print(
        f"Win rate:             "
        f"{_format_percent(report.win_rate)}"
    )
    print(
        f"Units staked:         "
        f"{report.total_staked_units}"
    )
    print(
        f"Profit units:         "
        f"{_format_units(report.profit_units)}"
    )
    print(
        f"ROI:                  "
        f"{_format_percent(report.roi)}"
    )
    print(
        f"Average model EV:     "
        f"{_format_percent(report.average_model_expected_value)}"
    )
    print(
        f"Maximum drawdown:     "
        f"{report.maximum_drawdown_units:.4f} units"
    )

    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Settle one stored MLB Moneyline "
            "paper-candidate slate."
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


def _format_percent(
    value: Decimal,
) -> str:
    return f"{float(value):.2%}"


def _format_units(
    value: Decimal,
) -> str:
    return f"{value:+.4f} units"


if __name__ == "__main__":
    raise SystemExit(main())
