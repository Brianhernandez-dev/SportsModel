from copy import deepcopy
from datetime import date, datetime, timezone
import json
from pathlib import Path
from shutil import copyfile

import pytest

from sportsmodel.ingest import mlb_recovery as recovery
from sportsmodel.database import mlb_recovery_repository as repository


FIXTURE = Path(__file__).parents[1] / 'fixtures/mlb_recovery/synthetic.json'
REVISION = 'a' * 40


def bundle():
    return json.loads(FIXTURE.read_text())


def spec():
    return recovery.RecoverySpecification(date(2025, 8, 1), (800,), REVISION)


def snapshot():
    return dict(games={'800': dict(game_id=1, source_id=1,
                                  start='2025-08-01T19:00:00+00:00', home_team_id=1,
                                  away_team_id=2, mlb_game_id=None, odds_api_event_id=None,
                                  sources=[[1, 'mlb_stats', '800']])},
                teams={'10': 1, '20': 2}, players={'100': None, '200': None})


class ReadOnlyCursor:
    def __init__(self, mapping_count=1, dangling=False):
        self.mapping_count, self.dangling = mapping_count, dangling
        self.queries, self.rows = [], []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def execute(self, sql, parameters=()):
        assert sql.strip().startswith('SELECT'), 'Preview attempted a write'
        self.queries.append(sql)
        if 'LIMIT 0' in sql:
            self.rows = []
        elif 'SELECT game_source_id, game_id' in sql:
            self.rows = [(1, 1)] * self.mapping_count
        elif 'SELECT game_date' in sql:
            self.rows = [] if self.dangling else [(datetime(2025, 8, 1, 19, tzinfo=timezone.utc), 1, 2, None, None)]
        elif 'SELECT game_source_id,source_name' in sql:
            self.rows = [(1, 'mlb_stats', '800')]
        elif 'baseball_team_sources' in sql:
            self.rows = [(1 if parameters[0] == '10' else 2,)]
        elif 'baseball_player_sources' in sql:
            self.rows = []
        else:
            raise AssertionError(sql)

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.rows[0] if self.rows else None


class ReadOnlyConnection:
    def __init__(self):
        self.reader = ReadOnlyCursor()
        self.settings = None

    def set_session(self, **kwargs):
        self.settings = kwargs

    def cursor(self):
        return self.reader

    def close(self):
        pass


def test_preview_no_writes_and_complete_manifest():
    connection = ReadOnlyConnection()
    manifest = recovery.plan_recovery(spec(), bundle(), connection_factory=lambda: connection)
    assert connection.settings['readonly'] is True
    assert manifest['eligible_game_pks'] == [800]
    assert manifest['missing_player_ids'] == [100, 200]
    assert len(manifest['games'][0]['boxscore']['team_statistics']) == 2
    assert manifest['games'][0]['starters'] == [200, 100]
    assert all('baseball_player_id' not in p for p in manifest['games'][0]['boxscore']['pitcher_statistics'])


@pytest.mark.parametrize('count,dangling', [(0, False), (2, False), (1, True)])
def test_existing_resolver_failures(count, dangling):
    cursor = ReadOnlyCursor(count, dangling)
    with pytest.raises(ValueError):
        repository.resolve_existing_mlb_game(cursor, 800, home_team_id=1, away_team_id=2)


def test_existing_resolver_orientation_and_no_source_parameter():
    with pytest.raises(ValueError):
        repository.resolve_existing_mlb_game(ReadOnlyCursor(), 800, home_team_id=2, away_team_id=1)
    with pytest.raises(TypeError):
        repository.resolve_existing_mlb_game(ReadOnlyCursor(), 800, source_name='odds_api', home_team_id=1, away_team_id=2)


@pytest.mark.parametrize('pks', [(), (800, 800), (0,), (-1,), (True,), ('800',)])
def test_invalid_allowlists(pks):
    with pytest.raises(ValueError):
        recovery.RecoverySpecification(date(2025, 8, 1), pks, REVISION)


@pytest.mark.parametrize('field,value', [('format_version', 2), ('format_version', True),
                                       ('eligibility_contract', 'skip-anything'),
                                       ('schedule_date', '2025-08-01'), ('code_revision', 'main')])
def test_invalid_specification(field, value):
    args = dict(schedule_date=date(2025, 8, 1), game_pks=(800,), code_revision=REVISION)
    args[field] = value
    with pytest.raises(ValueError):
        recovery.RecoverySpecification(**args)


@pytest.mark.parametrize('change', ['missing', 'outside', 'duplicate', 'feed_id', 'box_id',
                                   'orientation', 'feed_date', 'schedule_date', 'unknown',
                                   'scores', 'pitcher_totals', 'people', 'canonical_date'])
def test_invalid_payloads_fail_before_connection_or_write(change):
    payload, snap = bundle(), snapshot()
    event = payload['schedule']['dates'][0]['games'][0]
    pinned = payload['games']['800']
    if change == 'missing':
        payload['schedule']['dates'][0]['games'] = []
    elif change in ('outside', 'duplicate'):
        other = deepcopy(event)
        if change == 'outside':
            other['gamePk'] = 801
        payload['schedule']['dates'][0]['games'].append(other)
    elif change == 'feed_id':
        pinned['feed']['gamePk'] = 801
    elif change == 'box_id':
        pinned['boxscore']['gamePk'] = 801
    elif change == 'orientation':
        snap['games']['800']['home_team_id'] = 2
    elif change == 'feed_date':
        pinned['feed']['gameData']['datetime']['officialDate'] = '2025-08-02'
    elif change == 'schedule_date':
        payload['schedule']['dates'][0]['date'] = '2025-08-02'
    elif change == 'unknown':
        event['status'] = {'abstractGameState': 'Unknown'}
    elif change == 'scores':
        event['teams']['home']['score'] = 6
    elif change == 'pitcher_totals':
        for box in (pinned['boxscore'], pinned['feed']['liveData']['boxscore']):
            box['teams']['home']['players']['ID100']['stats']['pitching']['outs'] = 26
    elif change == 'people':
        payload['people'].pop()
    else:
        snap['games']['800']['start'] = '2025-08-02T19:00:00+00:00'
    with pytest.raises((ValueError, KeyError)):
        recovery.build_manifest(spec(), payload, snap)


@pytest.mark.parametrize('status,game_type,reason', [
    ({'abstractGameState': 'Preview'}, 'R', 'excluded-nonfinal'),
    ({'abstractGameState': 'Live'}, 'R', 'excluded-nonfinal'),
    ({'detailedState': 'Postponed'}, 'R', 'excluded-postponed'),
    ({'detailedState': 'Suspended'}, 'R', 'excluded-suspended'),
    ({'abstractGameState': 'Final'}, 'A', 'excluded-ineligible-game-type'),
])
def test_deterministic_explicit_exclusions(status, game_type, reason):
    payload = bundle()
    payload['schedule']['dates'][0]['games'][0].update(status=status, gameType=game_type)
    payload['games'], payload['people'] = {}, []
    snap = snapshot(); snap['players'] = {}
    manifest = recovery.build_manifest(spec(), payload, snap)
    assert manifest['excluded'] == [dict(game_pk=800, reason=reason)]
    assert manifest['eligible_game_pks'] == []


def test_manifest_byte_stability_and_hash_checks():
    manifest = recovery.build_manifest(spec(), bundle(), snapshot())
    assert recovery.canonical_json(manifest) == recovery.canonical_json(recovery.build_manifest(spec(), bundle(), snapshot()))
    manifest['pinned_payloads']['games']['800']['feed']['gamePk'] = 801
    result = recovery.execute_recovery(manifest, manifest['manifest_sha256'], code_revision=REVISION,
                                       acknowledge_writes=True, connection_factory=lambda: pytest.fail('Connected'))
    assert result['status'] == 'failed-before-write'


def test_tampered_payload_even_with_rehashed_manifest_rejected():
    manifest = recovery.build_manifest(spec(), bundle(), snapshot())
    manifest['pinned_payloads']['games']['800']['feed']['gamePk'] = 801
    manifest['manifest_sha256'] = recovery.digest({k: v for k, v in manifest.items() if k != 'manifest_sha256'})
    result = recovery.execute_recovery(manifest, manifest['manifest_sha256'], code_revision=REVISION,
                                       acknowledge_writes=True, connection_factory=lambda: pytest.fail('Connected'))
    assert result['status'] == 'failed-before-write'


def test_acknowledgement_and_revision_required():
    manifest = recovery.build_manifest(spec(), bundle(), snapshot())
    for ack, revision in [(False, REVISION), (True, 'b' * 40)]:
        result = recovery.execute_recovery(manifest, manifest['manifest_sha256'], code_revision=revision,
                                           acknowledge_writes=ack, connection_factory=lambda: pytest.fail('Connected'))
        assert result['status'] == 'failed-before-write'


@pytest.mark.parametrize('field', ['observed_at', 'canonical_start', 'schedule_start', 'unknown_type',
                                  'game_number', 'doubleheader', 'schedule_metadata'])
def test_interrupted_safeguards_fail_closed(field):
    payload, snap = bundle(), snapshot()
    if field == 'observed_at':
        payload['observed_at'] = '2025-08-02T15:00:00'
    elif field == 'canonical_start':
        snap['games']['800']['start'] = '2025-08-01T19:00:00'
    elif field == 'schedule_start':
        payload['schedule']['dates'][0]['games'][0]['gameDate'] = '2025-08-01T19:00:00'
    elif field == 'unknown_type':
        payload['schedule']['dates'][0]['games'][0]['gameType'] = '?'
    elif field == 'schedule_metadata':
        payload['schedule']['dates'][0]['games'][0]['gameNumber'] = 2
    else:
        key, value = ('gameNumber', 0) if field == 'game_number' else ('doubleHeader', '?')
        payload['games']['800']['feed']['gameData']['game'][key] = value
    with pytest.raises(ValueError):
        recovery.build_manifest(spec(), payload, snap)


def test_implementation_drift_refused_without_connection(monkeypatch):
    manifest = recovery.build_manifest(spec(), bundle(), snapshot())
    monkeypatch.setattr(recovery, 'implementation_hash', lambda: 'b' * 64)
    result = recovery.execute_recovery(manifest, manifest['manifest_sha256'], code_revision=REVISION,
                                       acknowledge_writes=True, connection_factory=lambda: pytest.fail('Connected'))
    assert result['status'] == 'failed-before-write'


def test_typed_approval_requires_exact_hash():
    with pytest.raises(ValueError):
        recovery.ApprovedRecoverySpecification(spec(), 'approved')


def test_commit_uncertainty_not_misreported_as_rollback(monkeypatch):
    manifest = recovery.build_manifest(spec(), bundle(), snapshot())
    class UncertainConnection(ReadOnlyConnection):
        def commit(self):
            raise RuntimeError('Synthetic lost commit acknowledgement')
        def rollback(self):
            raise RuntimeError('Synthetic closed connection')
        def close(self):
            raise RuntimeError('Synthetic closed connection')
    monkeypatch.setattr(recovery, '_revalidate', lambda *a, **k: snapshot())
    monkeypatch.setattr(repository, 'validate_result_scope', lambda *a: None)
    monkeypatch.setattr(recovery, 'save_historical_result', lambda **k: None)
    result = recovery.execute_recovery(manifest, manifest['manifest_sha256'], code_revision=REVISION,
                                       acknowledge_writes=True, connection_factory=UncertainConnection)
    assert result['status'] == 'partial'
    assert result['committed_results'] == []
    assert result['uncertain_commits'] == [dict(phase='results', game_pks=[800])]
    assert 'lost commit acknowledgement' in result['error']


def test_cli_provider_preview_is_read_only_and_execution_never_fetches(monkeypatch, tmp_path, capsys):
    from sportsmodel.ingest import mlb_recovery_cli as cli
    payload = bundle()
    connections = []
    def connect():
        connection = ReadOnlyConnection()
        connections.append(connection)
        return connection
    monkeypatch.setattr(cli, 'get_connection', connect)
    monkeypatch.setattr(cli, 'current_revision', lambda: REVISION)
    monkeypatch.setattr(cli, 'fetch_schedule_for_date', lambda d: payload['schedule'])
    monkeypatch.setattr(cli, 'fetch_live_feed', lambda pk: payload['games'][str(pk)]['feed'])
    monkeypatch.setattr(cli, 'fetch_boxscore', lambda pk: payload['games'][str(pk)]['boxscore'])
    monkeypatch.setattr(cli, 'fetch_mlb_players', lambda ids: payload['people'])
    monkeypatch.setattr(cli, 'plan_recovery', lambda s, b: recovery.plan_recovery(s, b, connection_factory=connect))
    output = tmp_path / 'manifest.json'
    args = ['preview', '--date', '2025-08-01', '--game-pks', '800', '--output', str(output),
            '--acknowledge-provider-access']
    assert cli.main(args) == 0
    manifest = json.loads(output.read_text())
    assert manifest['eligible_game_pks'] == [800]
    assert all(c.settings['readonly'] for c in connections)
    for name in ('get_connection', 'fetch_schedule_for_date', 'fetch_live_feed', 'fetch_boxscore', 'fetch_mlb_players'):
        monkeypatch.setattr(cli, name, lambda *a: pytest.fail('Unexpected DB/provider acquisition'))
    # Existing output refuses before acquisition; execution consumes the file only.
    assert cli.main(args) == 1
    monkeypatch.setattr(cli, 'execute_recovery', lambda m, h, **k: dict(status='partial', manifest_hash=h))
    assert cli.main(['execute', '--manifest', str(output), '--approved-manifest-sha256',
                     manifest['manifest_sha256'], '--acknowledge-production-writes']) == 1
    assert json.loads(capsys.readouterr().out.splitlines()[-1])['status'] == 'partial'


@pytest.mark.parametrize('args', [[], ['preview'], ['execute'],
    ['preview', '--date', '2025-08-01', '--game-pks', '800', '--output', 'manifest.json'],
    ['execute', '--manifest', 'manifest.json', '--approved-manifest-sha256', 'a' * 64]])
def test_cli_requires_explicit_mode_scope_and_acknowledgement(args):
    from sportsmodel.ingest.mlb_recovery_cli import main
    with pytest.raises(SystemExit) as error:
        main(args)
    assert error.value.code == 2


def test_preview_mapping_failure_precedes_mock_provider_access(monkeypatch):
    from sportsmodel.ingest import mlb_recovery_cli as cli
    connection = ReadOnlyConnection()
    connection.reader.mapping_count = 0
    monkeypatch.setattr(cli, 'get_connection', lambda: connection)
    monkeypatch.setattr(cli, 'fetch_schedule_for_date', lambda *a: pytest.fail('Provider contacted'))
    with pytest.raises(ValueError):
        cli.acquire_preview(spec())


def test_defensive_shared_canonical_check_without_weakening_db_constraints(monkeypatch):
    payload = bundle()
    event = deepcopy(payload['schedule']['dates'][0]['games'][0])
    event['gamePk'] = 801
    payload['schedule']['dates'][0]['games'].append(event)
    payload['games']['801'] = deepcopy(payload['games']['800'])
    monkeypatch.setattr(repository, 'resolve_existing_mlb_game', lambda *a, **k: snapshot()['games']['800'])
    with pytest.raises(ValueError, match='share one canonical'):
        recovery.read_snapshot(ReadOnlyCursor(), recovery.RecoverySpecification(date(2025,8,1),(800,801),REVISION), payload)


@pytest.mark.parametrize('dependency', ['database/connection.py', 'ingest/boxscore_parser.py'])
def test_execution_dependency_bytes_change_fingerprint(monkeypatch, tmp_path, dependency):
    # Exercise real file contents in an isolated source tree, never edit the
    # actual connection module or load its synthetic replacement.
    source_root = Path(recovery.__file__).parents[1]
    paths = ['ingest/mlb_recovery.py', 'database/mlb_recovery_repository.py',
             'ingest/mlb_recovery_cli.py', 'database/connection.py',
             'ingest/boxscore_parser.py', 'ingest/mlb_players.py', 'ingest/mlb_stats.py',
             'database/boxscore_repository.py', 'models/parsed_boxscore.py',
             'models/team_game_statistics.py', 'models/player_game_pitching_statistics.py']
    for path in paths:
        destination = tmp_path / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        copyfile(source_root / path, destination)
    original = recovery.implementation_hash()
    monkeypatch.setattr(recovery, '__file__', str(tmp_path / 'ingest/mlb_recovery.py'))
    assert recovery.implementation_hash() == original
    assert recovery.implementation_hash() == original
    with (tmp_path / dependency).open('ab') as stream:
        stream.write(b'\n# Synthetic execution-dependency change; not imported.\n')
    changed = recovery.implementation_hash()
    assert changed != original
    assert recovery.implementation_hash() == changed
    manifest = recovery.build_manifest(spec(), bundle(), snapshot())
    manifest['implementation_hash'] = original
    manifest['manifest_sha256'] = recovery.digest({k: v for k, v in manifest.items() if k != 'manifest_sha256'})
    result = recovery.execute_recovery(manifest, manifest['manifest_sha256'], code_revision=REVISION,
                                       acknowledge_writes=True, connection_factory=lambda: pytest.fail('Connected'))
    assert result['status'] == 'failed-before-write'
    assert result['failure_phase'] == 'approval'


def test_manifest_ignores_dictionary_insertion_order():
    def reversed_dicts(value):
        if isinstance(value, dict):
            return {k: reversed_dicts(v) for k, v in reversed(list(value.items()))}
        if isinstance(value, list):
            return [reversed_dicts(v) for v in value]
        return value
    expected = recovery.build_manifest(spec(), bundle(), snapshot(), protected_references={'a': 1, 'b': 2})
    reordered = recovery.build_manifest(spec(), reversed_dicts(bundle()), reversed_dicts(snapshot()),
                                       protected_references={'b': 2, 'a': 1})
    assert recovery.canonical_json(expected) == recovery.canonical_json(reordered)
    assert expected['manifest_sha256'] == reordered['manifest_sha256']
