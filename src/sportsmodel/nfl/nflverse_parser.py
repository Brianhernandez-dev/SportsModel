from collections.abc import Iterable, Mapping
from datetime import date, datetime, time
from typing import Any
from zoneinfo import ZoneInfo

from sportsmodel.nfl.models import (
    NflGameSourceRecord,
    NflGameStatus,
    NflSeasonType,
    NflTeamGameStatisticsSourceRecord,
    NflTeamSourceRecord,
)


SOURCE_NAME = "nflverse"
NFLVERSE_SCHEDULE_TIME_ZONE = ZoneInfo("America/New_York")

_POSTSEASON_LABELS = {
    "WC": "Wild Card",
    "DIV": "Divisional",
    "CON": "Conference Championship",
    "SB": "Super Bowl",
}


def parse_nflverse_team_records(
    rows: Iterable[Mapping[str, Any]],
) -> tuple[NflTeamSourceRecord, ...]:
    records = tuple(_parse_team(row) for row in rows)
    return tuple(sorted(records, key=lambda record: record.abbreviation))


def build_nflverse_team_identity_index(
    records: Iterable[NflTeamSourceRecord],
) -> dict[str, str]:
    identities: dict[str, str] = {}
    for record in records:
        existing = identities.get(record.abbreviation)
        if existing is not None and existing != record.external_team_id:
            raise ValueError(
                "Team abbreviation maps to multiple external identities: "
                f"{record.abbreviation}"
            )
        identities[record.abbreviation] = record.external_team_id
    return identities


def parse_nflverse_game_records(
    rows: Iterable[Mapping[str, Any]],
    *,
    team_identities: Mapping[str, str],
) -> tuple[NflGameSourceRecord, ...]:
    records = tuple(
        _parse_game(row, team_identities=team_identities)
        for row in rows
    )
    return tuple(
        sorted(
            records,
            key=lambda record: (
                record.scheduled_start_time,
                record.external_game_id,
            ),
        )
    )


def parse_nflverse_team_game_statistics_records(
    rows: Iterable[Mapping[str, Any]],
    *,
    team_identities: Mapping[str, str],
) -> tuple[NflTeamGameStatisticsSourceRecord, ...]:
    records = tuple(
        _parse_team_statistics(row, team_identities=team_identities)
        for row in rows
    )
    return tuple(
        sorted(
            records,
            key=lambda record: (
                record.external_game_id,
                record.team_external_id,
            ),
        )
    )


def _parse_team(row: Mapping[str, Any]) -> NflTeamSourceRecord:
    return NflTeamSourceRecord(
        source_name=SOURCE_NAME,
        external_team_id=_required_text(row, "team_id"),
        abbreviation=_required_text(row, "team_abbr"),
        display_name=_required_text(row, "team_name"),
        nickname=_required_text(row, "team_nick"),
        conference=_required_text(row, "team_conf"),
        division=_required_text(row, "team_division"),
    )


def _parse_game(
    row: Mapping[str, Any],
    *,
    team_identities: Mapping[str, str],
) -> NflGameSourceRecord:
    game_type = _required_text(row, "game_type")
    season_type, week_label = _normalize_game_type(game_type)
    home_abbreviation = _required_text(row, "home_team")
    away_abbreviation = _required_text(row, "away_team")
    home_external_id = _resolve_team(
        home_abbreviation,
        team_identities=team_identities,
    )
    away_external_id = _resolve_team(
        away_abbreviation,
        team_identities=team_identities,
    )
    home_score = _optional_integer(row, "home_score")
    away_score = _optional_integer(row, "away_score")

    if (home_score is None) != (away_score is None):
        raise ValueError("home_score and away_score must both be present or absent")

    if home_score is None:
        status = NflGameStatus.UNPLAYED
        overtime = None
    else:
        status = NflGameStatus.FINAL
        overtime = _required_boolean_integer(row, "overtime")

    location = _required_text(row, "location")
    if location not in {"Home", "Neutral"}:
        raise ValueError(f"Unsupported nflverse location: {location!r}")

    return NflGameSourceRecord(
        source_name=SOURCE_NAME,
        external_game_id=_required_text(row, "game_id"),
        season=_required_integer(row, "season"),
        season_type=season_type,
        week=_required_integer(row, "week"),
        week_label=week_label,
        scheduled_start_time=_parse_scheduled_start(row),
        home_external_team_id=home_external_id,
        away_external_team_id=away_external_id,
        status=status,
        home_score=home_score,
        away_score=away_score,
        overtime=overtime,
        neutral_site=location == "Neutral",
    )


def _parse_team_statistics(
    row: Mapping[str, Any],
    *,
    team_identities: Mapping[str, str],
) -> NflTeamGameStatisticsSourceRecord:
    season_type, _ = _normalize_game_type(
        _required_text(row, "season_type")
    )
    return NflTeamGameStatisticsSourceRecord(
        source_name=SOURCE_NAME,
        external_game_id=_required_text(row, "game_id"),
        season=_required_integer(row, "season"),
        season_type=season_type,
        week=_required_integer(row, "week"),
        team_external_id=_resolve_team(
            _required_text(row, "team"),
            team_identities=team_identities,
        ),
        opponent_external_id=_resolve_team(
            _required_text(row, "opponent_team"),
            team_identities=team_identities,
        ),
        completions=_required_integer(row, "completions"),
        pass_attempts=_required_integer(row, "attempts"),
        passing_yards=_required_integer(row, "passing_yards"),
        passing_touchdowns=_required_integer(row, "passing_tds"),
        passing_interceptions=_required_integer(
            row, "passing_interceptions"
        ),
        sacks_suffered=_required_integer(row, "sacks_suffered"),
        carries=_required_integer(row, "carries"),
        rushing_yards=_required_integer(row, "rushing_yards"),
        rushing_touchdowns=_required_integer(row, "rushing_tds"),
        fumbles_lost=_required_integer(row, "fumbles_lost_total"),
        penalties=_required_integer(row, "penalties"),
        penalty_yards=_required_integer(row, "penalty_yards"),
    )


def _normalize_game_type(value: str) -> tuple[NflSeasonType, str]:
    if value == "REG":
        return NflSeasonType.REGULAR, "Regular Season"
    if value == "PRE":
        return NflSeasonType.PRESEASON, "Preseason"
    if value in _POSTSEASON_LABELS:
        return NflSeasonType.POSTSEASON, _POSTSEASON_LABELS[value]
    if value == "POST":
        return NflSeasonType.POSTSEASON, "Postseason"
    raise ValueError(f"Unsupported nflverse game type: {value!r}")


def _parse_scheduled_start(row: Mapping[str, Any]) -> datetime:
    try:
        game_date = date.fromisoformat(_required_text(row, "gameday"))
        game_time = time.fromisoformat(_required_text(row, "gametime"))
    except ValueError as error:
        raise ValueError("Invalid nflverse gameday or gametime") from error
    return datetime.combine(
        game_date,
        game_time,
        tzinfo=NFLVERSE_SCHEDULE_TIME_ZONE,
    )


def _resolve_team(
    abbreviation: str,
    *,
    team_identities: Mapping[str, str],
) -> str:
    try:
        return team_identities[abbreviation]
    except KeyError as error:
        raise ValueError(
            f"Unknown nflverse team abbreviation: {abbreviation!r}"
        ) from error


def _required_text(row: Mapping[str, Any], field_name: str) -> str:
    value = row.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} is required")
    return value.strip()


def _required_integer(row: Mapping[str, Any], field_name: str) -> int:
    value = row.get(field_name)
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be an integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{field_name} must be an integer") from error
    if parsed < 0:
        raise ValueError(f"{field_name} cannot be negative")
    return parsed


def _optional_integer(row: Mapping[str, Any], field_name: str) -> int | None:
    value = row.get(field_name)
    if value is None or value == "":
        return None
    return _required_integer(row, field_name)


def _required_boolean_integer(row: Mapping[str, Any], field_name: str) -> bool:
    value = _required_integer(row, field_name)
    if value not in {0, 1}:
        raise ValueError(f"{field_name} must be 0 or 1")
    return bool(value)
