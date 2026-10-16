"""Unsupported legacy market writer admission, entirely offline."""
import pytest
from contextlib import contextmanager
from datetime import datetime, timezone
from sportsmodel.analysis import market
from sportsmodel.database.mlb_retirement_guard import OperatorRefusal

PROBE = "SELECT EXISTS(SELECT 1 FROM pg_catalog.pg_namespace WHERE nspname='mlb036_private')"


class Connection:
    def __init__(self, metadata, rows=()):
        self.metadata = metadata
        self.rows = rows
        self.calls, self.writes = [], []
        self.commits, self.rollbacks = 0, 0
        self.closed = False
    def __enter__(self): return self
    def __exit__(self, kind, *args):
        if kind is None: self.commits += 1
        else: self.rollbacks += 1
    @contextmanager
    def cursor(self): yield self
    def execute(self, query, params=None): self.calls.append((query, params))
    def fetchone(self):
        assert self.calls[-1] == (PROBE, None)
        return self.metadata
    def fetchall(self):
        assert "mlb_retirement_effective_markets()" in self.calls[-1][0]
        return self.rows
    def executemany(self, query, rows): self.writes.append((query, rows))
    def close(self): self.closed = True


@pytest.mark.parametrize("metadata", [(True,), None, (), (0,), [False], ("false",)])
def test_market_analysis_refuses036_before_market_read_or_write(metadata, monkeypatch):
    connection = Connection(metadata)
    monkeypatch.setattr(market, "get_connection", lambda: connection)
    with pytest.raises(OperatorRefusal): market.analyze_markets()
    assert connection.calls == [(PROBE, None)] and connection.writes == []
    assert connection.commits == 0 and connection.rollbacks == 1 and connection.closed


def test_legacy_false_probe_retains_empty_analysis_behavior(monkeypatch, capsys):
    connection = Connection((False,))
    monkeypatch.setattr(market, "get_connection", lambda: connection)
    market.analyze_markets()
    assert connection.calls[0] == (PROBE, None)
    assert len(connection.calls) == 2 and len(connection.writes) == 1
    assert connection.writes[0][1] == []
    assert connection.commits == 1 and connection.rollbacks == 0 and connection.closed
    assert "Market analysis rows processed: 0" in capsys.readouterr().out


def test_legacy_false_probe_retains_loaded_price_analysis_and_attribution(monkeypatch):
    from decimal import Decimal
    stamp = datetime(2026, 7, 12, 16, tzinfo=timezone.utc)
    rows = [(1, 26, 10, "h2h", "Miami Marlins", None, -110, stamp),
            (2, 26, 10, "h2h", "Cleveland Guardians", None, 100, stamp)]
    connection = Connection((False,), rows)
    monkeypatch.setattr(market, "get_connection", lambda: connection)
    market.analyze_markets()
    written = connection.writes[0][1]
    assert [row[0] for row in written] == [1, 2]
    assert written[0][1] == Decimal(110) / Decimal(210)
    assert written[1][1] == Decimal("0.5")
    assert [row[3:6] for row in written] == [(Decimal(-110), -110, 1), (Decimal(100), 100, 1)]
    assert connection.commits == 1 and connection.rollbacks == 0
