from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class NflSeasonType(StrEnum):
    PRESEASON = "preseason"
    REGULAR = "regular"
    POSTSEASON = "postseason"


class NflGameStatus(StrEnum):
    FINAL = "final"
    UNPLAYED = "unplayed"


@dataclass(frozen=True)
class NflTeamSourceRecord:
    """One provider-owned NFL team identity or historical alias."""

    source_name: str
    external_team_id: str
    abbreviation: str
    display_name: str
    nickname: str
    conference: str
    division: str

    def __post_init__(self) -> None:
        _require_text(self.source_name, "source_name")
        _require_text(self.external_team_id, "external_team_id")
        _require_text(self.abbreviation, "abbreviation")
        _require_text(self.display_name, "display_name")
        _require_text(self.nickname, "nickname")
        if self.conference not in {"AFC", "NFC"}:
            raise ValueError("conference must be AFC or NFC")
        if self.division not in {
            "AFC East",
            "AFC North",
            "AFC South",
            "AFC West",
            "NFC East",
            "NFC North",
            "NFC South",
            "NFC West",
        }:
            raise ValueError("division is not a recognized NFL division")


@dataclass(frozen=True)
class NflGameSourceRecord:
    """Provider-neutral schedule or result record for one NFL game."""

    source_name: str
    external_game_id: str
    season: int
    season_type: NflSeasonType
    week: int
    week_label: str
    scheduled_start_time: datetime
    home_external_team_id: str
    away_external_team_id: str
    status: NflGameStatus
    home_score: int | None
    away_score: int | None
    overtime: bool | None
    neutral_site: bool

    def __post_init__(self) -> None:
        _require_text(self.source_name, "source_name")
        _require_text(self.external_game_id, "external_game_id")
        _require_text(self.home_external_team_id, "home_external_team_id")
        _require_text(self.away_external_team_id, "away_external_team_id")
        _require_text(self.week_label, "week_label")
        if self.season < 1920:
            raise ValueError("season is outside the NFL data range")
        if self.week <= 0:
            raise ValueError("week must be positive")
        if self.scheduled_start_time.tzinfo is None:
            raise ValueError("scheduled_start_time must be timezone-aware")
        if self.home_external_team_id == self.away_external_team_id:
            raise ValueError("home and away teams must be different")
        if self.status is NflGameStatus.FINAL:
            if self.home_score is None or self.away_score is None:
                raise ValueError("final games require both scores")
            if self.overtime is None:
                raise ValueError("final games require an overtime value")
        elif any(
            value is not None
            for value in (self.home_score, self.away_score, self.overtime)
        ):
            raise ValueError("unplayed games cannot contain result fields")
        for score in (self.home_score, self.away_score):
            if score is not None and score < 0:
                raise ValueError("scores cannot be negative")
        if (
            self.season_type is NflSeasonType.POSTSEASON
            and self.status is NflGameStatus.FINAL
            and self.home_score == self.away_score
        ):
            raise ValueError("postseason games cannot end in a tie")


@dataclass(frozen=True)
class NflTeamGameStatisticsSourceRecord:
    """Stable team/game aggregates selected from nflverse team stats."""

    source_name: str
    external_game_id: str
    season: int
    season_type: NflSeasonType
    week: int
    team_external_id: str
    opponent_external_id: str
    completions: int
    pass_attempts: int
    passing_yards: int
    passing_touchdowns: int
    passing_interceptions: int
    sacks_suffered: int
    carries: int
    rushing_yards: int
    rushing_touchdowns: int
    fumbles_lost: int
    penalties: int
    penalty_yards: int

    def __post_init__(self) -> None:
        for field_name in (
            "source_name",
            "external_game_id",
            "team_external_id",
            "opponent_external_id",
        ):
            _require_text(getattr(self, field_name), field_name)
        if self.team_external_id == self.opponent_external_id:
            raise ValueError("team and opponent must be different")
        if self.season < 1920 or self.week <= 0:
            raise ValueError("season and week must be positive NFL values")
        for field_name in (
            "completions",
            "pass_attempts",
            "passing_yards",
            "passing_touchdowns",
            "passing_interceptions",
            "sacks_suffered",
            "carries",
            "rushing_yards",
            "rushing_touchdowns",
            "fumbles_lost",
            "penalties",
            "penalty_yards",
        ):
            if getattr(self, field_name) < 0:
                raise ValueError(f"{field_name} cannot be negative")
        if self.completions > self.pass_attempts:
            raise ValueError("completions cannot exceed pass attempts")


def _require_text(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} cannot be blank")
