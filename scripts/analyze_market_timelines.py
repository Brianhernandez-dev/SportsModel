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
    timelines = build_market_timelines(
        complete_markets
    )

    multi_snapshot_timelines = [
        timeline
        for timeline in timelines
        if len(timeline.markets) > 1
    ]

    print(f"Snapshots: {len(snapshots)}")
    print(
        f"Complete markets: "
        f"{len(complete_markets)}"
    )
    print(f"Market timelines: {len(timelines)}")
    print(
        f"Multi-snapshot timelines: "
        f"{len(multi_snapshot_timelines)}"
    )
    print()

    timelines_to_display = (
        multi_snapshot_timelines[:10]
        if multi_snapshot_timelines
        else timelines[:10]
    )

    for timeline in timelines_to_display:
        print(
            f"Game {timeline.game_id} | "
            f"Sportsbook {timeline.sportsbook_id} | "
            f"{timeline.market_type} | "
            f"Markets: {len(timeline.markets)}"
        )

        for market in timeline.markets:
            selection_summary = ", ".join(
                (
                    f"{selection.selection_name} "
                    f"{selection.line_value} "
                    f"{selection.price:+d}"
                )
                for selection in market.selections
            )

            print(
                f"  {market.snapshot_time.isoformat()} | "
                f"{selection_summary}"
            )

        print()


if __name__ == "__main__":
    main()
