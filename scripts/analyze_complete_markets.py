from sportsmodel.analysis.market_builder import build_complete_markets
from sportsmodel.database.repository import get_market_snapshots


def main() -> None:
    snapshots = get_market_snapshots()
    markets = build_complete_markets(snapshots)

    print(f"Snapshots: {len(snapshots)}")
    print(f"Complete markets: {len(markets)}")
    print()

    for market in markets[:20]:
        print(market)


if __name__ == "__main__":
    main()