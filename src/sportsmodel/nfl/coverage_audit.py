"""Deterministic, provider-data-only coverage audit for nflverse schedules."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import re
from typing import Any

from sportsmodel.nfl.nflverse_parser import parse_nflverse_game_records


IN_SCOPE_GAME_TYPES = frozenset({"REG", "WC", "DIV", "CON", "SB"})
POSTSEASON_GAME_TYPES = frozenset({"WC", "DIV", "CON", "SB"})
REQUIRED_TEXT_FIELDS = (
    "game_id", "season", "game_type", "week", "gameday", "gametime",
    "home_team", "away_team", "location",
)
GAME_ID_PATTERN = re.compile(r"^(\d{4})_(\d{2})_([A-Z0-9]{2,4})_([A-Z0-9]{2,4})$")


@dataclass(frozen=True)
class SeasonCoverage:
    season: int
    regular_rows: int
    postseason_rows: int
    total_rows: int
    unique_game_ids: int
    duplicate_game_ids: int
    unique_teams: int
    final_games: int
    unplayed_games: int
    overtime_games: int
    tied_games: int
    neutral_site_games: int


def _blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _integer(value: Any) -> int | None:
    if isinstance(value, bool) or _blank(value):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def select_rows(
    rows: Iterable[Mapping[str, Any]], season_from: int, season_to: int
) -> list[dict[str, Any]]:
    selected = []
    for row in rows:
        season = _integer(row.get("season"))
        if season is not None and season_from <= season <= season_to:
            if row.get("game_type") in IN_SCOPE_GAME_TYPES:
                selected.append(dict(row))
    return sorted(selected, key=lambda row: (int(row["season"]), row.get("game_id", "")))


def coverage_matrix(rows: Iterable[Mapping[str, Any]]) -> list[SeasonCoverage]:
    grouped: dict[int, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[int(row["season"])].append(row)
    result = []
    for season, season_rows in sorted(grouped.items()):
        ids = [row.get("game_id", "") for row in season_rows if not _blank(row.get("game_id"))]
        teams = {
            str(row[field]).strip()
            for row in season_rows
            for field in ("home_team", "away_team")
            if not _blank(row.get(field))
        }
        finals = [row for row in season_rows if not _blank(row.get("home_score")) and not _blank(row.get("away_score"))]
        result.append(SeasonCoverage(
            season=season,
            regular_rows=sum(row.get("game_type") == "REG" for row in season_rows),
            postseason_rows=sum(row.get("game_type") in POSTSEASON_GAME_TYPES for row in season_rows),
            total_rows=len(season_rows),
            unique_game_ids=len(set(ids)),
            duplicate_game_ids=sum(count - 1 for count in Counter(ids).values() if count > 1),
            unique_teams=len(teams),
            final_games=len(finals),
            unplayed_games=len(season_rows) - len(finals),
            overtime_games=sum(_integer(row.get("overtime")) == 1 for row in finals),
            tied_games=sum(_integer(row.get("home_score")) == _integer(row.get("away_score")) for row in finals),
            neutral_site_games=sum(row.get("location") == "Neutral" for row in season_rows),
        ))
    return result


def validate_rows(rows: Iterable[Mapping[str, Any]], known_teams: set[str]) -> dict[str, dict[int, list[str]]]:
    findings: dict[str, dict[int, list[str]]] = defaultdict(lambda: defaultdict(list))
    for row in rows:
        season = _integer(row.get("season")) or 0
        game_id = str(row.get("game_id") or "<missing>")
        for field in REQUIRED_TEXT_FIELDS:
            if _blank(row.get(field)):
                findings[f"missing_or_blank_{field}"][season].append(game_id)
        match = GAME_ID_PATTERN.fullmatch(game_id)
        if match is None:
            findings["malformed_game_id"][season].append(game_id)
        else:
            if int(match.group(1)) != season:
                findings["game_id_season_mismatch"][season].append(game_id)
            if match.group(3) != row.get("away_team") or match.group(4) != row.get("home_team"):
                findings["game_id_matchup_mismatch"][season].append(game_id)
        week = _integer(row.get("week"))
        if week is None or week <= 0:
            findings["invalid_week"][season].append(game_id)
        for field in ("home_team", "away_team"):
            team = row.get(field)
            if not _blank(team) and team not in known_teams:
                findings[f"unknown_{field}"][season].append(game_id)
        if row.get("home_team") == row.get("away_team") and not _blank(row.get("home_team")):
            findings["identical_home_away_team"][season].append(game_id)
        home_score = _integer(row.get("home_score"))
        away_score = _integer(row.get("away_score"))
        home_present = not _blank(row.get("home_score"))
        away_present = not _blank(row.get("away_score"))
        if home_present != away_present:
            findings["partial_score_state"][season].append(game_id)
        for field, score, present in (("home_score", home_score, home_present), ("away_score", away_score, away_present)):
            if present and (score is None or score < 0):
                findings[f"invalid_{field}"][season].append(game_id)
        final = home_present and away_present
        overtime = _integer(row.get("overtime"))
        if final and overtime not in {0, 1}:
            findings["invalid_final_overtime"][season].append(game_id)
        if not final and not _blank(row.get("overtime")):
            findings["unplayed_with_overtime"][season].append(game_id)
        if final and home_score == away_score and overtime != 1:
            findings["tie_without_overtime"][season].append(game_id)
        if final and home_score == away_score and row.get("game_type") in POSTSEASON_GAME_TYPES:
            findings["postseason_tie"][season].append(game_id)
        if row.get("location") not in {"Home", "Neutral"}:
            findings["invalid_location"][season].append(game_id)
        try:
            datetime.fromisoformat(str(row.get("gameday")))
        except ValueError:
            findings["invalid_gameday"][season].append(game_id)
        try:
            datetime.strptime(str(row.get("gametime")), "%H:%M")
        except ValueError:
            findings["invalid_gametime"][season].append(game_id)
    return {
        category: {season: sorted(ids) for season, ids in sorted(by_season.items())}
        for category, by_season in sorted(findings.items())
    }


def parser_compatibility(rows: Iterable[Mapping[str, Any]], team_identities: Mapping[str, str]) -> dict[str, Any]:
    attempted = succeeded = 0
    rejected: dict[str, list[str]] = defaultdict(list)
    parsed_times: list[tuple[str, str, str]] = []
    for row in rows:
        attempted += 1
        game_id = str(row.get("game_id") or "<missing>")
        try:
            record = parse_nflverse_game_records([row], team_identities=team_identities)[0]
            succeeded += 1
            parsed_times.append((game_id, record.scheduled_start_time.isoformat(), record.scheduled_start_time.astimezone(timezone.utc).isoformat()))
        except (TypeError, ValueError) as error:
            rejected[str(error)].append(game_id)
    return {
        "attempted": attempted,
        "succeeded": succeeded,
        "rejected": attempted - succeeded,
        "rejection_percentage": round((attempted - succeeded) * 100 / attempted, 6) if attempted else 0.0,
        "rejection_categories": {message: {"count": len(ids), "examples": sorted(ids)[:5]} for message, ids in sorted(rejected.items())},
        "parsed_times": parsed_times,
    }


def external_id_integrity(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    by_id: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    missing = []
    malformed = []
    for row in rows:
        game_id = row.get("game_id")
        if _blank(game_id):
            missing.append(f"season={row.get('season')},week={row.get('week')}")
            continue
        game_id = str(game_id).strip()
        by_id[game_id].append(row)
        if GAME_ID_PATTERN.fullmatch(game_id) is None:
            malformed.append(game_id)
    duplicates = {game_id: len(group) for game_id, group in by_id.items() if len(group) > 1}
    conflicting = {}
    for game_id, group in by_id.items():
        matchups = {(row.get("season"), row.get("away_team"), row.get("home_team")) for row in group}
        if len(matchups) > 1:
            conflicting[game_id] = sorted(matchups)
    return {"missing_ids": sorted(missing), "malformed_ids": sorted(set(malformed)), "duplicate_ids": dict(sorted(duplicates.items())), "conflicting_id_matchups": dict(sorted(conflicting.items()))}


def team_identity_audit(rows: Iterable[Mapping[str, Any]], team_rows: Iterable[Mapping[str, Any]], canonical_ids: set[str]) -> dict[str, Any]:
    aliases = {str(row["team_abbr"]).strip(): str(row["team_id"]).strip() for row in team_rows}
    names = {str(row["team_abbr"]).strip(): str(row["team_name"]).strip() for row in team_rows}
    observed = sorted({str(row[field]).strip() for row in rows for field in ("home_team", "away_team") if not _blank(row.get(field))})
    grouped: dict[str, list[str]] = defaultdict(list)
    for alias, external_id in aliases.items():
        grouped[external_id].append(alias)
    return {
        "observed_abbreviations": observed,
        "observed_count": len(observed),
        "unresolved_abbreviations": sorted(alias for alias in observed if alias not in aliases),
        "observed_external_team_ids": sorted({aliases[alias] for alias in observed if alias in aliases}),
        "external_team_id_count": len({aliases[alias] for alias in observed if alias in aliases}),
        "aliases": {external_id: [{"abbreviation": alias, "name": names[alias]} for alias in sorted(group)] for external_id, group in sorted(grouped.items()) if len(group) > 1},
        "provider_ids_not_in_canonical_seed": sorted({aliases[alias] for alias in observed if alias in aliases} - canonical_ids),
        "canonical_seed_ids_not_observed": sorted(canonical_ids - {aliases[alias] for alias in observed if alias in aliases}),
    }


def audit(rows, team_rows, *, season_from: int, season_to: int, canonical_ids: set[str]) -> dict[str, Any]:
    selected = select_rows(rows, season_from, season_to)
    team_rows = list(team_rows)
    identities = {str(row["team_abbr"]).strip(): str(row["team_id"]).strip() for row in team_rows}
    parser = parser_compatibility(selected, identities)
    parsed_times = parser.pop("parsed_times")
    offsets = Counter(value[-6:] for _, value, _ in parsed_times)
    utc_date_rollovers = sum(local[:10] != utc[:10] for _, local, utc in parsed_times)
    suspicious_neutral_times = sorted(
        row["game_id"]
        for row in selected
        if row.get("location") == "Neutral"
        and str(row.get("gametime", "")) >= "21:00"
    )
    return {
        "season_from": season_from,
        "season_to": season_to,
        "total_rows": len(selected),
        "coverage": [asdict(item) for item in coverage_matrix(selected)],
        "validation_findings": validate_rows(selected, set(identities)),
        "parser": parser,
        "external_ids": external_id_integrity(selected),
        "teams": team_identity_audit(selected, team_rows, canonical_ids),
        "timezone": {
            "assumption": "gameday + gametime interpreted as America/New_York",
            "observed_utc_offsets": dict(sorted(offsets.items())),
            "utc_date_rollovers": utc_date_rollovers,
            "suspicious_neutral_kickoff_ids": suspicious_neutral_times,
        },
    }
