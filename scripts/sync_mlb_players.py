import argparse

from sportsmodel.ingest.mlb_players import sync_mlb_players


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Fetch MLB players by MLB person ID and synchronize them "
            "with the canonical baseball player tables."
        )
    )

    parser.add_argument(
        "player_ids",
        nargs="+",
        help="One or more MLB person IDs.",
    )

    return parser.parse_args()


def main() -> None:
    arguments = parse_arguments()

    summary = sync_mlb_players(arguments.player_ids)

    print("MLB player synchronization complete.")
    print(f"Players received: {summary.players_received}")
    print(f"Players created: {summary.players_created}")
    print(f"Players updated: {summary.players_updated}")
    print(f"Players skipped: {summary.players_skipped}")


if __name__ == "__main__":
    main()