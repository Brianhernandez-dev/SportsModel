import argparse
from decimal import Decimal, InvalidOperation

from sportsmodel.analysis.expected_value import (
    calculate_expected_value_markets,
)
from sportsmodel.analysis.market_builder import (
    build_complete_markets,
)
from sportsmodel.analysis.no_vig import (
    calculate_no_vig_markets,
)
from sportsmodel.database.repository import (
    get_game_results,
    get_market_snapshots,
)
from sportsmodel.settlement.settlement import (
    settle_bet_candidates,
)
from sportsmodel.strategies.positive_ev import (
    select_positive_ev_candidates,
)


def parse_decimal(value: str) -> Decimal:
    try:
        return Decimal(value)
    except InvalidOperation as error:
        raise argparse.ArgumentTypeError(
            f"Invalid decimal value: {value}"
        ) from error


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Explain whether positive-EV candidates can be "
            "matched and settled against historical results."
        )
    )

    parser.add_argument(
        "--min-ev",
        type=parse_decimal,
        default=Decimal("0"),
        help=(
            "Minimum expected value as a decimal. "
            "Default: 0."
        ),
    )

    return parser.parse_args()


def main() -> None:
    arguments = parse_arguments()

    snapshots = get_market_snapshots()
    complete_markets = build_complete_markets(snapshots)
    no_vig_markets = calculate_no_vig_markets(
        complete_markets
    )
    expected_value_markets = (
        calculate_expected_value_markets(
            no_vig_markets
        )
    )

    candidates = select_positive_ev_candidates(
        expected_value_markets,
        minimum_expected_value=arguments.min_ev,
    )

    results = get_game_results()

    results_by_game = {
        result.game_id: result
        for result in results
    }

    settled_bets = settle_bet_candidates(
        candidates,
        results,
    )

    settled_by_snapshot = {
        bet.odds_market_snapshot_id: bet
        for bet in settled_bets
    }

    print()
    print("=" * 72)
    print("SportsModel Candidate Settlement Diagnostic")
    print("=" * 72)
    print()
    print(f"Minimum EV:          {arguments.min_ev:.2%}")
    print(f"Candidates:          {len(candidates)}")
    print(f"Game results:        {len(results)}")
    print(f"Settled candidates:  {len(settled_bets)}")
    print()

    for candidate in candidates:
        print("-" * 72)
        print(
            f"Game {candidate.game_id} | "
            f"Sportsbook {candidate.sportsbook_id} | "
            f"{candidate.market_type}"
        )
        print(
            f"Selection: {candidate.selection_name}"
        )
        print(
            f"Line: {candidate.line_value} | "
            f"Price: {candidate.price:+d} | "
            f"EV: {candidate.expected_value:.4%}"
        )
        print(
            f"Bet time: "
            f"{candidate.bet_snapshot_time.isoformat()}"
        )

        result = results_by_game.get(
            candidate.game_id
        )

        if result is None:
            print("Result match: NO")
            print(
                "Reason: No linked final result exists for "
                "this canonical game_id."
            )
            continue

        print("Result match: YES")
        print(
            f"Final: {result.away_team} "
            f"{result.away_score}, "
            f"{result.home_team} "
            f"{result.home_score}"
        )

        settled = settled_by_snapshot.get(
            candidate.odds_market_snapshot_id
        )

        if settled is not None:
            print("Settlement: SUCCESS")
            print(
                f"Outcome: {settled.outcome.value.upper()} | "
                f"Profit: {settled.profit_units:+.4f} units"
            )
            continue

        print("Settlement: FAILED")

        if candidate.market_type not in {
            "h2h",
            "spreads",
            "totals",
        }:
            print(
                "Reason: Unsupported market type."
            )

        elif (
            candidate.market_type
            in {"h2h", "spreads"}
            and candidate.selection_name
            not in {
                result.home_team,
                result.away_team,
            }
        ):
            print(
                "Reason: Candidate team name does not match "
                "either historical result team."
            )
            print(
                f"Candidate: {candidate.selection_name}"
            )
            print(
                f"Expected: {result.home_team} or "
                f"{result.away_team}"
            )

        elif (
            candidate.market_type
            in {"spreads", "totals"}
            and candidate.line_value is None
        ):
            print(
                "Reason: Market requires a line value, "
                "but none was stored."
            )

        elif (
            candidate.market_type == "totals"
            and candidate.selection_name
            not in {"Over", "Under"}
        ):
            print(
                "Reason: Totals selection must be Over "
                "or Under."
            )

        else:
            print(
                "Reason: Candidate matched a result but was "
                "not settled; inspect settlement logic."
            )

    print()
    print("=" * 72)


if __name__ == "__main__":
    main()
