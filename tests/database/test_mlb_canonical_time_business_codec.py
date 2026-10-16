"""Independent offline036 business framing vectors; no PG/provider/config access."""
from copy import deepcopy
from datetime import date, datetime, timezone
from decimal import Decimal
from types import MappingProxyType

import pytest

from sportsmodel.database import mlb_canonical_time_codec as codec


FIELDS = frozenset(("identity", "history", "teams", "pitching", "markets", "legacy", "observations",
    "team_sources", "player_sources", "team_identities", "player_identities", "ingestion_runs",
    "sportsbooks", "book_sources", "canonical_corrections"))
DOMAIN = "SPORTSMODEL:MLB036:BUSINESS_STATE:v1"


def empty_snapshot():
    value = {key: [] for key in FIELDS}
    value["identity"] = {}
    return value


def digest(value):
    return codec.fingerprint(DOMAIN, codec.business_value(value))


def test_business_exact15_field_inventory_and_independent_empty_golden():
    assert codec.BUSINESS_FIELDS == FIELDS and len(FIELDS) == 15
    # Literal SHA independently derived from tag/uint64-length frames, not this codec.
    assert digest(empty_snapshot()) == "af784032e049a61e989b186e0d11aff1eec9f9e97d85e7fe45175e71d3ccd5e9"


def test_official_date_and_epoch_timestamp_independent_golden():
    value = empty_snapshot()
    value["history"] = [{"game_id": 26, "game_date": "1970-01-01", "created_at": "1970-01-01T00:00:00Z"}]
    projected = codec.business_value(value)
    assert projected["history"] == [{"game_id": 26, "official_date": "1970-01-01",
        "created_at": datetime(1970, 1, 1, tzinfo=timezone.utc)}]
    assert digest(value) == "b15dacb37466dbd8c8c215f9746d41044beaef7c61e239e582c175b27119b7e9"
    assert "game_date" in value["history"][0] and "official_date" not in value["history"][0]


def test_full_snapshot_projection_never_mutates_nested_original_or_retained_dates():
    value = empty_snapshot()
    value["history"] = [{"game_id": 26, "game_date": "2026-07-12", "created_at": "2026-07-13T00:00:00Z"}]
    value["identity"] = {"games": [{"game_id": 26, "game_date": "2026-07-12T17:40:00Z"}],
                          "sources": [], "candidates": []}
    value["markets"] = [{"line_value": "-1.50000000000000000001", "price": -110,
                          "snapshot_time": "2026-07-12T16:00:00Z", "observed_at": None}]
    value["team_sources"] = [{"external_team_id": "00146", "last_synced_at": "2026-07-12T00:00:00Z"}]
    original = deepcopy(value)
    projected = codec.business_value(value)
    assert value == original
    projected["history"][0]["official_date"] = "2026-07-11"
    projected["identity"]["games"][0]["game_id"] = 27
    projected["markets"][0]["price"] = 120
    assert value == original


def test_object_order_is_canonical_but_business_row_order_is_preserved():
    value = empty_snapshot()
    value["history"] = [{"game_id": 26, "game_date": "2026-07-12"},
                         {"game_id": 584, "game_date": "2026-07-12"}]
    reordered = {key: deepcopy(value[key]) for key in reversed(tuple(value))}
    reordered["history"] = [dict(reversed(tuple(row.items()))) for row in reordered["history"]]
    assert digest(value) == digest(reordered)
    reordered["history"].reverse()
    assert digest(value) != digest(reordered)


def test_string_bytes_no_unicode_or_numeric_text_normalization():
    value = empty_snapshot()
    value["markets"] = [{"line_value": "1.50000000000000000001", "selection_name": "e\u0301"}]
    projected = codec.business_value(value)
    assert projected["markets"][0]["line_value"] == "1.50000000000000000001"
    changed = deepcopy(value)
    changed["markets"][0]["line_value"] = "1.5"
    assert digest(value) != digest(changed)
    changed = deepcopy(value)
    changed["markets"][0]["selection_name"] = "é"
    assert digest(value) != digest(changed)


@pytest.mark.parametrize("field", sorted(codec.TIMESTAMP_FIELDS))
def test_all_retained_timestamp_names_have_exact_typed_framing(field):
    value = empty_snapshot()
    value["observations"] = [{field: "1970-01-01T01:00:00.000001+01:00"}]
    instant = codec.business_value(value)["observations"][0][field]
    assert codec.encode(instant).hex() == "0200000000000000080000000000000001"


@pytest.mark.parametrize("field", sorted(codec.TIMESTAMP_FIELDS))
def test_nullable_timestamp_fields_remain_null_not_epoch_or_observation_time(field):
    value = empty_snapshot()
    value["observations"] = [{field: None}]
    assert codec.business_value(value)["observations"][0][field] is None


@pytest.mark.parametrize("invalid", ["2026-07-12", "2026-07-12T17:40:00", "2026-07-12 17:40:00Z",
    "2026-07-12T24:00:00Z", "2026-07-12T17:40:60Z", "2026-02-30T17:40:00Z",
    "2026-07-12T17:40:00.1234567Z", "2026-07-12T17:40:00+24:00", "infinity",
    datetime(2026, 7, 12, tzinfo=timezone.utc), 1783878000])
def test_malformed_or_coerced_retained_timestamps_refuse(invalid):
    value = empty_snapshot()
    value["legacy"] = [{"snapshot_time": invalid}]
    original = deepcopy(value)
    with pytest.raises(codec.CodecRefusal): codec.business_value(value)
    assert value == original


@pytest.mark.parametrize("invalid", ["2026-02-30", "2026-7-12", "2026-07-12T00:00:00Z", "infinity",
                                     date(2026, 7, 12), 20260712])
def test_historical_date_cannot_be_reinterpreted_as_instant_or_coerced(invalid):
    value = empty_snapshot()
    value["history"] = [{"game_date": invalid}]
    with pytest.raises(codec.CodecRefusal): codec.business_value(value)


@pytest.mark.parametrize("field", ["officialDate", "official_date", "active_from", "active_through"])
def test_other_retained_date_fields_are_validated_without_timestamp_conversion(field):
    value = empty_snapshot()
    value["player_sources"] = [{field: "2024-02-29"}]
    assert codec.business_value(value)["player_sources"][0][field] == "2024-02-29"
    value["player_sources"][0][field] = "2025-02-29"
    with pytest.raises(codec.CodecRefusal): codec.business_value(value)


@pytest.mark.parametrize("number", [1.5, float("inf"), float("nan"), Decimal("1.5"), 2**63, -(2**63)-1])
def test_float_or_unsupported_numeric_values_never_enter_business_hash(number):
    value = empty_snapshot()
    value["markets"] = [{"line_value": number}]
    with pytest.raises(codec.CodecRefusal): codec.business_value(value)


def test_null_and_boolean_metrics_remain_distinct_from_numeric_or_absent_values():
    value = empty_snapshot()
    value["pitching"] = [{"is_starter": False, "decision": None, "pitching_outs": 0}]
    projected = codec.business_value(value)
    assert projected["pitching"] == value["pitching"]
    assert codec.encode(False) != codec.encode(0) != codec.encode(None)
    changed = deepcopy(value)
    del changed["pitching"][0]["decision"]
    assert digest(value) != digest(changed)


@pytest.mark.parametrize("change", ["missing", "unknown", "replacement", "notdict", "subclass"])
def test_business_snapshot_rejects_any_top_level_schema_drift(change):
    value = empty_snapshot()
    if change == "missing": value.pop("book_sources")
    elif change == "unknown": value["unreviewed_relation"] = []
    elif change == "replacement": value["unknown"] = value.pop("sportsbooks")
    elif change == "notdict": value = MappingProxyType(value)
    else:
        class DictSubclass(dict): pass
        value = DictSubclass(value)
    with pytest.raises(codec.CodecRefusal): codec.business_value(value)


@pytest.mark.parametrize("history", [None, {}, (), "[]", [None], [[]], [{"game_id": 26}],
    [{"game_date": "2026-07-12", "official_date": "2026-07-12"}]])
def test_history_date_projection_requires_exact_list_rows_and_no_name_collision(history):
    value = empty_snapshot()
    value["history"] = history
    with pytest.raises(codec.CodecRefusal): codec.business_value(value)


def test_depth_cardinality_utf8_and_aggregate_body_limits_remain_fail_closed(monkeypatch):
    value = empty_snapshot()
    nested = 0
    for _ in range(33): nested = [nested]
    value["identity"] = {"nested": nested}
    with pytest.raises(codec.CodecRefusal, match="Depth"): codec.business_value(value)
    value = empty_snapshot()
    value["markets"] = [0] * 100001
    with pytest.raises(codec.CodecRefusal, match="Cardinality"): codec.business_value(value)
    value = empty_snapshot()
    value["sportsbooks"] = [{"name": "\ud800"}]
    with pytest.raises(codec.CodecRefusal, match="UTF8"): codec.business_value(value)
    monkeypatch.setattr(codec, "MAX_BODY", 96)
    with pytest.raises(codec.CodecRefusal, match="Body"): digest(empty_snapshot())
