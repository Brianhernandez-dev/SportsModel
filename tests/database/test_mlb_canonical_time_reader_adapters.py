"""Offline036 adapter contracts; actual PostgreSQL enforcement is a separate gate."""
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone

import pytest

from sportsmodel.database import mlb_completeness_repository as completeness
from sportsmodel.database.mlb_canonical_time_repository import CertifiedReader, KnowledgeReceipt
from sportsmodel.database.mlb_retirement_guard import OperatorRefusal
from sportsmodel.operations import mlb_history_check as history


CUTOFF = datetime(2026, 10, 9, tzinfo=timezone.utc)


def forbidden(*args, **kwargs):
    raise AssertionError("Raw connection/provider fallback is forbidden")


class FixtureReader(CertifiedReader):
    def rows(self, purpose, **params):
        self.calls.append((purpose, params))
        if purpose in self.refuse:
            raise OperatorRefusal("Synthetic unavailable receipt")
        value = self.payloads.get(purpose, ())
        return tuple(value(params) if callable(value) else value)


def reader(payloads=None, refuse=()):
    value = FixtureReader(forbidden, KnowledgeReceipt(7, "a" * 64, CUTOFF, "b" * 64,
                                                     ("127.0.0.1", 55572, "synthetic")), CUTOFF)
    object.__setattr__(value, "payloads", payloads or {})
    object.__setattr__(value, "calls", [])
    object.__setattr__(value, "refuse", set(refuse))
    return value


def snapshot(game_pk=700, game_id=7):
    created = CUTOFF - timedelta(days=1)
    teams = tuple(completeness.TeamStatisticsRecord(team_id=team, is_home=home, runs=runs,
        pitching_outs=27, runs_allowed=allowed, earned_runs_allowed=allowed,
        hits_allowed=5, home_runs_allowed=0, walks_allowed=1, strikeouts_recorded=6,
        created_at=created) for team, home, runs, allowed in ((1, True, 3, 1), (2, False, 1, 3)))
    pitchers = tuple(completeness.PitchingStatisticsRecord(team_id=team, appearance_order=1,
        is_starter=True, pitching_outs=27, hits_allowed=5, runs_allowed=allowed,
        earned_runs_allowed=allowed, home_runs_allowed=0, walks_allowed=1,
        strikeouts=6, created_at=created) for team, allowed in ((1, 1), (2, 3)))
    return completeness.MlbGameCompletenessSnapshot(game_pk, (game_id,), 1, 2, (str(game_pk),),
        (completeness.HistoricalResultRecord(game_id, game_pk, 3, 1),), teams, pitchers)


def packet(value):
    result = asdict(value)
    for kind in ("team_statistics", "pitching_statistics"):
        for row in result[kind]:
            row["created_at"] = row["created_at"].isoformat()
    return result


def test_certified_completeness_translates_exact_dataclass_payload():
    expected = snapshot()
    value = reader({"completeness": [packet(expected)]})
    assert completeness._load_completeness_snapshots((700,), connection_factory=value) == (expected,)
    assert value.calls == [("completeness", {"ids": [700]})]
    completeness.assert_mlb_games_complete((700,), connection_factory=value, as_of=CUTOFF)


@pytest.mark.parametrize("returned", [[], [packet(snapshot(701))], [packet(snapshot()), packet(snapshot())]])
def test_completeness_does_not_filter_missing_wrong_or_duplicate_requested_evidence(returned):
    value = reader({"completeness": returned})
    with pytest.raises(completeness.MlbCompletenessError):
        completeness._load_completeness_snapshots((700,), connection_factory=value)


@pytest.mark.parametrize("cutoff", [None, CUTOFF + timedelta(seconds=1), CUTOFF - timedelta(seconds=1)])
def test_completeness_requires_same_original_cutoff_before_any_read(cutoff):
    value = reader()
    with pytest.raises(completeness.MlbCompletenessError):
        completeness.assert_mlb_games_complete((700,), connection_factory=value, as_of=cutoff)
    assert value.calls == []


@pytest.mark.parametrize("operation", ["games", "features", "required", "nonplayed", "slate"])
def test_empty_certified_windows_cannot_elide_receipt_guard(operation):
    value = reader(refuse=("completeness", "required_game_pks", "nonplayed_identity", "slate"))
    with pytest.raises(OperatorRefusal):
        if operation == "games":
            completeness.assert_mlb_games_complete((), connection_factory=value, as_of=CUTOFF)
        elif operation == "features":
            completeness.assert_mlb_feature_history_complete(target_game_pks=(), cutoff_time=CUTOFF,
                                                             connection_factory=value)
        elif operation == "required":
            completeness._load_required_feature_game_pks(team_ids=(), cutoff_time=CUTOFF,
                                                         connection_factory=value)
        elif operation == "nonplayed":
            completeness.validate_mlb_non_played_games((), connection_factory=value)
        else:
            completeness.load_mlb_game_pks_for_pacific_date(date(2026, 10, 10), connection_factory=value)
    assert len(value.calls) == 1


def test_certified_pacific_slate_uses_exact_half_open_interval_and_source_gateway():
    value = reader({"slate": [{"game_id": 7}], "game_sources": [{"game_id": 7, "external_game_id": "700"}]})
    assert completeness.load_mlb_game_pks_for_pacific_date(date(2026, 10, 10), connection_factory=value) == (700,)
    assert value.calls == [("slate", {"start": "2026-10-10T07:00:00+00:00", "end": "2026-10-11T07:00:00+00:00"}),
                           ("game_sources", {"ids": [7]})]


@pytest.mark.parametrize("source", [None, "bad", "0", "７００", 700])
def test_required_history_refuses_invalid_source_ids(source):
    value = reader({"required_game_pks": [{"external_game_id": source}]})
    with pytest.raises(completeness.MlbCompletenessError):
        completeness._load_required_feature_game_pks(team_ids=(1,), starting_pitcher_ids=(10,),
                                                     cutoff_time=CUTOFF, connection_factory=value)


@pytest.mark.parametrize("conflict", ["played", "duplicate", "source_count", "orientation"])
def test_nonplayed_certified_path_preserves_conflict_refusals(conflict):
    row = dict(external_game_id="700", game_id=7, home_team_name="Miami Marlins",
               away_team_name="Cleveland Guardians", played_history=False, source_count=1)
    rows = [row]
    if conflict == "played": row["played_history"] = True
    elif conflict == "duplicate": rows.append(dict(row))
    elif conflict == "source_count": row["source_count"] = 2
    else: row["away_team_name"] = "Miami Marlins"
    value = reader({"nonplayed_identity": rows})
    game = completeness.NonPlayedMlbGame(700, "Miami Marlins", "Cleveland Indians", "Cancelled")
    with pytest.raises(completeness.MlbCompletenessError):
        completeness.validate_mlb_non_played_games((game,), connection_factory=value)


def h1_reader(state="complete"):
    team = dict(team_id=1, game_id=7, game_date=(CUTOFF-timedelta(days=1)).isoformat(),
                home_team_id=1, away_team_id=2, rank=1)
    starter = dict(baseball_player_id=10, game_id=7, game_date=team["game_date"],
                   team_id=1, home_team_id=1, away_team_id=2, created_at=team["game_date"], rank=1)
    payloads = {
        "slate": [dict(game_id=99, game_date="2026-10-10T19:00:00+00:00", home_team_id=1, away_team_id=2)],
        "mlb_teams": [dict(team_id=1, name="Miami Marlins", mlb_team_id=146, source_row_id=1),
                      dict(team_id=2, name="Cleveland Guardians", mlb_team_id=114, source_row_id=2)],
        "mlb_starters": [dict(baseball_player_id=10, external_player_id="100"),
                         dict(baseball_player_id=20, external_player_id="200")],
        "h1_team": [team], "h1_starter": [starter],
        "game_sources": [dict(game_id=99, external_game_id="999"), dict(game_id=7, external_game_id="700")],
        "required_game_pks": [dict(external_game_id="700")], "completeness": [packet(snapshot())]}
    if state == "invisible": payloads["game_sources"] = payloads["game_sources"][:1]
    elif state == "ambiguous": payloads["game_sources"].append(dict(game_id=7, external_game_id="701"))
    elif state == "incomplete": payloads["completeness"][0]["results"] = []
    return reader(payloads)


def run_h1(value, **kwargs):
    return history.check_feature_history(target_date=date(2026, 10, 10), target_game_ids=(99,),
        starting_pitcher_ids=(10, 20), cutoff_time=CUTOFF, target=None,
        connection_factory=value, **kwargs)


@pytest.mark.parametrize("state", ["invisible", "ambiguous", "incomplete"])
def test_certified_h1_retains_independent_windows_and_reports_failures(state):
    report = run_h1(h1_reader(state))
    assert report["status"] == "FAIL"
    assert report["required_canonical_game_ids"] == [7]
    if state != "incomplete":
        assert report["games_missing_mlb_stats_identity"] == [7]
        assert report["team_history_games_missing_mlb_stats_identity"] == [7]
        assert report["starter_history_games_missing_mlb_stats_identity"] == [7]
    else:
        assert report["games_missing_required_feature_history"]


def test_certified_h1_requires_full_target_completeness_during_final_check():
    value = h1_reader()
    with pytest.raises(completeness.MlbCompletenessError, match="differs from requested"):
        run_h1(value)
    assert ("completeness", {"ids": [999]}) in value.calls


def test_certified_h1_complete_path_retains_original_receipt_and_cutoff():
    value = h1_reader()
    value.payloads["completeness"] = lambda params: [packet(snapshot(pk, 99 if pk == 999 else 7)) for pk in params["ids"]]
    report = run_h1(value)
    assert report["status"] == "PASS"
    assert report["guard"]["receipt_id"] == value.receipt.receipt_id
    assert report["cutoff_time"] == CUTOFF.isoformat()
    assert report["visible_required_game_pks"] == [700]
    assert not callable(value)


@pytest.mark.parametrize("rank", [49, 50])
def test_valid_canonical_starter_window_boundary_is_accepted(rank):
    value = h1_reader()
    row = value.payloads["h1_starter"][0]
    row["rank"] = rank
    history._validate_certified_windows((), (row,), (1, 2), (10, 20), CUTOFF)


@pytest.mark.parametrize("mutate", ["v2", "cutoff", "slate", "starter", "team"])
def test_certified_h1_refuses_v2_cutoff_and_identity_substitution(mutate):
    value = h1_reader()
    kwargs = {}
    if mutate == "v2": kwargs["identity_knowledge"] = object()
    elif mutate == "cutoff": object.__setattr__(value, "cutoff_time", CUTOFF + timedelta(seconds=1))
    elif mutate == "slate": value.payloads["slate"][0]["game_id"] = 98
    elif mutate == "starter": value.payloads["mlb_starters"].append(dict(baseball_player_id=10, external_player_id="101"))
    else: value.payloads["mlb_teams"][0]["name"] = "Boston Red Sox"
    with pytest.raises(OperatorRefusal): run_h1(value, **kwargs)
    if mutate in ("v2", "cutoff"): assert value.calls == []


@pytest.mark.parametrize("mutate", ["game_date", "created_at", "rank", "team", "duplicate"])
def test_certified_h1_revalidates_starter_pit_orientation_and_window(mutate):
    value = h1_reader("incomplete")
    row = value.payloads["h1_starter"][0]
    if mutate == "game_date": row["game_date"] = CUTOFF.isoformat()
    elif mutate == "created_at": row["created_at"] = (CUTOFF + timedelta(seconds=1)).isoformat()
    elif mutate == "rank": row["rank"] = 51
    elif mutate == "team": row["team_id"] = 3
    else: value.payloads["h1_starter"].append(dict(row))
    with pytest.raises(OperatorRefusal): run_h1(value)


SCHEMA036_PROBE = "SELECT EXISTS(SELECT 1 FROM pg_catalog.pg_namespace WHERE nspname='mlb036_private')"


def adapter_call(kind, factory, cutoff=CUTOFF):
    from sportsmodel.database.game_repository import PostgresGameRepository
    from sportsmodel.database.team_statistics_repository import PostgresTeamStatisticsRepository
    from sportsmodel.database.pitcher_statistics_repository import PostgresPitcherStatisticsRepository
    from sportsmodel.database.bullpen_statistics_repository import PostgresBullpenStatisticsRepository
    from sportsmodel.database.scheduled_execution_repository import get_earliest_mlb_game_start_for_pacific_date
    if kind == "game": return PostgresGameRepository(connection_factory=factory).get_by_id(game_id=26)
    if kind == "next": return PostgresGameRepository(connection_factory=factory).get_next_upcoming_game(cutoff_time=cutoff)
    if kind == "team": return PostgresTeamStatisticsRepository(connection_factory=factory).get_completed_games_before(team_id=1, cutoff_time=cutoff, limit=200)
    if kind == "starter": return PostgresPitcherStatisticsRepository(connection_factory=factory).get_completed_starts_before(player_id=10, cutoff_time=cutoff, limit=50)
    if kind == "bullpen": return PostgresBullpenStatisticsRepository(connection_factory=factory).get_completed_relief_appearances_before(team_id=1, cutoff_time=cutoff)
    return get_earliest_mlb_game_start_for_pacific_date(date(2026, 10, 10), connection_factory=factory)


@pytest.mark.parametrize("kind", ["game", "next", "team", "starter", "bullpen", "schedule"])
@pytest.mark.parametrize("metadata", [(True,), None, (), ("false",), (0,), [False], (False, False)])
def test_raw_adapter_refuses036_or_malformed_namespace_probe_before_any_time_read(kind, metadata):
    class Cursor:
        calls = []
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def execute(self, sql, params=None):
            self.calls.append((sql, params))
            assert sql == SCHEMA036_PROBE, "Time-bearing query occurred before certified admission"
        def fetchone(self): return metadata
    class Connection:
        closed = False
        value = Cursor()
        def cursor(self): return self.value
        def close(self): self.closed = True
    connection = Connection()
    with pytest.raises(OperatorRefusal): adapter_call(kind, lambda: connection)
    assert connection.value.calls == [(SCHEMA036_PROBE, None)]
    assert connection.closed


@pytest.mark.parametrize("kind,purpose,params", [
    ("game", "game", {"id": 26}), ("next", "next_game", {}),
    ("team", "team_stats", {"id": 1, "limit": 200}),
    ("starter", "starter_stats", {"id": 10, "limit": 50}),
    ("bullpen", "bullpen_stats", {"id": 1}),
    ("schedule", "earliest_start", {"start": "2026-10-10T07:00:00+00:00", "end": "2026-10-11T07:00:00+00:00"})])
def test_all036_adapter_empty_branches_use_typed_receipt_gateway(kind, purpose, params):
    value = reader()
    result = adapter_call(kind, value)
    assert result == (() if kind in ("team", "starter", "bullpen") else None)
    assert value.calls == [(purpose, params)]
    value = reader(refuse=(purpose,))
    with pytest.raises(OperatorRefusal): adapter_call(kind, value)
    assert value.calls == [(purpose, params)]


@pytest.mark.parametrize("kind", ["next", "team", "starter", "bullpen"])
def test036_repository_adapter_refuses_cutoff_change_without_read(kind):
    value = reader()
    with pytest.raises(ValueError, match="cutoff differs"):
        adapter_call(kind, value, CUTOFF + timedelta(seconds=1))
    assert value.calls == []


def completeness_raw_call(kind, factory):
    if kind == "slate":
        return completeness.load_mlb_game_pks_for_pacific_date(date(2026, 10, 10), connection_factory=factory)
    if kind == "nonplayed":
        game = completeness.NonPlayedMlbGame(700, "Miami Marlins", "Cleveland Guardians", "Cancelled")
        return completeness.validate_mlb_non_played_games((game,), connection_factory=factory)
    if kind == "snapshots":
        return completeness._load_completeness_snapshots((700,), connection_factory=factory)
    return completeness._load_required_feature_game_pks(team_ids=(1,), starting_pitcher_ids=(10,),
        cutoff_time=CUTOFF, connection_factory=factory)


@pytest.mark.parametrize("kind", ["slate", "nonplayed", "snapshots", "required"])
@pytest.mark.parametrize("metadata", [(True,), None, (), ("false",), (0,), [False], (False, False)])
def test_completeness_raw_paths_refuse036_or_malformed_probe_before_business_data(kind, metadata):
    class Cursor:
        calls = []
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def execute(self, sql, params=None):
            self.calls.append((sql, params))
            assert sql == SCHEMA036_PROBE, "Raw completeness data accessed before admission"
        def fetchone(self): return metadata
    class Connection:
        closed = False
        value = Cursor()
        def cursor(self): return self.value
        def close(self): self.closed = True
    connection = Connection()
    with pytest.raises(OperatorRefusal): completeness_raw_call(kind, lambda: connection)
    assert connection.value.calls == [(SCHEMA036_PROBE, None)]
    assert connection.closed


@pytest.mark.parametrize("kind", ["slate", "nonplayed", "snapshots", "required"])
def test_completeness_legacy_false_probe_preserves_empty_business_evidence(kind):
    class Cursor:
        calls = []
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def execute(self, sql, params=None): self.calls.append((sql, params))
        def fetchone(self):
            assert self.calls[-1] == (SCHEMA036_PROBE, None)
            return (False,)
        def fetchall(self): return []
    class Connection:
        closed = False
        value = Cursor()
        def cursor(self): return self.value
        def close(self): self.closed = True
    connection = Connection()
    result = completeness_raw_call(kind, lambda: connection)
    assert connection.value.calls[0] == (SCHEMA036_PROBE, None)
    assert len(connection.value.calls) == 2 and connection.closed
    if kind == "snapshots":
        assert result[0].game_pk == 700 and result[0].mapping_game_ids == ()
    else:
        assert result == ()


@pytest.mark.parametrize("kind", ["games", "features", "nonplayed", "required"])
def test_generic_empty_legacy_helpers_preserve_no_data_not_certification_contract(kind):
    if kind == "games":
        result = completeness.assert_mlb_games_complete((), as_of=CUTOFF, connection_factory=forbidden)
    elif kind == "features":
        result = completeness.assert_mlb_feature_history_complete(target_game_pks=(), cutoff_time=CUTOFF,
            connection_factory=forbidden)
    elif kind == "nonplayed":
        result = completeness.validate_mlb_non_played_games((), connection_factory=forbidden)
    else:
        result = completeness._load_required_feature_game_pks(team_ids=(), cutoff_time=CUTOFF,
            connection_factory=forbidden)
    assert result is None if kind in ("games", "features") else result == ()
