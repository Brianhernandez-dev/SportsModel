from dataclasses import FrozenInstanceError
from datetime import date, datetime, timezone

import pytest

from sportsmodel.models.baseball_player_team_assignment import (
    BaseballPlayerTeamAssignment,
)
from sportsmodel.models.baseball_team_source import BaseballTeamSource


def test_baseball_team_source_defaults() -> None:
    source = BaseballTeamSource(
        baseball_team_source_id=None,
        team_id=2,
        source_name="mlb_stats",
        external_team_id="147",
    )

    assert source.baseball_team_source_id is None
    assert source.team_id == 2
    assert source.source_name == "mlb_stats"
    assert source.external_team_id == "147"
    assert source.created_at is None


def test_baseball_player_team_assignment_defaults() -> None:
    assignment = BaseballPlayerTeamAssignment(
        baseball_player_team_assignment_id=None,
        baseball_player_id=101,
        team_id=2,
    )

    assert assignment.roster_status_code is None
    assert assignment.roster_status_description is None
    assert assignment.jersey_number is None
    assert assignment.position_code is None
    assert assignment.position_name is None
    assert assignment.valid_from is None
    assert assignment.valid_through is None
    assert assignment.is_current is True
    assert assignment.last_synced_at is None


def test_baseball_player_team_assignment_populated() -> None:
    synced_at = datetime(
        2026,
        7,
        18,
        20,
        0,
        tzinfo=timezone.utc,
    )

    assignment = BaseballPlayerTeamAssignment(
        baseball_player_team_assignment_id=301,
        baseball_player_id=101,
        team_id=2,
        roster_status_code="A",
        roster_status_description="Active",
        jersey_number="39",
        position_code="2",
        position_name="Catcher",
        valid_from=date(2026, 7, 18),
        valid_through=None,
        is_current=True,
        last_synced_at=synced_at,
        created_at=synced_at,
        updated_at=synced_at,
    )

    assert assignment.baseball_player_team_assignment_id == 301
    assert assignment.roster_status_code == "A"
    assert assignment.roster_status_description == "Active"
    assert assignment.jersey_number == "39"
    assert assignment.position_code == "2"
    assert assignment.position_name == "Catcher"
    assert assignment.valid_from == date(2026, 7, 18)
    assert assignment.is_current is True
    assert assignment.last_synced_at == synced_at


def test_team_models_are_immutable() -> None:
    source = BaseballTeamSource(
        baseball_team_source_id=None,
        team_id=2,
        source_name="mlb_stats",
        external_team_id="147",
    )

    assignment = BaseballPlayerTeamAssignment(
        baseball_player_team_assignment_id=None,
        baseball_player_id=101,
        team_id=2,
    )

    with pytest.raises(FrozenInstanceError):
        source.team_id = 3

    with pytest.raises(FrozenInstanceError):
        assignment.team_id = 3