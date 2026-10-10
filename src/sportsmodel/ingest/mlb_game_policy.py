"""Shared MLB schedule and championship admission policies."""

from collections.abc import Mapping
from datetime import date, datetime
from typing import Any

CHAMPIONSHIP_SEASON_GAME_TYPES = frozenset({"R", "F", "D", "L", "W"})
NON_MODEL_GAME_TYPES = frozenset({"S", "E", "A", "I"})
# Public MLB Stats teams?sportId=1&season=2026. Expansion requires review;
# postseason seed/champion placeholders also have positive provider IDs.
MLB_CLUB_NAMES = {
    108: "Los Angeles Angels", 109: "Arizona Diamondbacks", 110: "Baltimore Orioles",
    111: "Boston Red Sox", 112: "Chicago Cubs", 113: "Cincinnati Reds",
    114: "Cleveland Guardians", 115: "Colorado Rockies", 116: "Detroit Tigers",
    117: "Houston Astros", 118: "Kansas City Royals", 119: "Los Angeles Dodgers",
    120: "Washington Nationals", 121: "New York Mets", 133: "Athletics",
    134: "Pittsburgh Pirates", 135: "San Diego Padres", 136: "Seattle Mariners",
    137: "San Francisco Giants", 138: "St. Louis Cardinals", 139: "Tampa Bay Rays",
    140: "Texas Rangers", 141: "Toronto Blue Jays", 142: "Minnesota Twins",
    143: "Philadelphia Phillies", 144: "Atlanta Braves", 145: "Chicago White Sox",
    146: "Miami Marlins", 147: "New York Yankees", 158: "Milwaukee Brewers",
}
MLB_CLUB_IDS = frozenset(MLB_CLUB_NAMES)
# Historical provider names: Athletics alias is already normalized by the
# repository; Cleveland's 2021 name is verified at teams/114?season=2021.
MLB_CLUB_ALIASES = {133: frozenset({"Oakland Athletics"}),
                    114: frozenset({"Cleveland Indians"})}
NON_PLAYED_STATES = frozenset({"Postponed", "Suspended", "Cancelled", "Canceled"})


def extract_schedule_games(
    schedule_payload: Any,
    *,
    expected_date: date,
) -> tuple[Mapping[str, Any], ...]:
    """Validate one requested-date schedule envelope and return every game."""
    if not isinstance(schedule_payload, Mapping):
        raise ValueError("MLB schedule response was not a mapping")

    date_blocks = schedule_payload.get("dates")
    if not isinstance(date_blocks, list):
        raise ValueError("MLB schedule response dates must be a list")

    games: list[Mapping[str, Any]] = []
    for date_block in date_blocks:
        if not isinstance(date_block, Mapping):
            raise ValueError("MLB schedule date block was not a mapping")

        returned_date_value = date_block.get("date")
        if not isinstance(returned_date_value, str):
            raise ValueError("MLB schedule date block lacks a valid ISO date")
        try:
            returned_date = date.fromisoformat(returned_date_value)
        except ValueError:
            raise ValueError("MLB schedule date block lacks a valid ISO date") from None
        if returned_date.isoformat() != returned_date_value:
            raise ValueError("MLB schedule date block lacks a valid ISO date")
        if returned_date != expected_date:
            raise ValueError("MLB schedule returned a date other than the requested date")

        date_games = date_block.get("games")
        if not isinstance(date_games, list):
            raise ValueError("MLB schedule date block games must be a list")
        for game in date_games:
            if not isinstance(game, Mapping):
                raise ValueError("MLB schedule game entry was not a mapping")
            games.append(game)

    return tuple(games)


def championship_game_type(game: dict) -> bool:
    """False is an intentional non-model exclusion, never an unknown type."""
    value = game.get("gameType")
    if not isinstance(value, str):
        raise ValueError("Missing/malformed MLB gameType; verify the schedule contract")
    if value in CHAMPIONSHIP_SEASON_GAME_TYPES:
        return True
    if value in NON_MODEL_GAME_TYPES:
        return False
    raise ValueError("Unknown/unsupported MLB gameType; verify the schedule contract")


def confirmed_championship_game(game: dict) -> bool:
    """Defer conditional/unresolved postseason games before team persistence.

    A Y flag alone is not a confirmed game even with real clubs and fixed time.
    Played Final/Live evidence can establish occurrence; otherwise require N.
    Regular-season admission keeps its existing participant validation contract.
    """
    if not championship_game_type(game):
        return False
    if game["gameType"] == "R":
        return True
    status = game.get("status")
    if not isinstance(status, dict):
        raise ValueError("Postseason game has malformed/missing status")
    flag = game.get("ifNecessary")
    if flag not in ("N", "Y"):
        raise ValueError("Postseason game lacks recognized ifNecessary confirmation")
    if status.get("detailedState") in NON_PLAYED_STATES:
        return False
    played = status.get("abstractGameState") in ("Live", "Final") or status.get("detailedState") == "Final"
    if flag == "Y" and not played:
        return False
    tbd = status.get("startTimeTBD", False)
    if type(tbd) is not bool:
        raise ValueError("Postseason startTimeTBD must be boolean")
    if tbd:
        return False
    if type(game.get("gamePk")) is not int or game["gamePk"] <= 0:
        raise ValueError("Confirmed postseason game requires a positive gamePk")
    value = game.get("gameDate")
    if not isinstance(value, str):
        raise ValueError("Confirmed postseason game requires an aware start timestamp")
    start = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if start.tzinfo is None or start.utcoffset() is None:
        raise ValueError("Confirmed postseason game requires an aware start timestamp")
    ids = []
    teams = game.get("teams")
    if not isinstance(teams, dict):
        raise ValueError("Postseason game has malformed/missing participants")
    for side in ("home", "away"):
        section = teams.get(side, {})
        team = section.get("team", {}) if isinstance(section, dict) else {}
        if not isinstance(team, dict) or type(team.get("id")) is not int or team["id"] not in MLB_CLUB_IDS:
            raise ValueError("Postseason participant is unresolved or not a recognized MLB club")
        name = team.get("name")
        if not isinstance(name, str) or " ".join(name.split()) not in (
            {MLB_CLUB_NAMES[team["id"]]} | MLB_CLUB_ALIASES.get(team["id"], frozenset())
        ):
            raise ValueError("Postseason participant name is unresolved")
        ids.append(team["id"])
    if ids[0] == ids[1]:
        raise ValueError("Postseason participants must be distinct")
    return True
