from __future__ import annotations

import os

import pytest

from tests.database import conftest as database_conftest
from tests.database import disposable_postgres as safety


VALID_DATABASE = "sportsmodel_test_0123456789ab"
VALID_MARKER = "m" * 32
VALID_INSTANCE = "a" * 64
PRODUCTION_SYSTEM_ID = "9999999999999999999"
TEST_SYSTEM_ID = "8888888888888888888"


def _environment(database_url: str | None = None, **overrides: str) -> dict[str, str]:
    values = {
        safety.TEST_DATABASE_URL: (
            database_url
            or f"postgresql://sportsmodel_test:test@127.0.0.1:55435/{VALID_DATABASE}"
        ),
        safety.DESTRUCTIVE_ACKNOWLEDGEMENT: "1",
        safety.DISPOSABLE_MARKER: VALID_MARKER,
        safety.DISPOSABLE_INSTANCE_ID: VALID_INSTANCE,
        safety.PRODUCTION_SYSTEM_IDENTIFIER: PRODUCTION_SYSTEM_ID,
    }
    values.update(overrides)
    return values


@pytest.mark.parametrize("host", ("127.0.0.1", "localhost"))
def test_production_port_is_rejected_before_connection(host: str, monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(safety.psycopg2, "connect", lambda url: calls.append(url))
    environment = _environment(
        f"postgresql://sportsmodel_test:test@{host}:5432/{VALID_DATABASE}"
    )

    with pytest.raises(safety.DisposableDatabaseSafetyError, match="port 5432"):
        safety.open_verified_disposable_database(environment)

    assert calls == []


def test_production_database_name_is_rejected_before_connection(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(safety.psycopg2, "connect", lambda url: calls.append(url))
    environment = _environment(
        "postgresql://sportsmodel_test:test@127.0.0.1:55435/sportsmodel"
    )

    with pytest.raises(
        safety.DisposableDatabaseSafetyError,
        match="production database name",
    ):
        safety.open_verified_disposable_database(environment)

    assert calls == []


@pytest.mark.parametrize(
    ("missing", "message"),
    (
        (safety.TEST_DATABASE_URL, "TEST_DATABASE_URL.*required"),
        (safety.DESTRUCTIVE_ACKNOWLEDGEMENT, "ALLOW_DESTRUCTIVE_TEST_DB=1"),
        (safety.DISPOSABLE_MARKER, "DATABASE_MARKER"),
        (safety.DISPOSABLE_INSTANCE_ID, "DATABASE_INSTANCE_ID"),
        (safety.PRODUCTION_SYSTEM_IDENTIFIER, "PRODUCTION_DATABASE_SYSTEM_IDENTIFIER"),
    ),
)
def test_missing_explicit_test_authorization_fails_closed(
    missing: str,
    message: str,
) -> None:
    environment = _environment()
    del environment[missing]

    with pytest.raises(safety.DisposableDatabaseSafetyError, match=message):
        safety.require_disposable_database_configuration(environment)


def test_application_database_url_overlap_is_rejected() -> None:
    environment = _environment()
    environment["DATABASE_URL"] = environment[safety.TEST_DATABASE_URL]

    with pytest.raises(safety.DisposableDatabaseSafetyError, match="DATABASE_URL"):
        safety.require_disposable_database_configuration(environment)


def test_application_postgres_identity_overlap_is_rejected() -> None:
    environment = _environment(
        POSTGRES_HOST="localhost",
        POSTGRES_PORT="55435",
        POSTGRES_DB=VALID_DATABASE,
    )

    with pytest.raises(safety.DisposableDatabaseSafetyError, match=r"POSTGRES_\*"):
        safety.require_disposable_database_configuration(environment)


@pytest.mark.parametrize(
    ("database_url", "message"),
    (
        ("not-a-postgresql-url", "malformed"),
        (
            f"postgresql://sportsmodel_test:test@127.0.0.1/{VALID_DATABASE}",
            "explicitly contain",
        ),
        (
            "postgresql://sportsmodel_test:test@127.0.0.1:55435/test",
            "generated sportsmodel_test",
        ),
        (
            f"postgresql://wrong_user:test@127.0.0.1:55435/{VALID_DATABASE}",
            "user must be sportsmodel_test",
        ),
        (
            f"postgresql://sportsmodel_test:test@db.example:55435/{VALID_DATABASE}",
            "explicit loopback endpoint",
        ),
        (
            f"postgresql://sportsmodel_test:test@127.0.0.1:55435/{VALID_DATABASE}"
            "?hostaddr=127.0.0.2",
            "alternate PostgreSQL routing",
        ),
    ),
)
def test_malformed_or_partial_test_configuration_is_rejected(
    database_url: str,
    message: str,
) -> None:
    with pytest.raises(safety.DisposableDatabaseSafetyError, match=message):
        safety.require_disposable_database_configuration(
            _environment(database_url)
        )


def test_partial_application_identity_is_ambiguous() -> None:
    with pytest.raises(safety.DisposableDatabaseSafetyError, match="partial"):
        safety.require_disposable_database_configuration(
            _environment(POSTGRES_HOST="localhost")
        )


def test_native_or_production_server_identity_is_rejected_without_destructive_sql() -> None:
    configuration = safety.require_disposable_database_configuration(_environment())
    connection = _FakeConnection(
        server_rows=[
            (
                VALID_DATABASE,
                "sportsmodel_test",
                "172.17.0.2",
                5432,
                160015,
                False,
                PRODUCTION_SYSTEM_ID,
            )
        ],
        marker_rows=[(VALID_MARKER, VALID_INSTANCE, PRODUCTION_SYSTEM_ID)],
    )

    with pytest.raises(safety.DisposableDatabaseSafetyError, match="production PostgreSQL"):
        safety.verify_disposable_database_connection(connection, configuration)

    assert not any("DROP " in sql.upper() for sql in connection.statements)


@pytest.mark.parametrize(
    ("database", "user"),
    (("unexpected_database", "sportsmodel_test"), (VALID_DATABASE, "unexpected_user")),
)
def test_unexpected_connected_identity_is_rejected_without_destructive_sql(
    database: str,
    user: str,
) -> None:
    configuration = safety.require_disposable_database_configuration(_environment())
    connection = _FakeConnection(
        server_rows=[
            (
                database,
                user,
                "172.17.0.2",
                5432,
                160015,
                False,
                TEST_SYSTEM_ID,
            )
        ],
        marker_rows=[(VALID_MARKER, VALID_INSTANCE, TEST_SYSTEM_ID)],
    )

    with pytest.raises(safety.DisposableDatabaseSafetyError, match="identity mismatch"):
        safety.verify_disposable_database_connection(connection, configuration)

    assert not any("DROP " in sql.upper() for sql in connection.statements)


def test_missing_disposable_marker_is_rejected_without_destructive_sql() -> None:
    configuration = safety.require_disposable_database_configuration(_environment())
    connection = _matching_connection(marker_rows=[])

    with pytest.raises(safety.DisposableDatabaseSafetyError, match="one disposable"):
        safety.verify_disposable_database_connection(connection, configuration)

    assert not any("DROP " in sql.upper() for sql in connection.statements)


def test_ambiguous_disposable_marker_is_rejected_without_destructive_sql() -> None:
    configuration = safety.require_disposable_database_configuration(_environment())
    marker = (VALID_MARKER, VALID_INSTANCE, TEST_SYSTEM_ID)
    connection = _matching_connection(marker_rows=[marker, marker])

    with pytest.raises(safety.DisposableDatabaseSafetyError, match="one disposable"):
        safety.verify_disposable_database_connection(connection, configuration)

    assert not any("DROP " in sql.upper() for sql in connection.statements)


def test_exact_disposable_server_identity_is_accepted_and_logged(
    capsys,
    monkeypatch,
) -> None:
    environment = _environment()
    connection = _matching_connection()
    monkeypatch.setattr(safety.psycopg2, "connect", lambda url: connection)

    verified = safety.open_verified_disposable_database(environment)

    assert verified.connection is connection
    assert verified.identity.database == VALID_DATABASE
    assert verified.identity.instance_id == VALID_INSTANCE
    output = capsys.readouterr().out
    assert "port=55435" in output
    assert f"database={VALID_DATABASE}" in output
    assert f"container_id={VALID_INSTANCE}" in output
    assert VALID_MARKER not in output
    assert "marker_sha256=" in output


def test_destructive_fixture_rejects_5432_before_connect_or_drop(monkeypatch) -> None:
    environment = _environment(
        f"postgresql://sportsmodel_test:test@127.0.0.1:5432/{VALID_DATABASE}"
    )
    for name, value in environment.items():
        monkeypatch.setenv(name, value)
    calls: list[str] = []
    monkeypatch.setattr(safety.psycopg2, "connect", lambda url: calls.append(url))

    with pytest.raises(safety.DisposableDatabaseSafetyError, match="port 5432"):
        database_conftest.initialized_nfl_test_database.__wrapped__()

    assert calls == []


def test_configured_real_disposable_server_identity() -> None:
    if not os.getenv(safety.TEST_DATABASE_URL):
        pytest.skip("requires explicit disposable PostgreSQL configuration")
    verified = safety.open_verified_disposable_database()
    try:
        assert verified.configuration.port != 5432
        assert verified.identity.database.startswith("sportsmodel_test_")
        assert verified.identity.instance_id == verified.configuration.instance_id
    finally:
        verified.connection.rollback()
        verified.connection.close()


class _FakeCursor:
    def __init__(self, connection: "_FakeConnection") -> None:
        self.connection = connection
        self.rows: list[tuple[object, ...]] = []

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, *unused: object) -> None:
        pass

    def execute(self, sql: str) -> None:
        self.connection.statements.append(sql)
        if "pg_control_system" in sql:
            self.rows = self.connection.server_rows
        elif "sportsmodel_test_guard.instance_identity" in sql:
            self.rows = self.connection.marker_rows
        else:
            raise AssertionError(f"unexpected SQL: {sql}")

    def fetchall(self) -> list[tuple[object, ...]]:
        return self.rows


class _FakeConnection:
    def __init__(
        self,
        *,
        server_rows: list[tuple[object, ...]],
        marker_rows: list[tuple[object, ...]],
    ) -> None:
        self.server_rows = server_rows
        self.marker_rows = marker_rows
        self.statements: list[str] = []

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self)

    def close(self) -> None:
        pass


def _matching_connection(
    *,
    marker_rows: list[tuple[object, ...]] | None = None,
) -> _FakeConnection:
    return _FakeConnection(
        server_rows=[
            (
                VALID_DATABASE,
                "sportsmodel_test",
                "172.17.0.2",
                5432,
                160015,
                False,
                TEST_SYSTEM_ID,
            )
        ],
        marker_rows=(
            marker_rows
            if marker_rows is not None
            else [(VALID_MARKER, VALID_INSTANCE, TEST_SYSTEM_ID)]
        ),
    )
