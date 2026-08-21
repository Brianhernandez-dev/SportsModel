from uuid import UUID

from psycopg2.extensions import adapt

from sportsmodel.database import connection


def test_loads_explicit_environment_file(
    monkeypatch,
) -> None:
    calls = []

    monkeypatch.setenv(
        "SPORTSMODEL_ENV_FILE",
        r"D:\SportsModel\.env",
    )

    monkeypatch.setattr(
        connection,
        "load_dotenv",
        lambda *args, **kwargs: calls.append(
            (args, kwargs)
        ),
    )

    connection.load_database_environment()

    assert calls == [
        (
            (r"D:\SportsModel\.env",),
            {"override": True},
        )
    ]


def test_loads_default_environment_file(
    monkeypatch,
) -> None:
    calls = []

    monkeypatch.delenv(
        "SPORTSMODEL_ENV_FILE",
        raising=False,
    )

    monkeypatch.setattr(
        connection,
        "load_dotenv",
        lambda *args, **kwargs: calls.append(
            (args, kwargs)
        ),
    )

    connection.load_database_environment()

    assert calls == [
        ((), {})
    ]


def test_shared_database_bootstrap_registers_uuid_adaptation() -> None:
    identifier = UUID("b8eebca7-44f1-4e64-a821-01876b4db323")

    assert adapt(identifier).getquoted() == (
        b"'b8eebca7-44f1-4e64-a821-01876b4db323'::uuid"
    )
