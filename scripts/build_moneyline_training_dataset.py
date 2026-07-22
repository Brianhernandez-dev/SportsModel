import argparse
import csv
from pathlib import Path
from time import perf_counter
from typing import Any

from sportsmodel.database.completed_game_repository import (
    PostgresCompletedGameRepository,
)
from sportsmodel.features.datasets.moneyline_dataset import (
    MoneylineTrainingDatasetBuilder,
)


DEFAULT_OUTPUT_PATH = Path(
    "data/training/mlb_moneyline_training.csv"
)


def main() -> None:
    arguments = _parse_arguments()
    output_path = arguments.output

    started_at = perf_counter()

    repository = PostgresCompletedGameRepository()
    completed_games = repository.get_all()

    builder = MoneylineTrainingDatasetBuilder()
    result = builder.build(completed_games)

    _write_csv(
        output_path=output_path,
        rows=result.rows,
    )

    elapsed_seconds = perf_counter() - started_at

    print("=" * 58)
    print("SportsModel Moneyline Training Dataset")
    print("=" * 58)
    print(
        "Completed games received: "
        f"{result.completed_games_received}"
    )
    print(f"Rows generated: {result.rows_generated}")
    print(
        "Tied games skipped: "
        f"{result.tied_games_skipped}"
    )
    print(f"Feature columns: {result.feature_count}")
    print(f"Output: {output_path.resolve()}")
    print(f"Elapsed seconds: {elapsed_seconds:.2f}")


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build the historical MLB Moneyline training "
            "dataset."
        )
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help=(
            "CSV output path. Defaults to "
            "data/training/mlb_moneyline_training.csv."
        ),
    )

    return parser.parse_args()


def _write_csv(
    *,
    output_path: Path,
    rows: tuple[dict[str, Any], ...],
) -> None:
    if not rows:
        raise RuntimeError(
            "No Moneyline training rows were generated."
        )

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    field_names = list(rows[0])

    with output_path.open(
        mode="w",
        newline="",
        encoding="utf-8",
    ) as output_file:
        writer = csv.DictWriter(
            output_file,
            fieldnames=field_names,
            extrasaction="raise",
        )
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main()
