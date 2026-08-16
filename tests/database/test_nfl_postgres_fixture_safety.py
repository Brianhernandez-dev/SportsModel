import pytest

from tests.database import conftest as database_conftest


def test_missing_destructive_acknowledgement_prevents_connection(monkeypatch):
    monkeypatch.setenv(
        "SPORTSMODEL_TEST_DATABASE_URL", "postgresql://test/disposable"
    )
    monkeypatch.delenv("SPORTSMODEL_ALLOW_DESTRUCTIVE_TEST_DB", raising=False)
    calls = []
    monkeypatch.setattr(
        database_conftest.psycopg2,
        "connect",
        lambda url: calls.append(url),
    )

    with pytest.raises(pytest.skip.Exception, match="ALLOW_DESTRUCTIVE_TEST_DB=1"):
        database_conftest.initialized_nfl_test_database.__wrapped__()

    assert calls == []


def test_application_database_url_equality_prevents_connection(monkeypatch):
    shared_url = "postgresql://application/shared"
    monkeypatch.setenv("SPORTSMODEL_TEST_DATABASE_URL", shared_url)
    monkeypatch.setenv("SPORTSMODEL_ALLOW_DESTRUCTIVE_TEST_DB", "1")
    monkeypatch.setenv("DATABASE_URL", shared_url)
    calls = []
    monkeypatch.setattr(
        database_conftest.psycopg2,
        "connect",
        lambda url: calls.append(url),
    )

    with pytest.raises(pytest.skip.Exception, match="must differ"):
        database_conftest.initialized_nfl_test_database.__wrapped__()

    assert calls == []


def test_distinct_acknowledged_disposable_url_passes_preflight(monkeypatch):
    disposable_url = "postgresql://test/disposable"
    monkeypatch.setenv("SPORTSMODEL_TEST_DATABASE_URL", disposable_url)
    monkeypatch.setenv("SPORTSMODEL_ALLOW_DESTRUCTIVE_TEST_DB", "1")
    monkeypatch.setenv("DATABASE_URL", "postgresql://application/primary")

    assert (
        database_conftest._require_destructive_test_database_configuration()
        == disposable_url
    )
