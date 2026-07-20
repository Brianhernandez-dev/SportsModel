from dataclasses import asdict
from datetime import datetime, timezone
from pprint import pformat
from time import perf_counter

from sportsmodel.database.game_repository import (
    PostgresGameRepository,
)
from sportsmodel.features.generation_service import (
    FeatureGenerationService,
)


def main() -> None:
    """
    Generate and display features for the next upcoming MLB game.
    """

    current_time = datetime.now(timezone.utc)

    game_repository = PostgresGameRepository()

    game = game_repository.get_next_upcoming_game(
        cutoff_time=current_time,
    )

    if game is None:
        print(
            "No upcoming game was found in the database "
            f"after {current_time.isoformat()}."
        )
        return

    service = FeatureGenerationService(
        game_repository=game_repository,
    )

    started_at = perf_counter()

    feature_vector = service.generate_for_game_record(
        game=game,
        cutoff_time=current_time,
    )

    elapsed_milliseconds = (
        perf_counter() - started_at
    ) * 1000

    print()
    print("Upcoming MLB Game Feature Preview")
    print("=================================")
    print(f"Game ID: {game.game_id}")
    print(f"Game start: {game.game_start_time.isoformat()}")
    print(f"Feature cutoff: {current_time.isoformat()}")
    print(f"Home team ID: {game.home_team_id}")
    print(f"Away team ID: {game.away_team_id}")
    print(
        "Generation time: "
        f"{elapsed_milliseconds:.2f} milliseconds"
    )
    print()
    print("Generated Feature Vector")
    print("------------------------")
    print(
        pformat(
            asdict(feature_vector),
            sort_dicts=False,
            width=100,
        )
    )


if __name__ == "__main__":
    main()
