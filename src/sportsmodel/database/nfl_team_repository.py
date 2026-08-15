from typing import Any

from sportsmodel.nfl.team_identity import (
    NflConference,
    NflDivision,
    NflTeamProfile,
    NflTeamSeason,
    NflTeamSource,
)


def load_nfl_team_by_franchise_key(
    cursor: Any,
    *,
    franchise_key: str,
) -> NflTeamProfile:
    cursor.execute(
        """
        SELECT
            team_id,
            franchise_key,
            current_abbreviation,
            is_active
        FROM nfl_team_profiles
        WHERE franchise_key = %s;
        """,
        (franchise_key,),
    )
    return _require_profile(cursor.fetchone(), franchise_key)


def load_nfl_team_by_id(
    cursor: Any,
    *,
    team_id: int,
) -> NflTeamProfile:
    _require_positive_identifier(team_id, "NFL team ID")
    cursor.execute(
        """
        SELECT
            team_id,
            franchise_key,
            current_abbreviation,
            is_active
        FROM nfl_team_profiles
        WHERE team_id = %s;
        """,
        (team_id,),
    )
    return _require_profile(cursor.fetchone(), str(team_id))


def resolve_nfl_team_by_source(
    cursor: Any,
    *,
    source_name: str,
    external_team_id: str,
) -> NflTeamProfile:
    normalized_source = _require_text(source_name, "Source name")
    normalized_external_id = _require_text(
        external_team_id,
        "External NFL team ID",
    )
    cursor.execute(
        """
        SELECT
            profile.team_id,
            profile.franchise_key,
            profile.current_abbreviation,
            profile.is_active
        FROM nfl_team_sources AS source
        JOIN nfl_team_profiles AS profile
          ON profile.team_id = source.team_id
        WHERE
            source.source_name = %s
            AND source.external_team_id = %s;
        """,
        (normalized_source, normalized_external_id),
    )
    row = cursor.fetchone()
    if row is None:
        raise LookupError(
            "Unknown NFL team source mapping: "
            f"{normalized_source}/{normalized_external_id}."
        )
    return _profile_from_row(row)


def list_active_nfl_teams(cursor: Any) -> tuple[NflTeamProfile, ...]:
    cursor.execute(
        """
        SELECT
            team_id,
            franchise_key,
            current_abbreviation,
            is_active
        FROM nfl_team_profiles
        WHERE is_active = TRUE
        ORDER BY current_abbreviation;
        """
    )
    return tuple(_profile_from_row(row) for row in cursor.fetchall())


def load_nfl_team_season(
    cursor: Any,
    *,
    team_id: int,
    season: int,
) -> NflTeamSeason:
    _require_positive_identifier(team_id, "NFL team ID")
    cursor.execute(
        """
        SELECT
            team_id,
            season,
            display_name,
            abbreviation,
            conference,
            division
        FROM nfl_team_seasons
        WHERE team_id = %s AND season = %s;
        """,
        (team_id, season),
    )
    row = cursor.fetchone()
    if row is None:
        raise LookupError(
            f"NFL season identity was not found for team {team_id}, "
            f"season {season}."
        )
    return NflTeamSeason(
        team_id=row[0],
        season=row[1],
        display_name=row[2],
        abbreviation=row[3],
        conference=NflConference(row[4]),
        division=NflDivision(row[5]),
    )


def upsert_nfl_team_source(
    cursor: Any,
    *,
    team_id: int,
    source_name: str,
    external_team_id: str,
    source_team_name: str | None = None,
) -> NflTeamSource:
    load_nfl_team_by_id(cursor, team_id=team_id)
    normalized_source = _require_text(source_name, "Source name")
    normalized_external_id = _require_text(
        external_team_id,
        "External NFL team ID",
    )
    normalized_team_name = (
        source_team_name.strip()
        if source_team_name is not None and source_team_name.strip()
        else None
    )
    cursor.execute(
        """
        INSERT INTO nfl_team_sources (
            team_id,
            source_name,
            external_team_id,
            source_team_name
        )
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (source_name, external_team_id)
        DO UPDATE SET
            source_team_name = EXCLUDED.source_team_name,
            updated_at = CURRENT_TIMESTAMP
        WHERE nfl_team_sources.team_id = EXCLUDED.team_id
        RETURNING
            nfl_team_source_id,
            team_id,
            source_name,
            external_team_id,
            source_team_name;
        """,
        (
            team_id,
            normalized_source,
            normalized_external_id,
            normalized_team_name,
        ),
    )
    row = cursor.fetchone()
    if row is None:
        raise ValueError(
            "NFL source identity is already mapped to a different team: "
            f"{normalized_source}/{normalized_external_id}."
        )
    return NflTeamSource(
        nfl_team_source_id=row[0],
        team_id=row[1],
        source_name=row[2],
        external_team_id=row[3],
        source_team_name=row[4],
    )


def _profile_from_row(row: tuple[Any, ...]) -> NflTeamProfile:
    return NflTeamProfile(
        team_id=row[0],
        franchise_key=row[1],
        current_abbreviation=row[2],
        is_active=row[3],
    )


def _require_profile(
    row: tuple[Any, ...] | None,
    identity: str,
) -> NflTeamProfile:
    if row is None:
        raise LookupError(f"NFL team was not found: {identity}.")
    return _profile_from_row(row)


def _require_text(value: str, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} cannot be empty.")
    return normalized


def _require_positive_identifier(value: int, field_name: str) -> None:
    if value <= 0:
        raise ValueError(f"{field_name} must be greater than zero.")
