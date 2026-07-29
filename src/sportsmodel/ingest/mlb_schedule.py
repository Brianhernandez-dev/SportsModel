from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from sportsmodel.database.connection import get_connection
from sportsmodel.ingest.game_matching import (
    get_or_create_canonical_game,
)
from sportsmodel.ingest.mlb_stats import (
    fetch_schedule_for_date,
    get_team_id,
    parse_game_datetime,
)


SOURCE_NAME = "mlb_stats"
REGULAR_SEASON_GAME_TYPE = "R"


ScheduleFetcher = Callable[
    [date],
    dict[str, Any],
]
ConnectionFactory = Callable[[], Any]
TeamIdResolver = Callable[[Any, str], int]
CanonicalGameResolver = Callable[..., int]
CanonicalGameUpdater = Callable[..., None]
ProgressCallback = Callable[[str], None]


@dataclass(frozen=True)
class ScheduledMlbGame:
    """
    Valid regular-season game parsed from an MLB schedule response.
    """

    game_pk: int

    game_datetime: datetime

    home_team: str

    away_team: str


@dataclass(frozen=True)
class ScheduleSyncDateSummary:
    """
    Result of synchronizing one MLB schedule date.
    """

    schedule_date: date

    games_received: int

    games_synchronized: int

    games_skipped: int

    error_message: str | None = None

    @property
    def failed(self) -> bool:
        return self.error_message is not None


@dataclass(frozen=True)
class ScheduleSyncSummary:
    """
    Aggregate result for an MLB schedule synchronization.
    """

    start_date: date

    end_date: date

    date_summaries: tuple[
        ScheduleSyncDateSummary,
        ...,
    ]

    @property
    def dates_attempted(self) -> int:
        return len(self.date_summaries)

    @property
    def dates_failed(self) -> int:
        return sum(
            summary.failed
            for summary in self.date_summaries
        )

    @property
    def games_received(self) -> int:
        return sum(
            summary.games_received
            for summary in self.date_summaries
        )

    @property
    def games_synchronized(self) -> int:
        return sum(
            summary.games_synchronized
            for summary in self.date_summaries
        )

    @property
    def games_skipped(self) -> int:
        return sum(
            summary.games_skipped
            for summary in self.date_summaries
        )


def sync_mlb_schedule(
    *,
    start_date: date | None = None,
    days_ahead: int = 7,
    progress_callback: ProgressCallback | None = print,
    schedule_fetcher: ScheduleFetcher = fetch_schedule_for_date,
    connection_factory: ConnectionFactory = get_connection,
    team_id_resolver: TeamIdResolver = get_team_id,
    canonical_game_resolver: CanonicalGameResolver = (
        get_or_create_canonical_game
    ),
    canonical_game_updater: CanonicalGameUpdater | None = None,
) -> ScheduleSyncSummary:
    """
    Synchronize regular-season MLB games into the canonical game table.

    days_ahead is inclusive. A value of seven processes the start date
    through seven calendar days after the start date.
    """

    if days_ahead < 0:
        raise ValueError(
            "Days ahead cannot be negative."
        )

    resolved_start_date = (
        date.today()
        if start_date is None
        else start_date
    )

    end_date = (
        resolved_start_date
        + timedelta(days=days_ahead)
    )

    updater = (
        update_canonical_game
        if canonical_game_updater is None
        else canonical_game_updater
    )

    date_summaries: list[
        ScheduleSyncDateSummary
    ] = []

    for schedule_date in _date_range(
        resolved_start_date,
        end_date,
    ):
        summary = _sync_schedule_date(
            schedule_date=schedule_date,
            schedule_fetcher=schedule_fetcher,
            connection_factory=connection_factory,
            team_id_resolver=team_id_resolver,
            canonical_game_resolver=(
                canonical_game_resolver
            ),
            canonical_game_updater=updater,
        )

        date_summaries.append(summary)

        if progress_callback is not None:
            progress_callback(
                _format_date_summary(summary)
            )

    result = ScheduleSyncSummary(
        start_date=resolved_start_date,
        end_date=end_date,
        date_summaries=tuple(date_summaries),
    )

    if progress_callback is not None:
        for line in _format_sync_summary(result):
            progress_callback(line)

    return result


def update_canonical_game(
    cursor: Any,
    *,
    game_id: int,
    game_datetime: datetime,
    home_team_id: int,
    away_team_id: int,
) -> None:
    """
    Refresh canonical schedule information from the current MLB feed.
    """

    cursor.execute(
        """
        UPDATE games
        SET
            game_date = %s,
            home_team_id = %s,
            away_team_id = %s
        WHERE game_id = %s;
        """,
        (
            game_datetime,
            home_team_id,
            away_team_id,
            game_id,
        ),
    )


def _sync_schedule_date(
    *,
    schedule_date: date,
    schedule_fetcher: ScheduleFetcher,
    connection_factory: ConnectionFactory,
    team_id_resolver: TeamIdResolver,
    canonical_game_resolver: CanonicalGameResolver,
    canonical_game_updater: CanonicalGameUpdater,
) -> ScheduleSyncDateSummary:
    try:
        schedule_data = schedule_fetcher(
            schedule_date
        )
    except Exception as error:
        return ScheduleSyncDateSummary(
            schedule_date=schedule_date,
            games_received=0,
            games_synchronized=0,
            games_skipped=0,
            error_message=_format_error(error),
        )

    schedule_games = _extract_schedule_games(
        schedule_data
    )

    try:
        connection = connection_factory()
    except Exception as error:
        return ScheduleSyncDateSummary(
            schedule_date=schedule_date,
            games_received=len(schedule_games),
            games_synchronized=0,
            games_skipped=0,
            error_message=_format_error(error),
        )

    games_synchronized = 0
    games_skipped = 0

    try:
        with connection.cursor() as cursor:
            for game in schedule_games:
                scheduled_game = (
                    _parse_scheduled_game(game)
                )

                if scheduled_game is None:
                    games_skipped += 1
                    continue

                home_team_id = team_id_resolver(
                    cursor,
                    scheduled_game.home_team,
                )
                away_team_id = team_id_resolver(
                    cursor,
                    scheduled_game.away_team,
                )

                game_id = canonical_game_resolver(
                    cursor,
                    source_name=SOURCE_NAME,
                    external_game_id=str(
                        scheduled_game.game_pk
                    ),
                    game_datetime=(
                        scheduled_game.game_datetime
                    ),
                    home_team_id=home_team_id,
                    away_team_id=away_team_id,
                )

                canonical_game_updater(
                    cursor,
                    game_id=game_id,
                    game_datetime=(
                        scheduled_game.game_datetime
                    ),
                    home_team_id=home_team_id,
                    away_team_id=away_team_id,
                )

                games_synchronized += 1

        connection.commit()

    except Exception as error:
        connection.rollback()

        return ScheduleSyncDateSummary(
            schedule_date=schedule_date,
            games_received=len(schedule_games),
            games_synchronized=0,
            games_skipped=games_skipped,
            error_message=_format_error(error),
        )

    finally:
        connection.close()

    return ScheduleSyncDateSummary(
        schedule_date=schedule_date,
        games_received=len(schedule_games),
        games_synchronized=games_synchronized,
        games_skipped=games_skipped,
    )


def _date_range(
    start_date: date,
    end_date: date,
):
    current_date = start_date

    while current_date <= end_date:
        yield current_date
        current_date += timedelta(days=1)


def _extract_schedule_games(
    schedule_data: dict[str, Any],
) -> tuple[dict[str, Any], ...]:
    date_blocks = schedule_data.get("dates")

    if not isinstance(date_blocks, list):
        return ()

    games: list[dict[str, Any]] = []

    for date_block in date_blocks:
        if not isinstance(date_block, dict):
            continue

        date_games = date_block.get("games")

        if not isinstance(date_games, list):
            continue

        games.extend(
            game
            for game in date_games
            if isinstance(game, dict)
        )

    return tuple(games)


def _parse_scheduled_game(
    game: dict[str, Any],
) -> ScheduledMlbGame | None:
    if (
        game.get("gameType")
        != REGULAR_SEASON_GAME_TYPE
    ):
        return None

    game_pk = game.get("gamePk")
    game_datetime = parse_game_datetime(game)
    teams = game.get("teams")

    if (
        not isinstance(game_pk, int)
        or game_pk <= 0
        or game_datetime is None
        or not isinstance(teams, dict)
    ):
        return None

    home_team = _extract_team_name(
        teams.get("home")
    )
    away_team = _extract_team_name(
        teams.get("away")
    )

    if (
        home_team is None
        or away_team is None
    ):
        return None

    return ScheduledMlbGame(
        game_pk=game_pk,
        game_datetime=game_datetime,
        home_team=home_team,
        away_team=away_team,
    )


def _extract_team_name(
    side: Any,
) -> str | None:
    if not isinstance(side, dict):
        return None

    team = side.get("team")

    if not isinstance(team, dict):
        return None

    team_name = team.get("name")

    if (
        not isinstance(team_name, str)
        or not team_name.strip()
    ):
        return None

    return team_name.strip()


def _format_date_summary(
    summary: ScheduleSyncDateSummary,
) -> str:
    if summary.error_message is not None:
        return (
            f"{summary.schedule_date}: failed - "
            f"{summary.error_message}"
        )

    return (
        f"{summary.schedule_date}: "
        f"received={summary.games_received}, "
        f"synchronized="
        f"{summary.games_synchronized}, "
        f"skipped={summary.games_skipped}"
    )


def _format_sync_summary(
    summary: ScheduleSyncSummary,
) -> tuple[str, ...]:
    return (
        "MLB schedule synchronization complete.",
        (
            "Date range: "
            f"{summary.start_date} through "
            f"{summary.end_date}"
        ),
        (
            "Dates attempted: "
            f"{summary.dates_attempted}"
        ),
        (
            "Dates failed: "
            f"{summary.dates_failed}"
        ),
        (
            "Schedule games received: "
            f"{summary.games_received}"
        ),
        (
            "Games synchronized: "
            f"{summary.games_synchronized}"
        ),
        (
            "Games skipped: "
            f"{summary.games_skipped}"
        ),
    )


def _format_error(error: Exception) -> str:
    return (
        f"{type(error).__name__}: {error}"
    )
