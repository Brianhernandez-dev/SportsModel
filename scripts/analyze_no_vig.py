from sportsmodel.analysis.market_builder import build_complete_markets
from sportsmodel.analysis.no_vig import calculate_no_vig_markets
from sportsmodel.database.repository import get_market_snapshots


def main() -> None:
    snapshots = get_market_snapshots()

    complete_markets = build_complete_markets(
        snapshots
    )

    no_vig_markets = calculate_no_vig_markets(
        complete_markets
    )

    print(f"Snapshots: {len(snapshots)}")
    print(f"Complete markets: {len(complete_markets)}")
    print(f"No-vig markets: {len(no_vig_markets)}")
    print()

    for market in no_vig_markets[:10]:
        print(market)


if __name__ == "__main__":
    main()