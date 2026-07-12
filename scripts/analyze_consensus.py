from sportsmodel.analysis.consensus import build_consensus_markets
from sportsmodel.analysis.market_builder import build_complete_markets
from sportsmodel.analysis.no_vig import calculate_no_vig_markets
from sportsmodel.database.repository import get_market_snapshots


def main() -> None:
    snapshots = get_market_snapshots()
    complete_markets = build_complete_markets(snapshots)
    no_vig_markets = calculate_no_vig_markets(complete_markets)
    consensus_markets = build_consensus_markets(no_vig_markets)

    print(f"Snapshots: {len(snapshots)}")
    print(f"Complete markets: {len(complete_markets)}")
    print(f"No-vig markets: {len(no_vig_markets)}")
    print(f"Consensus markets: {len(consensus_markets)}")
    print()

    for market in consensus_markets[:20]:
        print(market)


if __name__ == "__main__":
    main()