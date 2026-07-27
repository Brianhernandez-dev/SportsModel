from collections.abc import Callable
from typing import Any

from sportsmodel.database.connection import get_connection
from sportsmodel.models.parsed_boxscore import ParsedBoxScore
from sportsmodel.models.player_game_pitching_statistics import (
    PlayerGamePitchingStatistics,
)
from sportsmodel.models.team_game_statistics import TeamGameStatistics


ConnectionFactory = Callable[[], Any]


UPDATE_GAME_QUERY = """
    UPDATE games
    SET
        game_number = %s,
        doubleheader_status = %s
    WHERE game_id = %s;
"""


UPSERT_TEAM_STATISTICS_QUERY = """
    INSERT INTO team_game_statistics (
        game_id,
        team_id,
        is_home,
        runs,
        hits,
        errors,
        at_bats,
        plate_appearances,
        doubles,
        triples,
        home_runs,
        walks,
        intentional_walks,
        strikeouts,
        hit_by_pitch,
        sacrifice_flies,
        stolen_bases,
        caught_stealing,
        pitching_outs,
        runs_allowed,
        earned_runs_allowed,
        hits_allowed,
        home_runs_allowed,
        walks_allowed,
        strikeouts_recorded,
        left_on_base,
        double_plays,
        source_name
    )
    VALUES (
        %s, %s, %s, %s, %s, %s, %s,
        %s, %s, %s, %s, %s, %s, %s,
        %s, %s, %s, %s, %s, %s, %s,
        %s, %s, %s, %s, %s, %s, %s
    )
    ON CONFLICT (game_id, team_id)
    DO UPDATE SET
        is_home = EXCLUDED.is_home,
        runs = EXCLUDED.runs,
        hits = EXCLUDED.hits,
        errors = EXCLUDED.errors,
        at_bats = EXCLUDED.at_bats,
        plate_appearances = EXCLUDED.plate_appearances,
        doubles = EXCLUDED.doubles,
        triples = EXCLUDED.triples,
        home_runs = EXCLUDED.home_runs,
        walks = EXCLUDED.walks,
        intentional_walks = EXCLUDED.intentional_walks,
        strikeouts = EXCLUDED.strikeouts,
        hit_by_pitch = EXCLUDED.hit_by_pitch,
        sacrifice_flies = EXCLUDED.sacrifice_flies,
        stolen_bases = EXCLUDED.stolen_bases,
        caught_stealing = EXCLUDED.caught_stealing,
        pitching_outs = EXCLUDED.pitching_outs,
        runs_allowed = EXCLUDED.runs_allowed,
        earned_runs_allowed = EXCLUDED.earned_runs_allowed,
        hits_allowed = EXCLUDED.hits_allowed,
        home_runs_allowed = EXCLUDED.home_runs_allowed,
        walks_allowed = EXCLUDED.walks_allowed,
        strikeouts_recorded = EXCLUDED.strikeouts_recorded,
        left_on_base = EXCLUDED.left_on_base,
        double_plays = EXCLUDED.double_plays,
        source_name = EXCLUDED.source_name,
        updated_at = CURRENT_TIMESTAMP;
"""


UPSERT_PITCHER_STATISTICS_QUERY = """
    INSERT INTO player_game_pitching_statistics (
        game_id,
        team_id,
        baseball_player_id,
        appearance_order,
        is_starter,
        pitching_outs,
        batters_faced,
        hits_allowed,
        runs_allowed,
        earned_runs_allowed,
        home_runs_allowed,
        walks_allowed,
        intentional_walks_allowed,
        strikeouts,
        hit_batters,
        pitches_thrown,
        strikes_thrown,
        decision,
        save_recorded,
        hold_recorded,
        blown_save_recorded,
        source_name
    )
    VALUES (
        %s, %s, %s, %s, %s, %s, %s,
        %s, %s, %s, %s, %s, %s, %s,
        %s, %s, %s, %s, %s, %s, %s,
        %s
    )
    ON CONFLICT (game_id, baseball_player_id)
    DO UPDATE SET
        team_id = EXCLUDED.team_id,
        appearance_order = EXCLUDED.appearance_order,
        is_starter = EXCLUDED.is_starter,
        pitching_outs = EXCLUDED.pitching_outs,
        batters_faced = EXCLUDED.batters_faced,
        hits_allowed = EXCLUDED.hits_allowed,
        runs_allowed = EXCLUDED.runs_allowed,
        earned_runs_allowed = EXCLUDED.earned_runs_allowed,
        home_runs_allowed = EXCLUDED.home_runs_allowed,
        walks_allowed = EXCLUDED.walks_allowed,
        intentional_walks_allowed = (
            EXCLUDED.intentional_walks_allowed
        ),
        strikeouts = EXCLUDED.strikeouts,
        hit_batters = EXCLUDED.hit_batters,
        pitches_thrown = EXCLUDED.pitches_thrown,
        strikes_thrown = EXCLUDED.strikes_thrown,
        decision = EXCLUDED.decision,
        save_recorded = EXCLUDED.save_recorded,
        hold_recorded = EXCLUDED.hold_recorded,
        blown_save_recorded = EXCLUDED.blown_save_recorded,
        source_name = EXCLUDED.source_name,
        updated_at = CURRENT_TIMESTAMP;
"""


def save_parsed_boxscore(
    parsed_boxscore: ParsedBoxScore,
    *,
    connection_factory: ConnectionFactory = get_connection,
) -> None:
    """
    Persist one fully parsed MLB box score in a single transaction.

    The game context, team statistics, and pitcher appearances are
    committed atomically.
    """

    connection = connection_factory()

    try:
        with connection.cursor() as cursor:
            _update_game(
                cursor=cursor,
                parsed_boxscore=parsed_boxscore,
            )

            for statistics in parsed_boxscore.team_statistics:
                _upsert_team_statistics(
                    cursor=cursor,
                    statistics=statistics,
                )

            for statistics in parsed_boxscore.pitcher_statistics:
                _upsert_pitcher_statistics(
                    cursor=cursor,
                    statistics=statistics,
                )

        connection.commit()

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()


def _update_game(
    *,
    cursor: Any,
    parsed_boxscore: ParsedBoxScore,
) -> None:
    """
    Update canonical game context from the parsed MLB box score.
    """

    doubleheader_status = (
        "doubleheader"
        if parsed_boxscore.double_header
        else "single"
    )

    cursor.execute(
        UPDATE_GAME_QUERY,
        (
            parsed_boxscore.game_number,
            doubleheader_status,
            parsed_boxscore.game_id,
        ),
    )

    if cursor.rowcount == 0:
        raise LookupError(
            "Canonical game does not exist: "
            f"{parsed_boxscore.game_id}"
        )


def _upsert_team_statistics(
    *,
    cursor: Any,
    statistics: TeamGameStatistics,
) -> None:
    """
    Insert or update one team statistics record.
    """

    cursor.execute(
        UPSERT_TEAM_STATISTICS_QUERY,
        (
            statistics.game_id,
            statistics.team_id,
            statistics.is_home,
            statistics.runs,
            statistics.hits,
            statistics.errors,
            statistics.at_bats,
            statistics.plate_appearances,
            statistics.doubles,
            statistics.triples,
            statistics.home_runs,
            statistics.walks,
            statistics.intentional_walks,
            statistics.strikeouts,
            statistics.hit_by_pitch,
            statistics.sacrifice_flies,
            statistics.stolen_bases,
            statistics.caught_stealing,
            statistics.pitching_outs,
            statistics.runs_allowed,
            statistics.earned_runs_allowed,
            statistics.hits_allowed,
            statistics.home_runs_allowed,
            statistics.walks_allowed,
            statistics.strikeouts_recorded,
            statistics.left_on_base,
            statistics.double_plays,
            statistics.source_name,
        ),
    )


def _upsert_pitcher_statistics(
    *,
    cursor: Any,
    statistics: PlayerGamePitchingStatistics,
) -> None:
    """
    Insert or update one pitcher appearance record.
    """

    decision = (
        statistics.decision.value
        if statistics.decision is not None
        else None
    )

    cursor.execute(
        UPSERT_PITCHER_STATISTICS_QUERY,
        (
            statistics.game_id,
            statistics.team_id,
            statistics.baseball_player_id,
            statistics.appearance_order,
            statistics.is_starter,
            statistics.pitching_outs,
            statistics.batters_faced,
            statistics.hits_allowed,
            statistics.runs_allowed,
            statistics.earned_runs_allowed,
            statistics.home_runs_allowed,
            statistics.walks_allowed,
            statistics.intentional_walks_allowed,
            statistics.strikeouts,
            statistics.hit_batters,
            statistics.pitches_thrown,
            statistics.strikes_thrown,
            decision,
            statistics.save_recorded,
            statistics.hold_recorded,
            statistics.blown_save_recorded,
            statistics.source_name,
        ),
    )