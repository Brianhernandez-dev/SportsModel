import argparse
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sportsmodel.analysis.moneyline_early_entry_service import (
    capture_moneyline_early_entry,
)


PACIFIC_TIME_ZONE = ZoneInfo("America/Los_Angeles")


def resolve_default_target_date() -> date:
    """Return tomorrow's Pacific-date slate."""

    return datetime.now(PACIFIC_TIME_ZONE).date() + timedelta(days=1)


def parse_target_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            "Target date must use YYYY-MM-DD."
        ) from error


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Persist qualified MLB Moneyline Early Entry "
            "evaluations using the preview model and "
            "late-night odds snapshot."
        )
    )
    parser.add_argument(
        "--target-date",
        type=parse_target_date,
        default=None,
        help=(
            "Target MLB slate date in YYYY-MM-DD format. "
            "Default: tomorrow in Pacific time."
        ),
    )
    return parser


def main() -> None:
    arguments = build_parser().parse_args()
    target_date = (
        arguments.target_date
        if arguments.target_date is not None
        else resolve_default_target_date()
    )
    result = capture_moneyline_early_entry(
        target_date=target_date,
    )

    print("=" * 64)
    print("MLB MONEYLINE EARLY ENTRY")
    print("=" * 64)
    print(f"Target date:           {result.target_date}")
    print(f"Preview run ID:        {result.prediction_run_id}")
    print(f"Late-night odds run:   {result.odds_ingestion_run_id}")
    print(f"Evaluations saved:     {result.evaluations_saved}")
    print(f"Early Entry picks:     {result.early_entry_candidates}")
    print()

    qualified = tuple(
        evaluation
        for evaluation in result.evaluation_result.evaluations
        if evaluation.qualifies_as_paper_candidate
    )

    if not qualified:
        print("NO QUALIFIED EARLY ENTRY PLAYS")
        return

    print("QUALIFIED EARLY ENTRY PLAYS")
    print("-" * 64)

    for rank, evaluation in enumerate(qualified, start=1):
        print(
            f"{rank}. {evaluation.selection_name} "
            f"{evaluation.price:+d}"
        )
        print(
            f"   {evaluation.away_team_name} at "
            f"{evaluation.home_team_name}"
        )
        print(
            "   Model: "
            f"{float(evaluation.model_probability):.1%} | "
            "EV: "
            f"{float(evaluation.model_expected_value):.1%} | "
            "Edge: "
            f"{float(evaluation.model_market_edge):.1%}"
        )
        print(f"   Sportsbook: {evaluation.sportsbook_name}")
        print()


if __name__ == "__main__":
    main()
