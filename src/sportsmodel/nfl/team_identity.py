from dataclasses import dataclass
from enum import StrEnum
import re


FRANCHISE_KEY_PATTERN = re.compile(
    r"^nfl_franchise_[0-9a-f]{8}-"
    r"[0-9a-f]{4}-[0-9a-f]{4}-"
    r"[0-9a-f]{4}-[0-9a-f]{12}$"
)


class NflConference(StrEnum):
    AFC = "AFC"
    NFC = "NFC"


class NflDivision(StrEnum):
    EAST = "East"
    NORTH = "North"
    SOUTH = "South"
    WEST = "West"


@dataclass(frozen=True)
class NflTeamProfile:
    team_id: int
    franchise_key: str
    current_abbreviation: str
    is_active: bool

    def __post_init__(self) -> None:
        _require_positive_team_id(self.team_id)
        if FRANCHISE_KEY_PATTERN.fullmatch(self.franchise_key) is None:
            raise ValueError(
                "NFL franchise key must use "
                "nfl_franchise_<lowercase UUID>."
            )
        _require_abbreviation(self.current_abbreviation)


@dataclass(frozen=True)
class NflTeamSeason:
    team_id: int
    season: int
    display_name: str
    abbreviation: str
    conference: NflConference
    division: NflDivision

    def __post_init__(self) -> None:
        _require_positive_team_id(self.team_id)
        if not 1920 <= self.season <= 2100:
            raise ValueError("NFL season must be between 1920 and 2100.")
        if not self.display_name.strip():
            raise ValueError("NFL season display name cannot be empty.")
        _require_abbreviation(self.abbreviation)


@dataclass(frozen=True)
class NflTeamSource:
    nfl_team_source_id: int
    team_id: int
    source_name: str
    external_team_id: str
    source_team_name: str | None = None

    def __post_init__(self) -> None:
        if self.nfl_team_source_id <= 0:
            raise ValueError("NFL team source ID must be positive.")
        _require_positive_team_id(self.team_id)
        if not self.source_name.strip():
            raise ValueError("NFL team source name cannot be empty.")
        if not self.external_team_id.strip():
            raise ValueError("External NFL team ID cannot be empty.")


def _require_positive_team_id(team_id: int) -> None:
    if team_id <= 0:
        raise ValueError("NFL team ID must be positive.")


def _require_abbreviation(abbreviation: str) -> None:
    if (
        not abbreviation
        or abbreviation != abbreviation.upper()
        or not abbreviation.isalnum()
        or len(abbreviation) > 4
    ):
        raise ValueError(
            "NFL team abbreviation must be 1-4 uppercase letters or digits."
        )
