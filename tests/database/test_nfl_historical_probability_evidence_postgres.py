import psycopg2
import pytest
from urllib.parse import urlparse

from sportsmodel.database.nfl_historical_probability_evidence_repository import (
    _capture_snapshot_identity,
    _require_read_only_repeatable_transaction,
)


def test_snapshot_guard_accepts_only_read_only_repeatable_postgres_transaction(
    initialized_nfl_test_database,
) -> None:
    connection = psycopg2.connect(initialized_nfl_test_database)
    try:
        connection.set_session(isolation_level="REPEATABLE READ", readonly=True)
        with connection.cursor() as cursor:
            _require_read_only_repeatable_transaction(cursor)
            cursor.execute("SELECT txid_current_if_assigned();")
            assert cursor.fetchone()[0] is None
        connection.rollback()
    finally:
        connection.close()


def test_snapshot_guard_rejects_default_read_write_transaction(
    initialized_nfl_test_database,
) -> None:
    connection = psycopg2.connect(initialized_nfl_test_database)
    try:
        with connection.cursor() as cursor:
            with pytest.raises(RuntimeError, match="read-only REPEATABLE READ"):
                _require_read_only_repeatable_transaction(cursor)
        connection.rollback()
    finally:
        connection.close()


def test_snapshot_identity_is_captured_in_the_guarded_transaction(
    initialized_nfl_test_database,
) -> None:
    connection = psycopg2.connect(initialized_nfl_test_database)
    try:
        connection.set_session(isolation_level="REPEATABLE READ", readonly=True)
        with connection.cursor() as cursor:
            _require_read_only_repeatable_transaction(cursor)
            reconstructed_at, database, server, snapshot = _capture_snapshot_identity(
                cursor
            )
            target = urlparse(initialized_nfl_test_database)
            assert reconstructed_at.tzinfo is not None
            assert database["database"] == target.path.lstrip("/")
            assert database["configured_host"] == target.hostname
            assert database["configured_port"] == target.port
            assert isinstance(server["server_port"], int)
            assert server["server_version_num"].isdigit()
            assert snapshot["transaction_isolation"] == "repeatable read"
            assert snapshot["transaction_read_only"] is True
            assert snapshot["snapshot_id"]
        connection.rollback()
    finally:
        connection.close()
