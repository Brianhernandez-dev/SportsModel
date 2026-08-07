import argparse

from sportsmodel.orchestration.odds_snapshot_schedule import (
    FIXED_SNAPSHOT_ROLES,
    resolve_snapshot_target_date,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Resolve the Pacific target date for a fixed "
            "MLB odds snapshot role."
        )
    )

    parser.add_argument(
        "--snapshot-role",
        required=True,
        choices=sorted(FIXED_SNAPSHOT_ROLES),
    )

    return parser


def main() -> None:
    arguments = build_parser().parse_args()

    target_date = resolve_snapshot_target_date(
        arguments.snapshot_role
    )

    print(target_date.isoformat())


if __name__ == "__main__":
    main()
