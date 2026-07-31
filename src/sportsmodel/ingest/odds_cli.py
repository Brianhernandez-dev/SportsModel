import argparse
from collections.abc import Callable
from typing import Any

from sportsmodel.ingest.odds_api import (
    fetch_live_odds,
)


OddsFetcher = Callable[[], Any]


def build_parser() -> argparse.ArgumentParser:
    """
    Build the live MLB Moneyline odds-ingestion parser.
    """

    return argparse.ArgumentParser(
        description=(
            "Fetch and persist current pregame "
            "MLB Moneyline odds."
        )
    )


def main(
    argv: list[str] | None = None,
    *,
    odds_fetcher: OddsFetcher = fetch_live_odds,
) -> int:
    """
    Execute one live MLB Moneyline odds-ingestion run.
    """

    build_parser().parse_args(argv)

    try:
        odds_fetcher()
    except Exception as error:
        print(
            "MLB Moneyline odds ingestion failed: "
            f"{type(error).__name__}: {error}"
        )
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
