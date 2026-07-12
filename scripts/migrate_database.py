import argparse

from sportsmodel.database.migrations import run_migrations


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Apply SportsModel database migrations."
    )

    parser.add_argument(
        "--baseline-through",
        type=int,
        metavar="VERSION",
        help=(
            "Record existing migrations through VERSION without "
            "executing their SQL."
        ),
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    run_migrations(
        baseline_through=args.baseline_through,
    )


if __name__ == "__main__":
    main()
