from sportsmodel.analysis.closing_line_value import (
    calculate_closing_line_value_markets,
)
from sportsmodel.analysis.market_builder import (
    build_complete_markets,
)
from sportsmodel.analysis.market_timeline import (
    build_market_timelines,
)
from sportsmodel.database.repository import (
    get_market_snapshots,
)


def main() -> None:
    snapshots = get_market_snapshots()
    complete_markets = build_complete_markets(snapshots)
    timelines = build_market_timelines(complete_markets)

    clv_markets = calculate_closing_line_value_markets(
        timelines
    )

    selections = [
        selection
        for market in clv_markets
        for selection in market.selections
    ]

    comparable_selections = [
        selection
        for selection in selections
        if selection.is_price_comparable
    ]

    changed_line_selections = [
        selection
        for selection in selections
        if selection.line_change not in (None, 0)
    ]

    positive_price_clv = [
        selection
        for selection in comparable_selections
        if (
            selection.decimal_odds_clv is not None
            and selection.decimal_odds_clv > 0
        )
    ]

    print(f"Snapshots: {len(snapshots)}")
    print(
        f"Complete markets: "
        f"{len(complete_markets)}"
    )
    print(f"Market timelines: {len(timelines)}")
    print(f"CLV markets: {len(clv_markets)}")
    print(f"CLV selections: {len(selections)}")
    print(
        f"Price-comparable selections: "
        f"{len(comparable_selections)}"
    )
    print(
        f"Changed-line selections: "
        f"{len(changed_line_selections)}"
    )
    print(
        f"Positive price CLV selections: "
        f"{len(positive_price_clv)}"
    )
    print()

    examples = [
        market
        for market in clv_markets
        if any(
            selection.line_change not in (None, 0)
            or (
                selection.decimal_odds_clv is not None
                and selection.decimal_odds_clv != 0
            )
            for selection in market.selections
        )
    ][:20]

    for market in examples:
        print(
            f"Game {market.game_id} | "
            f"Sportsbook {market.sportsbook_id} | "
            f"{market.market_type}"
        )
        print(
            f"  Bet:   "
            f"{market.bet_snapshot_time.isoformat()}"
        )
        print(
            f"  Close: "
            f"{market.closing_snapshot_time.isoformat()}"
        )

        for selection in market.selections:
            print(
                f"  {selection.selection_name}: "
                f"line {selection.bet_line} -> "
                f"{selection.closing_line}, "
                f"price {selection.bet_price:+d} -> "
                f"{selection.closing_price:+d}, "
                f"line change={selection.line_change}, "
                f"probability CLV="
                f"{selection.probability_clv}, "
                f"decimal CLV="
                f"{selection.decimal_odds_clv}"
            )

        print()


if __name__ == "__main__":
    main()
