from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

import requests

from sportsmodel.database.boxscore_status_repository import (
    get_complete_box_score_game_ids,
)
from sportsmodel.database.connection import get_connection
from sportsmodel.ingest.boxscore_ingestion import ingest_boxscore
from sportsmodel.ingest.game_matching import (
    get_or_create_canonical_game,
)


SOURCE_NAME = "mlb_stats"
MLB_SCHEDULE_URL = "https://statsapi.mlb.com/api/v1/schedule"


ScheduleFetcher = Callable[[date], dict[str, Any]]
ConnectionFactory = Callable[[], Any]
TeamIdResolver = Callable[[Any, str], int]
CanonicalGameResolver = Callable[..., int]
HistoricalResultSaver = Callable[..., None]
CompleteGameIdsGetter = Callable[
    [Iterable[int]],
    frozenset[int],
]
BoxScoreIngestor = Callable[..., None]
ProgressCallback = Callable[[str], None]


@dataclass(frozen=True)
class FinalizedScheduleGame:
    """
    Valid finalized game parsed from an MLB schedule response.
    """

    game_pk: int

    game_datetime: datetime

    home_team: str

    away_team: str

    home_score: int

    away_score: int


@dataclass(frozen=True)
class HistoricalGameReference:
    """
    Canonical and MLB identifiers for one persisted result.
    """

    game_id: int

    game_pk: int


@dataclass(frozen=True)
class HistoricalResultsDateSummary:
    """
    Result of processing one MLB schedule date.
    """

    schedule_date: date

    schedule_games_received: int

    finalized_games_processed: int

    games_skipped: int

    boxscores_processed: int

    boxscores_skipped_complete: int

    boxscores_failed: int

    schedule_error: str | None = None

    database_error: str | None = None

    @property
    def failed(self) -> bool:
        return (
            self.schedule_error is not None
            or self.database_error is not None
        )


@dataclass(frozen=True)
class HistoricalResultsBackfillSummary:
    """
    Aggregate result for a historical MLB date range.
    """

    start_date: date

    end_date: date

    date_summaries: tuple[
        HistoricalResultsDateSummary,
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
            summary.schedule_games_received
            for summary in self.date_summaries
        )

    @property
    def games_processed(self) -> int:
        return sum(
            summary.finalized_games_processed
            for summary in self.date_summaries
        )

    @property
    def games_skipped(self) -> int:
        return sum(
            summary.games_skipped
            for summary in self.date_summaries
        )

    @property
    def boxscores_processed(self) -> int:
        return sum(
            summary.boxscores_processed
            for summary in self.date_summaries
        )

    @property
    def boxscores_skipped_complete(self) -> int:
        return sum(
            summary.boxscores_skipped_complete
            for summary in self.date_summaries
        )

    @property
    def boxscores_failed(self) -> int:
        return sum(
            summary.boxscores_failed
            for summary in self.date_summaries
        )


def daterange(
    start_date: date,
    end_date: date,
):
    """Yield every calendar date from start_date through end_date."""

    current_date = start_date

    while current_date <= end_date:
        yield current_date
        current_date += timedelta(days=1)


def get_team_id(
    cursor: Any,
    team_name: str,
) -> int:
    """Return a team ID, creating the team when necessary."""

    cursor.execute(
        """
        INSERT INTO teams (team_name)
        VALUES (%s)
        ON CONFLICT (team_name) DO NOTHING;
        """,
        (team_name,),
    )

    cursor.execute(
        """
        SELECT team_id
        FROM teams
        WHERE team_name = %s;
        """,
        (team_name,),
    )

    row = cursor.fetchone()

    if row is None:
        raise LookupError(
            f"Unable to resolve team: {team_name}"
        )

    return int(row[0])


def parse_game_datetime(
    game: dict[str, Any],
) -> datetime | None:
    """Convert MLB's gameDate value into a UTC datetime."""

    game_date_value = game.get("gameDate")

    if not isinstance(game_date_value, str):
        return None

    return datetime.fromisoformat(
        game_date_value.replace("Z", "+00:00")
    ).astimezone(timezone.utc)


def save_historical_result(
    cursor: Any,
    game_id: int,
    mlb_game_id: int,
    game_date: date,
    home_team: str,
    away_team: str,
    home_score: int,
    away_score: int,
) -> None:
    """Insert or update one finalized MLB game result."""

    home_win = home_score > away_score

    cursor.execute(
        """
        INSERT INTO historical_games (
            game_id,
            mlb_game_id,
            game_date,
            home_team,
            away_team,
            home_score,
            away_score,
            home_win
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (mlb_game_id)
        DO UPDATE SET
            game_id = EXCLUDED.game_id,
            game_date = EXCLUDED.game_date,
            home_team = EXCLUDED.home_team,
            away_team = EXCLUDED.away_team,
            home_score = EXCLUDED.home_score,
            away_score = EXCLUDED.away_score,
            home_win = EXCLUDED.home_win;
        """,
        (
            game_id,
            mlb_game_id,
            game_date,
            home_team,
            away_team,
            home_score,
            away_score,
            home_win,
        ),
    )


def fetch_schedule_for_date(
    schedule_date: date,
) -> dict[str, Any]:
    """
    Fetch one MLB schedule date.
    """

    response = requests.get(
        MLB_SCHEDULE_URL,
        params={
            "sportId": 1,
            "date": schedule_date.isoformat(),
        },
        timeout=30,
    )

    response.raise_for_status()

    data = response.json()

    if not isinstance(data, dict):
        raise ValueError(
            "MLB schedule response was not an object."
        )

    return data


def fetch_historical_results(
    start_date: date = date(2026, 6, 1),
    end_date: date | None = None,
    *,
    skip_complete_boxscores: bool = True,
    progress_callback: ProgressCallback | None = print,
    schedule_fetcher: ScheduleFetcher = (
        fetch_schedule_for_date
    ),
    connection_factory: ConnectionFactory = get_connection,
    team_id_resolver: TeamIdResolver = get_team_id,
    canonical_game_resolver: CanonicalGameResolver = (
        get_or_create_canonical_game
    ),
    historical_result_saver: HistoricalResultSaver = (
        save_historical_result
    ),
    complete_game_ids_getter: CompleteGameIdsGetter = (
        get_complete_box_score_game_ids
    ),
    boxscore_ingestor: BoxScoreIngestor = ingest_boxscore,
) -> HistoricalResultsBackfillSummary:
    """
    Backfill finalized MLB results and complete box scores.

    Each schedule date is committed independently. A schedule or
    database failure for one date is recorded and does not prevent
    later dates from being processed.
    """

    if end_date is None:
        end_date = date.today() - timedelta(days=1)

    if start_date > end_date:
        raise ValueError(
            "Start date cannot be after end date."
        )

    date_summaries: list[
        HistoricalResultsDateSummary
    ] = []

    for schedule_date in daterange(
        start_date,
        end_date,
    ):
        date_summary = _process_schedule_date(
            schedule_date=schedule_date,
            skip_complete_boxscores=(
                skip_complete_boxscores
            ),
            schedule_fetcher=schedule_fetcher,
            connection_factory=connection_factory,
            team_id_resolver=team_id_resolver,
            canonical_game_resolver=(
                canonical_game_resolver
            ),
            historical_result_saver=(
                historical_result_saver
            ),
            complete_game_ids_getter=(
                complete_game_ids_getter
            ),
            boxscore_ingestor=boxscore_ingestor,
        )

        date_summaries.append(date_summary)

        if progress_callback is not None:
            progress_callback(
                _format_date_summary(date_summary)
            )

    summary = HistoricalResultsBackfillSummary(
        start_date=start_date,
        end_date=end_date,
        date_summaries=tuple(date_summaries),
    )

    if progress_callback is not None:
        for line in _format_backfill_summary(summary):
            progress_callback(line)

    return summary


def _process_schedule_date(
    *,
    schedule_date: date,
    skip_complete_boxscores: bool,
    schedule_fetcher: ScheduleFetcher,
    connection_factory: ConnectionFactory,
    team_id_resolver: TeamIdResolver,
    canonical_game_resolver: CanonicalGameResolver,
    historical_result_saver: HistoricalResultSaver,
    complete_game_ids_getter: CompleteGameIdsGetter,
    boxscore_ingestor: BoxScoreIngestor,
) -> HistoricalResultsDateSummary:
    try:
        schedule_data = schedule_fetcher(
            schedule_date
        )
    except Exception as error:
        return HistoricalResultsDateSummary(
            schedule_date=schedule_date,
            schedule_games_received=0,
            finalized_games_processed=0,
            games_skipped=0,
            boxscores_processed=0,
            boxscores_skipped_complete=0,
            boxscores_failed=0,
            schedule_error=_format_error(error),
        )

    schedule_games = _extract_schedule_games(
        schedule_data
    )

    references: list[HistoricalGameReference] = []
    games_skipped = 0

    try:
        connection = connection_factory()
    except Exception as error:
        return HistoricalResultsDateSummary(
            schedule_date=schedule_date,
            schedule_games_received=len(
                schedule_games
            ),
            finalized_games_processed=0,
            games_skipped=0,
            boxscores_processed=0,
            boxscores_skipped_complete=0,
            boxscores_failed=0,
            database_error=_format_error(error),
        )

    try:
        with connection.cursor() as cursor:
            for game in schedule_games:
                finalized_game = (
                    _parse_finalized_schedule_game(
                        game
                    )
                )

                if finalized_game is None:
                    games_skipped += 1
                    continue

                home_team_id = team_id_resolver(
                    cursor,
                    finalized_game.home_team,
                )

                away_team_id = team_id_resolver(
                    cursor,
                    finalized_game.away_team,
                )

                game_id = canonical_game_resolver(
                    cursor,
                    source_name=SOURCE_NAME,
                    external_game_id=str(
                        finalized_game.game_pk
                    ),
                    game_datetime=(
                        finalized_game.game_datetime
                    ),
                    home_team_id=home_team_id,
                    away_team_id=away_team_id,
                )

                historical_result_saver(
                    cursor=cursor,
                    game_id=game_id,
                    mlb_game_id=finalized_game.game_pk,
                    game_date=schedule_date,
                    home_team=finalized_game.home_team,
                    away_team=finalized_game.away_team,
                    home_score=finalized_game.home_score,
                    away_score=finalized_game.away_score,
                )

                references.append(
                    HistoricalGameReference(
                        game_id=game_id,
                        game_pk=finalized_game.game_pk,
                    )
                )

        connection.commit()

    except Exception as error:
        connection.rollback()

        return HistoricalResultsDateSummary(
            schedule_date=schedule_date,
            schedule_games_received=len(
                schedule_games
            ),
            finalized_games_processed=0,
            games_skipped=games_skipped,
            boxscores_processed=0,
            boxscores_skipped_complete=0,
            boxscores_failed=0,
            database_error=_format_error(error),
        )

    finally:
        connection.close()

    complete_game_ids = frozenset()

    if skip_complete_boxscores and references:
        try:
            complete_game_ids = (
                complete_game_ids_getter(
                    reference.game_id
                    for reference in references
                )
            )
        except Exception as error:
            return HistoricalResultsDateSummary(
                schedule_date=schedule_date,
                schedule_games_received=len(
                    schedule_games
                ),
                finalized_games_processed=len(
                    references
                ),
                games_skipped=games_skipped,
                boxscores_processed=0,
                boxscores_skipped_complete=0,
                boxscores_failed=len(references),
                database_error=(
                    "Box-score completeness check failed: "
                    + _format_error(error)
                ),
            )

    boxscores_processed = 0
    boxscores_skipped_complete = 0
    boxscores_failed = 0

    for reference in references:
        if reference.game_id in complete_game_ids:
            boxscores_skipped_complete += 1
            continue

        try:
            boxscore_ingestor(
                game_id=reference.game_id,
                game_pk=reference.game_pk,
            )

            boxscores_processed += 1

        except Exception:
            boxscores_failed += 1

    return HistoricalResultsDateSummary(
        schedule_date=schedule_date,
        schedule_games_received=len(schedule_games),
        finalized_games_processed=len(references),
        games_skipped=games_skipped,
        boxscores_processed=boxscores_processed,
        boxscores_skipped_complete=(
            boxscores_skipped_complete
        ),
        boxscores_failed=boxscores_failed,
    )


def _extract_schedule_games(
    schedule_data: dict[str, Any],
) -> tuple[dict[str, Any], ...]:
    dates = schedule_data.get("dates")

    if not isinstance(dates, list):
        return ()

    games: list[dict[str, Any]] = []

    for date_block in dates:
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


def _parse_finalized_schedule_game(
    game: dict[str, Any],
) -> FinalizedScheduleGame | None:
    status = game.get("status")

    if not isinstance(status, dict):
        return None

    is_final = (
        status.get("detailedState") == "Final"
        or status.get("abstractGameState") == "Final"
    )

    if not is_final:
        return None

    game_pk = game.get("gamePk")
    game_datetime = parse_game_datetime(game)

    teams = game.get("teams")

    if (
        not isinstance(game_pk, int)
        or game_datetime is None
        or not isinstance(teams, dict)
    ):
        return None

    home = teams.get("home")
    away = teams.get("away")

    if (
        not isinstance(home, dict)
        or not isinstance(away, dict)
    ):
        return None

    home_team = _extract_team_name(home)
    away_team = _extract_team_name(away)
    home_score = home.get("score")
    away_score = away.get("score")

    if (
        home_team is None
        or away_team is None
        or not _is_valid_score(home_score)
        or not _is_valid_score(away_score)
    ):
        return None

    return FinalizedScheduleGame(
        game_pk=game_pk,
        game_datetime=game_datetime,
        home_team=home_team,
        away_team=away_team,
        home_score=home_score,
        away_score=away_score,
    )


def _extract_team_name(
    side: dict[str, Any],
) -> str | None:
    team = side.get("team")

    if not isinstance(team, dict):
        return None

    team_name = team.get("name")

    if (
        not isinstance(team_name, str)
        or not team_name.strip()
    ):
        return None

    return team_name


def _is_valid_score(
    value: Any,
) -> bool:
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and value >= 0
    )


def _format_error(
    error: Exception,
) -> str:
    return (
        f"{type(error).__name__}: {error}"
    )


def _format_date_summary(
    summary: HistoricalResultsDateSummary,
) -> str:
    if summary.schedule_error is not None:
        return (
            f"{summary.schedule_date}: schedule failed - "
            f"{summary.schedule_error}"
        )

    if summary.database_error is not None:
        return (
            f"{summary.schedule_date}: database failed - "
            f"{summary.database_error}"
        )

    return (
        f"{summary.schedule_date}: "
        f"games={summary.schedule_games_received}, "
        f"processed={summary.finalized_games_processed}, "
        f"skipped={summary.games_skipped}, "
        f"boxscores={summary.boxscores_processed}, "
        "already_complete="
        f"{summary.boxscores_skipped_complete}, "
        f"boxscore_failures={summary.boxscores_failed}"
    )


def _format_backfill_summary(
    summary: HistoricalResultsBackfillSummary,
) -> tuple[str, ...]:
    return (
        "Historical MLB backfill complete.",
        (
            "Date range: "
            f"{summary.start_date} through {summary.end_date}"
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
            "Finalized games processed: "
            f"{summary.games_processed}"
        ),
        (
            "Games skipped: "
            f"{summary.games_skipped}"
        ),
        (
            "Box scores processed: "
            f"{summary.boxscores_processed}"
        ),
        (
            "Complete box scores skipped: "
            f"{summary.boxscores_skipped_complete}"
        ),
        (
            "Box scores failed: "
            f"{summary.boxscores_failed}"
        ),
    )
