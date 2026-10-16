"""Bounded market/audit adapter contracts without DB, providers or workflow execution."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from sportsmodel.database import repository, feature_data_audit as audit
from sportsmodel.database.mlb_canonical_time_repository import CertifiedReader, KnowledgeReceipt
from sportsmodel.database.mlb_retirement_guard import OperatorRefusal


CUTOFF = datetime(2026, 10, 9, tzinfo=timezone.utc)
START = CUTOFF - timedelta(days=1)
END = CUTOFF


def blocked(*args, **kwargs):
    raise AssertionError("Raw DB fallback is forbidden")


class FixtureReader(CertifiedReader):
    def rows(self, purpose, **params):
        self.calls.append((purpose, params))
        if self.refuse:
            raise OperatorRefusal("Synthetic missing/stale/unavailable receipt")
        return tuple(self.payloads)


def reader(payloads=(), refuse=False):
    value = FixtureReader(blocked, KnowledgeReceipt(8, "a" * 64, CUTOFF, "b" * 64,
        ("127.0.0.1", 55572, "synthetic")), CUTOFF)
    object.__setattr__(value, "payloads", payloads)
    object.__setattr__(value, "calls", [])
    object.__setattr__(value, "refuse", refuse)
    return value


def quote():
    return dict(odds_market_snapshot_id=9, effective_game_id=26, raw_acquisition_game_id=584,
        sportsbook_id=1, market_type="spreads", selection_name="Miami Marlins",
        line_value="-1.50000000000000000001", price=-110,
        snapshot_time=(CUTOFF-timedelta(hours=1)).isoformat(),
        created_at=(CUTOFF-timedelta(minutes=1)).isoformat(), observed_at=CUTOFF.isoformat())


@pytest.mark.parametrize("live", [False, True])
def test_certified_market_preserves_price_precision_times_and_raw_effective_identity(live, monkeypatch):
    monkeypatch.setattr(repository, "get_connection", blocked)
    value = reader([quote()])
    result = repository.get_market_snapshots(26, include_live=live, certified_reader=value)
    assert value.calls == [("markets", {"id": 26, "include_live": live})]
    assert len(result) == 1
    item = result[0]
    assert item.game_id == 26 and item.raw_acquisition_game_id == 584
    assert item.line_value == Decimal("-1.50000000000000000001")
    assert item.price == -110 and item.snapshot_time == CUTOFF-timedelta(hours=1)


@pytest.mark.parametrize("game,live", [(None, False), (True, False), (0, False), (-1, False), (26, 0)])
def test_certified_market_refuses_unbounded_or_malformed_requests_before_read(game, live):
    value = reader()
    with pytest.raises(OperatorRefusal):
        repository.get_market_snapshots(game, include_live=live, certified_reader=value)
    assert value.calls == []


def test_certified_empty_market_window_still_validates_receipt():
    value = reader(refuse=True)
    with pytest.raises(OperatorRefusal): repository.get_market_snapshots(26, certified_reader=value)
    assert value.calls == [("markets", {"id": 26, "include_live": False})]


@pytest.mark.parametrize("field", ["snapshot_time", "created_at", "observed_at"])
def test_later_quote_availability_is_not_reclassified_as_earlier_snapshot(field):
    row = quote()
    row[field] = (CUTOFF + timedelta(microseconds=1)).isoformat()
    with pytest.raises(OperatorRefusal, match="not available"):
        repository.get_market_snapshots(26, certified_reader=reader([row]))


@pytest.mark.parametrize("line", [1.5, 1, "NaN", "Infinity", "bogus"])
def test_certified_market_refuses_float_or_nonfinite_line(line):
    row = quote()
    row["line_value"] = line
    with pytest.raises(OperatorRefusal): repository.get_market_snapshots(26, certified_reader=reader([row]))


@pytest.mark.parametrize("field,value", [("effective_game_id", 27), ("price", -110.0), ("price", True)])
def test_certified_market_refuses_identity_or_price_substitution(field, value):
    row = quote()
    row[field] = value
    with pytest.raises(OperatorRefusal): repository.get_market_snapshots(26, certified_reader=reader([row]))


def test_certified_market_supports_null_line_and_null_observation():
    row = dict(quote(), line_value=None, observed_at=None)
    assert repository.get_market_snapshots(26, certified_reader=reader([row]))[0].line_value is None


@pytest.mark.parametrize("live", [False, True])
def test_legacy_market_path_preserves_existing_shared_queries_and_attribution(live, monkeypatch):
    class Cursor:
        calls = []
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def execute(self, sql, params=None): self.calls.append((sql, params))
        def fetchone(self):
            assert self.calls[-1][0] == "SELECT EXISTS(SELECT 1 FROM pg_catalog.pg_namespace WHERE nspname='mlb036_private')"
            return (False,)
        def fetchall(self): return [(9, 26, 1, "spreads", "Miami Marlins", Decimal("-1.5"), -110, START, 584)]
    class Connection:
        closed = False
        cursor_value = Cursor()
        def cursor(self): return self.cursor_value
        def close(self): self.closed = True
    connection = Connection()
    monkeypatch.setattr(repository, "get_connection", lambda: connection)
    result = repository.get_market_snapshots(26, include_live=live)
    sql, params = connection.cursor_value.calls[-1]
    assert "mlb_retirement_effective_markets()" in sql
    assert ("snapshot.snapshot_time < g.game_date" in sql) == (not live)
    assert "snapshot.effective_game_id = %s" in sql and params == [26]
    assert result[0].raw_acquisition_game_id == 584 and result[0].line_value == Decimal("-1.5")
    assert connection.cursor_value.calls[0] == ("SELECT EXISTS(SELECT 1 FROM pg_catalog.pg_namespace WHERE nspname='mlb036_private')", None)
    assert connection.closed


@pytest.mark.parametrize("kind", ["market", "results"])
@pytest.mark.parametrize("metadata", [(True,), None, (), (0,), [False], ("false",)])
def test_default_market_and_results_paths_refuse036_before_business_select(kind, metadata, monkeypatch):
    class Cursor:
        calls = []
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def execute(self, sql, params=None):
            assert sql == "SELECT EXISTS(SELECT 1 FROM pg_catalog.pg_namespace WHERE nspname='mlb036_private')"
            self.calls.append((sql, params))
        def fetchone(self): return metadata
    class Connection:
        closed = False
        value = Cursor()
        def cursor(self): return self.value
        def close(self): self.closed = True
    connection = Connection()
    monkeypatch.setattr(repository, "get_connection", lambda: connection)
    with pytest.raises(OperatorRefusal):
        repository.get_market_snapshots(26) if kind == "market" else repository.get_game_results()
    assert len(connection.value.calls) == 1 and connection.closed


def checks():
    return [dict(name=name, available=True, detail="Bounded synthetic evidence", row_count=1)
            for name in ("Historical game results", "Canonical game timestamps",
                         "Canonical team linkage", "Pregame market snapshots")]


def test_certified_partial_audit_does_not_claim_full_training_readiness(monkeypatch):
    monkeypatch.setattr(audit, "get_connection", blocked)
    value = reader(checks())
    report = audit.audit_feature_data(certified_reader=value, start=START, end=END)
    assert report.available_count == 4 and report.missing_count == 0
    assert not report.is_training_data_ready
    assert value.calls == [("feature_audit_summary", {"start": START.isoformat(), "end": END.isoformat()})]
    assert all("PARTIAL_SCOPED_AUDIT" in c.detail and "Not full training-data certification" in c.detail
               and "Receipt 8" in c.detail and CUTOFF.isoformat() in c.detail for c in report.checks)


@pytest.mark.parametrize("start,end", [(None, END), (START, None), (START.replace(tzinfo=None), END),
    (START, END.replace(tzinfo=None)), (END, START), (START, START), (START-timedelta(days=2), END)])
def test_certified_audit_refuses_unbounded_naive_or_invalid_windows_before_read(start, end):
    value = reader(checks())
    with pytest.raises(OperatorRefusal): audit.audit_feature_data(certified_reader=value, start=start, end=end)
    assert value.calls == []


def test_certified_audit_cannot_elide_receipt_guard_on_empty_input():
    value = reader(refuse=True)
    with pytest.raises(OperatorRefusal): audit.audit_feature_data(certified_reader=value, start=START, end=END)
    assert len(value.calls) == 1


@pytest.mark.parametrize("change", ["missing", "duplicate", "unknown", "availability", "count", "detail", "extra"])
def test_certified_audit_refuses_partial_or_malformed_summary_packet(change):
    rows = checks()
    if change == "missing": rows.pop()
    elif change == "duplicate": rows[1] = dict(rows[0])
    elif change == "unknown": rows[0]["name"] = "Unreviewed check"
    elif change == "availability": rows[0]["available"] = 1
    elif change == "count": rows[0]["row_count"] = -1
    elif change == "detail": rows[0]["detail"] = " "
    else: rows[0]["extra"] = True
    with pytest.raises(OperatorRefusal):
        audit.audit_feature_data(certified_reader=reader(rows), start=START, end=END)


def test_raw_audit_label_does_not_convert_forensic_availability_to_certification(monkeypatch):
    from sportsmodel.models.feature_data_audit import FeatureDataAuditCheck
    class Cursor:
        def __enter__(self): return self
        def __exit__(self, *args): pass
    class Connection:
        closed = False
        def cursor(self): return Cursor()
        def close(self): self.closed = True
    connection = Connection()
    monkeypatch.setattr(audit, "get_connection", lambda: connection)
    monkeypatch.setattr(audit, "_get_public_table_names", lambda c: set())
    names = [name for name in vars(audit) if name.startswith("_audit_") and name != "_audit_certified_feature_data"]
    for name in names:
        monkeypatch.setattr(audit, name, lambda **kwargs: FeatureDataAuditCheck("synthetic", True, "legacy evidence", 1))
    report = audit.audit_feature_data()
    assert len(report.checks) == 13 and report.available_count == 13 and connection.closed
    assert all(c.detail.startswith("RAW_FORENSIC / NOT_HISTORICALLY_CERTIFIED") for c in report.checks)


def test_scoped_audit_without_explicit_receipt_never_opens_raw_connection(monkeypatch):
    monkeypatch.setattr(audit, "get_connection", blocked)
    with pytest.raises(OperatorRefusal): audit.audit_feature_data(start=START, end=END)
