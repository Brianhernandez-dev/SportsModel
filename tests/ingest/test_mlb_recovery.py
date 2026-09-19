import ast
from copy import deepcopy
from datetime import date, datetime, timezone
import json
from pathlib import Path
from shutil import copyfile

import pytest

from sportsmodel.ingest import mlb_recovery as recovery
from sportsmodel.database import mlb_recovery_repository as repository


FIXTURE = Path(__file__).parents[1] / 'fixtures/mlb_recovery/synthetic.json'
SEMANTIC_FIXTURE = Path(__file__).parents[1] / 'fixtures/mlb_recovery/semantic_equivalence.json'
REVISION = 'a' * 40


def bundle():
    return json.loads(FIXTURE.read_text())


def semantic_fixture():
    return json.loads(SEMANTIC_FIXTURE.read_text())


def apply_semantic_additions(box, *families):
    fixture = semantic_fixture()
    if 'copyright' in families:
        box['copyright'] = fixture['copyright']
    if 'boxscore_names' in families:
        for side, players in fixture['boxscore_names'].items():
            for player, name in players.items():
                box['teams'][side]['players'][player]['person']['boxscoreName'] = name
    if 'team_hydration' in families:
        for side, values in fixture['team_hydration'].items():
            box['teams'][side]['team'].update(deepcopy(values))


def validation_inputs():
    payload = bundle()
    event = payload['schedule']['dates'][0]['games'][0]
    return event, payload['games']['800']


def spec():
    return recovery.RecoverySpecification(date(2025, 8, 1), (800,), REVISION)


def preview_args(tmp_path, *, game_pk='800', output=None, evidence_name='provider-evidence'):
    output = output or tmp_path / 'manifest.json'
    return ['preview', '--date', '2025-08-01', '--game-pks', game_pk,
            '--output', str(output), '--evidence-output', str(tmp_path / evidence_name),
            '--acknowledge-provider-access']


def snapshot():
    return dict(games={'800': dict(game_id=1, source_id=1,
                                  start='2025-08-01T19:00:00+00:00', home_team_id=1,
                                  away_team_id=2, mlb_game_id=None, odds_api_event_id=None,
                                  sources=[[1, 'mlb_stats', '800']])},
                teams={'10': 1, '20': 2}, players={'100': None, '200': None})


def explicit_literal_raise_line(path, message):
    tree = ast.parse(path.read_text(encoding='utf-8-sig'))
    matches = [node.lineno for node in ast.walk(tree)
               if isinstance(node, ast.Raise)
               and isinstance(node.exc, ast.Call)
               and len(node.exc.args) == 1
               and isinstance(node.exc.args[0], ast.Constant)
               and node.exc.args[0].value == message]
    assert len(matches) == 1
    return matches[0]


def temporary_application_error(tmp_path, source):
    application_root = tmp_path / 'src' / 'sportsmodel'
    application_root.mkdir(parents=True)
    source_path = application_root / 'security_fixture.py'
    source_path.write_text(source, encoding='utf-8')
    namespace = {}
    exec(compile(source, str(source_path), 'exec'), namespace)
    try:
        namespace['fail']()
    except Exception as error:
        return error, application_root, source_path
    raise AssertionError('Temporary failure source did not raise')


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


def test_semantic_boxscore_exact_equality_passes():
    event, pinned = validation_inputs()
    recovery._validate_box(event, pinned)


@pytest.mark.parametrize('families', [
    ('copyright',),
    ('boxscore_names',),
    ('team_hydration',),
    ('copyright', 'boxscore_names', 'team_hydration'),
])
def test_semantic_boxscore_standalone_only_nonmaterial_additions_pass(families):
    event, pinned = validation_inputs()
    apply_semantic_additions(pinned['boxscore'], *families)

    recovery._validate_box(event, pinned)


def test_semantic_boxscore_feed_only_nonmaterial_additions_deliberately_pass():
    event, pinned = validation_inputs()
    apply_semantic_additions(
        pinned['feed']['liveData']['boxscore'],
        'copyright', 'boxscore_names', 'team_hydration',
    )

    recovery._validate_box(event, pinned)


def test_semantic_boxscore_additions_pass_complete_planning():
    payload = bundle()
    apply_semantic_additions(
        payload['games']['800']['boxscore'],
        'copyright', 'boxscore_names', 'team_hydration',
    )

    manifest = recovery.build_manifest(spec(), payload, snapshot())

    assert manifest['eligible_game_pks'] == [800]
    assert manifest['games'][0]['starters'] == [200, 100]


def test_raw_boxscore_diagnostic_still_reports_nonmaterial_additions():
    from sportsmodel.ingest import mlb_recovery_cli as cli

    unused_event, pinned = validation_inputs()
    feed = pinned['feed']['liveData']['boxscore']
    standalone = pinned['boxscore']
    apply_semantic_additions(standalone, 'copyright')

    assert cli.field_differences(feed, standalone) == [{
        'path': '/copyright',
        'feed_present': False,
        'standalone_present': True,
        'feed': None,
        'standalone': semantic_fixture()['copyright'],
    }]


@pytest.mark.parametrize('case', semantic_fixture()['negative_cases'],
                         ids=lambda case: case['name'])
def test_semantic_boxscore_material_difference_fails_closed(case):
    event, pinned = validation_inputs()
    target = pinned['boxscore']
    parent = target
    for component in case['path'][:-1]:
        parent = parent[component]
    if case.get('action') == 'delete':
        del parent[case['path'][-1]]
    else:
        parent[case['path'][-1]] = case['value']

    with pytest.raises(ValueError, match='Standalone/feed boxscore disagreement'):
        recovery._validate_box(event, pinned)


def test_semantic_boxscore_pitcher_order_and_starter_mismatch_fails_closed():
    event, pinned = validation_inputs()
    for box in (pinned['feed']['liveData']['boxscore'], pinned['boxscore']):
        home = box['teams']['home']
        reliever = deepcopy(home['players']['ID100'])
        reliever['person']['id'] = 101
        home['players']['ID101'] = reliever
        home['pitchers'] = [100, 101]
    pinned['boxscore']['teams']['home']['pitchers'] = [101, 100]

    with pytest.raises(ValueError, match='Standalone/feed boxscore disagreement'):
        recovery._validate_box(event, pinned)


def test_semantic_boxscore_projection_is_deterministic():
    def reordered(value):
        if isinstance(value, dict):
            return {key: reordered(item) for key, item in reversed(list(value.items()))}
        if isinstance(value, list):
            return [reordered(item) for item in value]
        return value

    unused_event, pinned = validation_inputs()
    box = pinned['boxscore']
    first = recovery._recovery_boxscore_projection(box)
    second = recovery._recovery_boxscore_projection(reordered(box))

    assert recovery.canonical_json(first) == recovery.canonical_json(second)


def test_semantic_boxscore_validation_does_not_mutate_inputs():
    event, pinned = validation_inputs()
    apply_semantic_additions(
        pinned['boxscore'], 'copyright', 'boxscore_names', 'team_hydration')
    original_event, original_pinned = deepcopy(event), deepcopy(pinned)

    recovery._validate_box(event, pinned)

    assert event == original_event
    assert pinned == original_pinned


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


def test_implementation_drift_rechecked_inside_serializable_transaction(monkeypatch):
    manifest = recovery.build_manifest(spec(), bundle(), snapshot())
    hashes = iter([manifest['implementation_hash'], 'b' * 64])

    class TransactionConnection(ReadOnlyConnection):
        rolled_back = False

        def rollback(self):
            self.rolled_back = True

    connection = TransactionConnection()
    monkeypatch.setattr(recovery, 'implementation_hash', lambda: next(hashes))
    monkeypatch.setattr(recovery, '_revalidate', lambda *args, **kwargs: snapshot())
    monkeypatch.setattr(
        repository, 'validate_recovery_targets_absent',
        lambda *args: pytest.fail('Absence check reached after implementation drift'))

    result = recovery.execute_recovery(
        manifest, manifest['manifest_sha256'], code_revision=REVISION,
        acknowledge_writes=True, connection_factory=lambda: connection)

    assert result['status'] == 'failed-before-write'
    assert result['failure_phase'] == 'preflight'
    assert connection.settings == {'isolation_level': 'SERIALIZABLE'}
    assert connection.rolled_back is True


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
    monkeypatch.setattr(repository, 'validate_recovery_targets_absent', lambda *a: None)
    monkeypatch.setattr(repository, 'insert_recovery_result', lambda *a: None)
    monkeypatch.setattr(
        repository, 'insert_missing_mlb_player',
        lambda unused_cursor, payload, unused_observed_at: payload['id'])
    monkeypatch.setattr(repository, 'save_recovery_boxscore', lambda *a: None)
    result = recovery.execute_recovery(manifest, manifest['manifest_sha256'], code_revision=REVISION,
                                       acknowledge_writes=True, connection_factory=UncertainConnection)
    assert result['status'] == 'unknown-commit-state'
    assert result['committed_results'] == []
    assert result['committed_boxscores'] == []
    assert result['uncertain_commits'] == [dict(phase='commit', game_pks=[800])]
    assert 'lost commit acknowledgement' in result['error']
    assert 'rollback failed' in result['error']


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
    args = preview_args(tmp_path, output=output)
    assert cli.main(args) == 0
    manifest = json.loads(output.read_text())
    assert manifest['eligible_game_pks'] == [800]
    assert capsys.readouterr().out == manifest['manifest_sha256'] + '\n'
    assert all(c.settings['readonly'] for c in connections)
    evidence = tmp_path / 'provider-evidence'
    assert (evidence / 'acquisition_complete.json').is_file()
    assert (evidence / 'schedule.json').is_file()
    assert (evidence / 'games/800/feed.json').is_file()
    assert (evidence / 'games/800/boxscore.json').is_file()
    assert (evidence / 'people.json').is_file()
    retained_hashes = json.loads((evidence / 'payload_hashes.json').read_text())
    assert retained_hashes['payloads'] == [
        {'filename': 'schedule.json', 'game_pk': None,
         'payload_sha256': recovery.digest(payload['schedule']), 'source': 'schedule'},
        {'filename': 'games/800/feed.json', 'game_pk': 800,
         'payload_sha256': recovery.digest(payload['games']['800']['feed']),
         'source': 'live-feed'},
        {'filename': 'games/800/boxscore.json', 'game_pk': 800,
         'payload_sha256': recovery.digest(payload['games']['800']['boxscore']),
         'source': 'standalone-boxscore'},
        {'filename': 'people.json', 'game_pk': None,
         'payload_sha256': recovery.digest(payload['people']), 'source': 'people'},
    ]
    assert json.loads((evidence / 'preview_status.json').read_text())['status'] == 'success'
    for name in ('get_connection', 'fetch_schedule_for_date', 'fetch_live_feed', 'fetch_boxscore', 'fetch_mlb_players'):
        monkeypatch.setattr(cli, name, lambda *a: pytest.fail('Unexpected DB/provider acquisition'))
    # Existing output refuses before acquisition; execution consumes the file only.
    assert cli.main(args) == 1
    monkeypatch.setattr(cli, 'execute_recovery', lambda m, h, **k: dict(status='partial', manifest_hash=h))
    assert cli.main(['execute', '--manifest', str(output), '--approved-manifest-sha256',
                     manifest['manifest_sha256'], '--acknowledge-production-writes']) == 1
    assert json.loads(capsys.readouterr().out.splitlines()[-1])['status'] == 'partial'


def test_literal_value_error_in_isolated_application_root_is_trusted(tmp_path):
    from sportsmodel.ingest import mlb_recovery_cli as cli
    message = 'safe compile-time validation message'
    error, application_root, source_path = temporary_application_error(
        tmp_path, f'def fail():\n    raise ValueError({message!r})\n')
    failure = cli._failure_payload(error, 'preview-planning', application_root)
    assert failure == {
        'error': 'ValueError',
        'failure_phase': 'preview-planning',
        'safe_message': message,
        'source_file': 'src/sportsmodel/security_fixture.py',
        'source_function': 'fail',
        'source_line': explicit_literal_raise_line(source_path, message),
        'status': 'failed-before-write',
    }


@pytest.mark.parametrize('source,secret', [
    ("def fail():\n    secret = 'token=f-string-secret'\n"
     "    raise ValueError(f'bad provider event: {secret!r}')\n",
     'token=f-string-secret'),
    ("def fail():\n    secret = 'token=multiline-secret'\n"
     "    raise ValueError(\n        f'bad provider event: {secret!r}'\n    )\n",
     'token=multiline-secret'),
    ("def fail():\n    secret = 'postgresql://user:dsn-secret@host/db'\n"
     "    try:\n        raise RuntimeError(secret)\n"
     "    except RuntimeError as error:\n"
     "        raise ValueError(f'database lookup failed: {error}') from error\n",
     'dsn-secret'),
    ("def fail():\n    value = 'token=conversion-secret'\n    int(value)\n",
     'token=conversion-secret'),
    ("def fail():\n    secret = 'token=same-line-secret'\n"
     "    if secret: raise ValueError(f'{secret}'); raise ValueError('token=same-line-secret')\n",
     'token=same-line-secret'),
])
def test_dynamic_or_implicit_value_errors_in_trusted_source_are_redacted(
        source, secret, tmp_path):
    from sportsmodel.ingest import mlb_recovery_cli as cli
    error, application_root, unused_path = temporary_application_error(tmp_path, source)
    failure = cli._failure_payload(error, 'preview-planning', application_root)
    serialized = recovery.canonical_json(failure)
    assert secret not in serialized
    assert failure == {
        'error': 'ValueError',
        'failure_phase': 'preview-planning',
        'safe_message': 'redacted',
        'source_file': None,
        'source_function': None,
        'source_line': None,
        'status': 'failed-before-write',
    }


def test_external_value_error_is_redacted_for_isolated_application_root(tmp_path):
    from sportsmodel.ingest import mlb_recovery_cli as cli

    def external_failure():
        raise ValueError('token=external-secret')

    try:
        external_failure()
    except ValueError as error:
        failure = cli._failure_payload(
            error, 'preview-acquisition', tmp_path / 'src' / 'sportsmodel')
    serialized = recovery.canonical_json(failure)
    assert 'external-secret' not in serialized
    assert failure['safe_message'] == 'redacted'
    assert failure['source_function'] is None
    assert failure['source_file'] is None
    assert failure['source_line'] is None


def test_cli_trust_inspection_failure_falls_back_to_redacted_payload(
        monkeypatch, tmp_path, capsys):
    from sportsmodel.ingest import mlb_recovery_cli as cli
    secret = 'token=trust-inspection-secret'
    monkeypatch.setattr(cli, 'current_revision', lambda: REVISION)
    monkeypatch.setattr(cli, 'acquire_preview',
                        lambda unused, evidence=None: recovery._positive(0))

    def failed_trust_inspection(*args, **kwargs):
        raise KeyboardInterrupt(secret)

    monkeypatch.setattr(cli, '_trusted_value_error_details', failed_trust_inspection)
    output = tmp_path / 'manifest.json'
    result = cli.main(preview_args(tmp_path, output=output))
    captured = capsys.readouterr()
    assert result == 1
    assert not output.exists()
    assert secret not in captured.out
    assert secret not in captured.err
    assert 'Traceback' not in captured.out
    assert 'Traceback' not in captured.err
    assert json.loads(captured.out) == {
        'error': 'ValueError',
        'evidence_path': str((tmp_path / 'provider-evidence').resolve()),
        'evidence_status': 'incomplete',
        'failure_phase': 'preview-acquisition',
        'safe_message': 'redacted',
        'source_file': None,
        'source_function': None,
        'source_line': None,
        'status': 'failed-before-write',
    }


def test_cli_spec_validation_literal_reports_safe_phase_and_source(
        monkeypatch, tmp_path, capsys):
    from sportsmodel.ingest import mlb_recovery_cli as cli
    monkeypatch.setattr(cli, 'current_revision', lambda: REVISION)
    monkeypatch.setattr(cli, 'acquire_preview', lambda unused: pytest.fail('Provider contacted'))
    output = tmp_path / 'manifest.json'
    result = cli.main(preview_args(tmp_path, game_pk='0', output=output))
    failure = json.loads(capsys.readouterr().out)
    message = 'gamePk/participant IDs must be positive integers'
    assert result == 1
    assert not output.exists()
    assert failure['failure_phase'] == 'spec-validation'
    assert failure['safe_message'] == message
    assert failure['source_file'] == 'src/sportsmodel/ingest/mlb_recovery.py'
    assert failure['source_function'] == '_positive'
    assert failure['source_line'] == explicit_literal_raise_line(
        Path(recovery.__file__), message)


@pytest.mark.parametrize('phase', ['preview-acquisition', 'preview-planning'])
def test_cli_trusted_value_error_reports_safe_phase_and_source(
        phase, monkeypatch, tmp_path, capsys):
    from sportsmodel.ingest import mlb_recovery_cli as cli
    monkeypatch.setattr(cli, 'current_revision', lambda: REVISION)
    if phase == 'preview-acquisition':
        monkeypatch.setattr(cli, 'acquire_preview',
                            lambda unused, evidence=None: recovery._positive(0))
    else:
        def acquired(unused, evidence=None):
            evidence.complete()
            return {}
        monkeypatch.setattr(cli, 'acquire_preview', acquired)
        monkeypatch.setattr(cli, 'plan_recovery',
                            lambda unused_spec, unused_bundle: recovery._positive(0))
    output = tmp_path / 'manifest.json'
    result = cli.main(preview_args(tmp_path, output=output))
    failure = json.loads(capsys.readouterr().out)
    assert result == 1
    assert not output.exists()
    message = 'gamePk/participant IDs must be positive integers'
    expected = {
        'error': 'ValueError',
        'failure_phase': phase,
        'safe_message': message,
        'source_file': 'src/sportsmodel/ingest/mlb_recovery.py',
        'source_function': '_positive',
        'source_line': explicit_literal_raise_line(Path(recovery.__file__), message),
        'status': 'failed-before-write',
    }
    expected.update(evidence_path=str((tmp_path / 'provider-evidence').resolve()),
                    evidence_status=('complete' if phase == 'preview-planning'
                                     else 'incomplete'))
    assert failure == expected


def test_cli_manifest_write_failure_removes_partial_file_and_redacts(
        monkeypatch, tmp_path, capsys):
    from sportsmodel.ingest import mlb_recovery_cli as cli
    monkeypatch.setattr(cli, 'current_revision', lambda: REVISION)
    def acquired(unused, evidence=None):
        evidence.complete()
        return {}
    monkeypatch.setattr(cli, 'acquire_preview', acquired)
    monkeypatch.setattr(
        cli, 'plan_recovery',
        lambda unused_spec, unused_bundle: {'manifest_sha256': 'a' * 64},
    )
    output = tmp_path / 'manifest.json'
    original_open = Path.open

    class FailingWriter:
        def __init__(self, stream):
            self.stream = stream

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.stream.close()

        def write(self, value):
            self.stream.write(value[:8])
            self.stream.flush()
            raise ValueError('token=manifest-write-secret')

    def failing_stream(path, *args, **kwargs):
        if path == output:
            return FailingWriter(original_open(path, *args, **kwargs))
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'open', failing_stream)
    result = cli.main(preview_args(tmp_path, output=output))
    console = capsys.readouterr().out
    failure = json.loads(console)
    assert result == 1
    assert not output.exists()
    assert 'manifest-write-secret' not in console
    assert failure == {
        'error': 'ValueError',
        'evidence_path': str((tmp_path / 'provider-evidence').resolve()),
        'evidence_status': 'complete',
        'failure_phase': 'manifest-write',
        'safe_message': 'redacted',
        'source_file': None,
        'source_function': None,
        'source_line': None,
        'status': 'failed-before-write',
    }


def test_cli_existing_manifest_refusal_reports_output_precheck_without_acquisition(
        monkeypatch, tmp_path, capsys):
    from sportsmodel.ingest import mlb_recovery_cli as cli
    monkeypatch.setattr(cli, 'current_revision', lambda: REVISION)
    monkeypatch.setattr(cli, 'acquire_preview', lambda unused: pytest.fail('Provider contacted'))
    output = tmp_path / 'manifest.json'
    output.write_text('retained approval artifact')
    result = cli.main(preview_args(tmp_path, output=output))
    failure = json.loads(capsys.readouterr().out)
    message = 'Preview output must be a new file in an existing directory'
    assert result == 1
    assert output.read_text() == 'retained approval artifact'
    assert failure == {
        'error': 'ValueError',
        'failure_phase': 'preview-output-precheck',
        'safe_message': message,
        'source_file': 'src/sportsmodel/ingest/mlb_recovery_cli.py',
        'source_function': 'main',
        'source_line': explicit_literal_raise_line(Path(cli.__file__), message),
        'status': 'failed-before-write',
    }


def test_cli_non_value_error_message_remains_redacted(
        monkeypatch, tmp_path, capsys):
    from sportsmodel.ingest import mlb_recovery_cli as cli
    monkeypatch.setattr(cli, 'current_revision', lambda: REVISION)

    def provider_failure(unused, evidence=None):
        raise RuntimeError('token=provider-secret')

    monkeypatch.setattr(cli, 'acquire_preview', provider_failure)
    output = tmp_path / 'manifest.json'
    result = cli.main(preview_args(tmp_path, output=output))
    console = capsys.readouterr().out
    assert result == 1
    assert not output.exists()
    assert 'provider-secret' not in console
    assert json.loads(console) == {
        'error': 'RuntimeError',
        'evidence_path': str((tmp_path / 'provider-evidence').resolve()),
        'evidence_status': 'incomplete',
        'failure_phase': 'preview-acquisition',
        'safe_message': 'redacted',
        'source_file': None,
        'source_function': None,
        'source_line': None,
        'status': 'failed-before-write',
    }


def test_planning_failure_retains_complete_provider_evidence(
        monkeypatch, tmp_path, capsys):
    from sportsmodel.ingest import mlb_recovery_cli as cli
    payload = bundle()
    connection = ReadOnlyConnection()
    monkeypatch.setattr(cli, 'get_connection', lambda: connection)
    monkeypatch.setattr(cli, 'current_revision', lambda: REVISION)
    monkeypatch.setattr(cli, 'fetch_schedule_for_date', lambda unused: payload['schedule'])
    monkeypatch.setattr(cli, 'fetch_live_feed', lambda pk: payload['games'][str(pk)]['feed'])
    monkeypatch.setattr(cli, 'fetch_boxscore', lambda pk: payload['games'][str(pk)]['boxscore'])
    monkeypatch.setattr(cli, 'fetch_mlb_players', lambda unused: payload['people'])
    monkeypatch.setattr(cli, 'plan_recovery',
                        lambda unused_spec, unused_bundle: recovery._positive(0))
    output = tmp_path / 'manifest.json'

    assert cli.main(preview_args(tmp_path, output=output)) == 1

    failure = json.loads(capsys.readouterr().out)
    evidence = tmp_path / 'provider-evidence'
    assert failure['failure_phase'] == 'preview-planning'
    assert failure['evidence_path'] == str(evidence.resolve())
    assert failure['evidence_status'] == 'complete'
    assert not output.exists()
    assert (evidence / 'acquisition_complete.json').is_file()
    assert json.loads((evidence / 'preview_status.json').read_text())['status'] == 'planning-failed'
    assert connection.settings['readonly'] is True


def test_acquisition_failure_retains_partial_evidence_without_complete_marker(
        monkeypatch, tmp_path, capsys):
    from sportsmodel.ingest import mlb_recovery_cli as cli
    payload = bundle()
    monkeypatch.setattr(cli, 'get_connection', ReadOnlyConnection)
    monkeypatch.setattr(cli, 'current_revision', lambda: REVISION)
    monkeypatch.setattr(cli, 'fetch_schedule_for_date', lambda unused: payload['schedule'])
    monkeypatch.setattr(cli, 'fetch_live_feed', lambda pk: payload['games'][str(pk)]['feed'])

    def failed_boxscore(unused):
        raise RuntimeError('token=provider-request-secret')

    monkeypatch.setattr(cli, 'fetch_boxscore', failed_boxscore)
    output = tmp_path / 'manifest.json'

    assert cli.main(preview_args(tmp_path, output=output)) == 1

    console = capsys.readouterr().out
    evidence = tmp_path / 'provider-evidence'
    assert 'provider-request-secret' not in console
    assert (evidence / 'schedule.json').is_file()
    assert (evidence / 'games/800/feed.json').is_file()
    assert not (evidence / 'games/800/boxscore.json').exists()
    assert not (evidence / 'acquisition_complete.json').exists()
    assert not (evidence / 'payload_hashes.json').exists()
    assert json.loads((evidence / 'acquisition_metadata.json').read_text())['status'] == 'acquisition-failed'
    assert json.loads((evidence / 'preview_status.json').read_text())['status'] == 'acquisition-failed'
    assert not output.exists()


def test_retained_payload_hashes_ignore_dictionary_insertion_order(tmp_path):
    from sportsmodel.ingest import mlb_recovery_cli as cli

    def reordered(value):
        if isinstance(value, dict):
            return {key: reordered(item) for key, item in reversed(list(value.items()))}
        if isinstance(value, list):
            return [reordered(item) for item in value]
        return value

    first = cli.PreviewEvidence(tmp_path / 'first', spec())
    second = cli.PreviewEvidence(tmp_path / 'second', spec())
    first.schedule(bundle()['schedule'], spec().schedule_date)
    second.schedule(reordered(bundle()['schedule']), spec().schedule_date)
    first.complete()
    second.complete()
    first_hashes = json.loads((first.path / 'payload_hashes.json').read_text())
    second_hashes = json.loads((second.path / 'payload_hashes.json').read_text())
    assert first_hashes == second_hashes


def test_evidence_metadata_allowlist_excludes_request_and_database_secrets(
        monkeypatch, tmp_path):
    from sportsmodel.ingest import mlb_recovery_cli as cli
    payload = bundle()
    request_secret = 'token=request-object-secret'
    database_secret = 'postgresql://user:database-secret@host/database'

    class Provider:
        session_headers = {'Authorization': request_secret}

        def __call__(self, unused):
            return payload['schedule']

    connection = ReadOnlyConnection()
    connection.dsn = database_secret
    monkeypatch.setattr(cli, 'get_connection', lambda: connection)
    monkeypatch.setattr(cli, 'fetch_schedule_for_date', Provider())
    monkeypatch.setattr(cli, 'fetch_live_feed', lambda pk: payload['games'][str(pk)]['feed'])
    monkeypatch.setattr(cli, 'fetch_boxscore', lambda pk: payload['games'][str(pk)]['boxscore'])
    monkeypatch.setattr(cli, 'fetch_mlb_players', lambda unused: payload['people'])
    evidence = cli.PreviewEvidence(tmp_path / 'evidence', spec())

    cli.acquire_preview(spec(), evidence=evidence)

    retained = '\n'.join(path.read_text(encoding='utf-8')
                         for path in evidence.path.rglob('*.json'))
    assert request_secret not in retained
    assert database_secret not in retained
    metadata = json.loads((evidence.path / 'acquisition_metadata.json').read_text())
    assert set(metadata['requests'][0]) == {
        'endpoint_path', 'filename', 'game_pk', 'observation_timestamp',
        'payload_sha256', 'query_parameters', 'source',
    }


def test_field_diff_reports_real_shape_and_does_not_mutate_inputs():
    from sportsmodel.ingest import mlb_recovery_cli as cli
    payload = bundle()
    feed = deepcopy(payload['games']['800']['feed']['liveData']['boxscore'])
    standalone = deepcopy(payload['games']['800']['boxscore'])
    standalone['teams']['home']['teamStats']['batting']['runs'] = 99
    original_feed, original_standalone = deepcopy(feed), deepcopy(standalone)

    differences = cli.field_differences(feed, standalone)

    assert differences == [{
        'path': '/teams/home/teamStats/batting/runs',
        'feed_present': True,
        'standalone_present': True,
        'feed': 5,
        'standalone': 99,
    }]
    assert feed == original_feed
    assert standalone == original_standalone


def test_diagnostic_mode_reads_retained_payloads_without_provider_or_database(
        monkeypatch, tmp_path, capsys):
    from sportsmodel.ingest import mlb_recovery_cli as cli
    payload = bundle()
    evidence = cli.PreviewEvidence(tmp_path / 'evidence', spec())
    evidence.schedule(payload['schedule'], spec().schedule_date)
    evidence.feed(payload['games']['800']['feed'], 800)
    standalone = deepcopy(payload['games']['800']['boxscore'])
    standalone['teams']['away']['team']['id'] = 999
    evidence.boxscore(standalone, 800)
    evidence.complete()
    for name in ('get_connection', 'fetch_schedule_for_date', 'fetch_live_feed',
                 'fetch_boxscore', 'fetch_mlb_players'):
        monkeypatch.setattr(cli, name, lambda *args: pytest.fail('External access'))

    assert cli.main(['diagnose-evidence', '--evidence', str(evidence.path)]) == 0

    report = json.loads(capsys.readouterr().out)
    assert report['games'] == [{
        'game_pk': 800,
        'equal': False,
        'differences': [{
            'path': '/teams/away/team/id',
            'feed_present': True,
            'standalone_present': True,
            'feed': 20,
            'standalone': 999,
        }],
    }]


def test_evidence_directory_inside_repository_is_refused_before_creation():
    from sportsmodel.ingest import mlb_recovery_cli as cli
    target = Path(cli.__file__).resolve().parents[3] / 'forbidden-provider-evidence'
    assert not target.exists()
    with pytest.raises(ValueError, match='outside the repository'):
        cli.PreviewEvidence(target, spec())
    assert not target.exists()


def test_manifest_path_cannot_become_evidence_directory_parent(
        monkeypatch, tmp_path, capsys):
    from sportsmodel.ingest import mlb_recovery_cli as cli
    monkeypatch.setattr(cli, 'current_revision', lambda: REVISION)
    monkeypatch.setattr(cli, 'acquire_preview', lambda *args, **kwargs: pytest.fail('Provider contacted'))
    output = tmp_path / 'manifest.json'
    evidence = output / 'provider-evidence'
    args = preview_args(tmp_path, output=output)
    args[args.index('--evidence-output') + 1] = str(evidence)

    assert cli.main(args) == 1

    failure = json.loads(capsys.readouterr().out)
    assert failure['failure_phase'] == 'evidence-output-precheck'
    assert failure['safe_message'] == 'Manifest and provider evidence paths must be distinct'
    assert not output.exists()


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
