from collections.abc import Iterable, Mapping
from dataclasses import dataclass
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


@dataclass(frozen=True)
class ReviewedTimestampOverride:
    source_name: str
    external_game_id: str
    provider_gameday: str
    provider_gametime: str
    corrected_gameday: str
    corrected_gametime: str
    reason: str
    provenance: str


# Reviewed, identity-specific corrections. This is deliberately not a heuristic.
REVIEWED_TIMESTAMP_OVERRIDES = {
    (SOURCE_NAME, "2018_07_TEN_LAC"): ReviewedTimestampOverride(
        source_name=SOURCE_NAME,
        external_game_id="2018_07_TEN_LAC",
        provider_gameday="2018-10-21",
        provider_gametime="21:30",
        corrected_gameday="2018-10-21",
        corrected_gametime="09:30",
        reason="nflverse encoded the Wembley kickoff twelve hours late",
        provenance=(
            "docs/architecture/nflverse_2018_2025_coverage_audit.md; "
            "https://www.nfl.com/news/nfl-announces-times-dates-for-2018-"
            "london-games-0ap3000000927291"
        ),
    ),
    (SOURCE_NAME, "2018_08_PHI_JAX"): ReviewedTimestampOverride(
        source_name=SOURCE_NAME,
        external_game_id="2018_08_PHI_JAX",
        provider_gameday="2018-10-28",
        provider_gametime="21:30",
        corrected_gameday="2018-10-28",
        corrected_gametime="09:30",
        reason="nflverse encoded the Wembley kickoff twelve hours late",
        provenance=(
            "docs/architecture/nflverse_2018_2025_coverage_audit.md; "
            "https://www.nfl.com/news/nfl-announces-times-dates-for-2018-"
            "london-games-0ap3000000927291"
        ),
    ),
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
    source_season_type = _required_text(row, "season_type")
    if source_season_type == "REG":
        season_type = NflSeasonType.REGULAR
    elif source_season_type == "POST":
        season_type = NflSeasonType.POSTSEASON
    else:
        raise ValueError(
            f"Unsupported nflverse team-stat season type: {source_season_type!r}"
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
        passing_yards=_required_signed_integer(row, "passing_yards"),
        passing_touchdowns=_required_integer(row, "passing_tds"),
        passing_interceptions=_required_integer(
            row, "passing_interceptions"
        ),
        sacks_suffered=_required_integer(row, "sacks_suffered"),
        carries=_required_integer(row, "carries"),
        rushing_yards=_required_signed_integer(row, "rushing_yards"),
        rushing_touchdowns=_required_integer(row, "rushing_tds"),
        fumbles_lost=_required_integer(row, "fumbles_lost_total"),
        penalties=_optional_integer(row, "penalties"),
        penalty_yards=_optional_integer(row, "penalty_yards"),
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
    gameday = _required_text(row, "gameday")
    gametime = _required_text(row, "gametime")
    external_game_id = _required_text(row, "game_id")
    override = REVIEWED_TIMESTAMP_OVERRIDES.get((SOURCE_NAME, external_game_id))
    if override is not None:
        if (gameday, gametime) != (
            override.provider_gameday,
            override.provider_gametime,
        ):
            raise ValueError(
                "Reviewed timestamp override does not match provider evidence"
            )
        gameday = override.corrected_gameday
        gametime = override.corrected_gametime
    try:
        game_date = date.fromisoformat(gameday)
        game_time = time.fromisoformat(gametime)
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
    parsed = _required_signed_integer(row, field_name)
    if parsed < 0:
        raise ValueError(f"{field_name} cannot be negative")
    return parsed


def _required_signed_integer(row: Mapping[str, Any], field_name: str) -> int:
    value = row.get(field_name)
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be an integer")
    if isinstance(value, float) and not value.is_integer():
        raise ValueError(f"{field_name} must be an integer")
    if isinstance(value, str) and any(mark in value for mark in (".", "e", "E")):
        raise ValueError(f"{field_name} must be an integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{field_name} must be an integer") from error
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
