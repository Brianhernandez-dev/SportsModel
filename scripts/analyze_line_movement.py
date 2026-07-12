from sportsmodel.analysis.line_movement import calculate_line_movements
from sportsmodel.database.repository import get_market_snapshots


def main() -> None:
    snapshots = get_market_snapshots()
    movements = calculate_line_movements(snapshots)

    repeated_movements = [
        movement
        for movement in movements
        if movement.snapshot_count > 1
    ]

    print(f"Snapshots loaded: {len(snapshots)}")
    print(f"Movement groups: {len(movements)}")
    print(
        "Groups with multiple snapshots: "
        f"{len(repeated_movements)}"
    )

    print()

    for movement in repeated_movements[:20]:
        print(movement)


if __name__ == "__main__":
    main()