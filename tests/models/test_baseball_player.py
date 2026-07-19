from datetime import date, datetime, timezone

from sportsmodel.models.baseball_player import BaseballPlayer
from sportsmodel.models.baseball_player_source import BaseballPlayerSource


def test_baseball_player_defaults() -> None:
    player = BaseballPlayer(
        baseball_player_id=None,
        full_name="Test Player",
    )

    assert player.baseball_player_id is None
    assert player.full_name == "Test Player"
    assert player.bats is None
    assert player.throws is None
    assert player.primary_position is None
    assert player.active_from is None
    assert player.active_through is None
    assert player.is_active is True
    assert player.last_synced_at is None
    assert player.created_at is None
    assert player.updated_at is None


def test_baseball_player_supports_complete_record() -> None:
    synced_at = datetime(2026, 7, 18, 12, 0, tzinfo=timezone.utc)
    created_at = datetime(2026, 7, 18, 12, 1, tzinfo=timezone.utc)
    updated_at = datetime(2026, 7, 18, 12, 2, tzinfo=timezone.utc)

    player = BaseballPlayer(
        baseball_player_id=101,
        full_name="Complete Player",
        bats="L",
        throws="R",
        primary_position="Pitcher",
        active_from=date(2020, 7, 24),
        active_through=None,
        is_active=True,
        last_synced_at=synced_at,
        created_at=created_at,
        updated_at=updated_at,
    )

    assert player.baseball_player_id == 101
    assert player.bats == "L"
    assert player.throws == "R"
    assert player.primary_position == "Pitcher"
    assert player.active_from == date(2020, 7, 24)
    assert player.active_through is None
    assert player.last_synced_at == synced_at
    assert player.created_at == created_at
    assert player.updated_at == updated_at


def test_baseball_player_source_record() -> None:
    created_at = datetime(2026, 7, 18, 12, 0, tzinfo=timezone.utc)

    source = BaseballPlayerSource(
        baseball_player_source_id=201,
        baseball_player_id=101,
        source_name="mlb",
        external_player_id="123456",
        created_at=created_at,
    )

    assert source.baseball_player_source_id == 201
    assert source.baseball_player_id == 101
    assert source.source_name == "mlb"
    assert source.external_player_id == "123456"
    assert source.created_at == created_at


def test_baseball_player_models_are_immutable() -> None:
    player = BaseballPlayer(
        baseball_player_id=None,
        full_name="Immutable Player",
    )

    try:
        player.full_name = "Changed Name"  # type: ignore[misc]
    except AttributeError:
        pass
    else:
        raise AssertionError("BaseballPlayer should be immutable")