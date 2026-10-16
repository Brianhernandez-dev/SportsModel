"""Offline arbitration byte/protocol tests; fake connections are not PG proof.

No test connects to a DB, runs a provider, discovers credentials, or issues a real
authorization. The synthetic target and evidence are deliberately isolated. Tests
of wrapper order/fault containment do not certify actual database rollback, locks,
MVCC, replay or any complete acceptance scenario.
"""
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO
import json
from types import SimpleNamespace
import zipfile

import pytest


PROFILE = 'a' * 64
COMMIT = 'b' * 40
REJECTED_INPUT = (ValueError, KeyError, TypeError, zipfile.BadZipFile)


@pytest.fixture(autouse=True)
def offline_boundaries(monkeypatch):
    import dotenv
    import psycopg2
    import requests
    import socket
    def blocked(*args, **kwargs):
        raise AssertionError('Real DB/provider/network access forbidden in offline unit tests')
    monkeypatch.setattr(dotenv, 'load_dotenv', lambda *args, **kwargs: False)
    monkeypatch.setattr(psycopg2, 'connect', blocked)
    monkeypatch.setattr(requests.sessions.Session, 'request', blocked)
    monkeypatch.setattr(socket, 'create_connection', blocked)
    monkeypatch.setattr(socket.socket, 'connect', blocked)


@pytest.fixture
def operator(monkeypatch):
    from sportsmodel.operations import mlb_canonical_time_arbitration as module
    monkeypatch.setattr(module, 'current_commit', lambda: COMMIT)
    monkeypatch.setattr(module, 'profile_fingerprint', lambda: PROFILE)
    return module


@pytest.fixture
def target(operator):
    return operator.OperatorTarget(host='127.0.0.1', port=59999,
        database='sportsmodel_test_arbitration210_999', server_address='127.0.0.1',
        server_port=5432, postmaster_started_at='2026-10-12T00:00:00Z',
        identity_kind='isolated', system_identifier='123456789')


def event():
    return dict(gamePk=900584, officialDate='2026-07-12', gameDate='2026-07-12T17:40:00Z',
        gameType='R', doubleHeader='N', gameNumber=1, ifNecessary='N',
        status=dict(abstractGameState='Final', detailedState='Final', startTimeTBD=False),
        teams=dict(home=dict(team=dict(id=146, name='Miami Marlins'), score=3),
                   away=dict(team=dict(id=114, name='Cleveland Guardians'), score=1)))


def archive(entries):
    output = BytesIO()
    with zipfile.ZipFile(output, 'w') as zipped:
        for name, payload in entries:
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            zipped.writestr(info, payload)
    return output.getvalue()


def origin_entries(raw_payload):
    """Explicit isolated synthetic acquisition record, never native authenticity."""
    metadata = json.dumps(dict(
        url='https://statsapi.mlb.com/api/v1/schedule?sportId=1&date=2026-07-12',
        final_url='https://statsapi.mlb.com/api/v1/schedule?sportId=1&date=2026-07-12',
        http_status=200, observed_utc='2026-10-12T00:00:00+00:00',
        sha256=sha256(raw_payload).hexdigest(), bytes=len(raw_payload), requests=1,
        anonymous=True, paid_Odds_API=False, server_date='Mon, 12 Oct 2026 00:00:00 GMT',
        content_type='application/json;charset=UTF-8', synthetic=True), sort_keys=True).encode()
    members = [('synthetic_schedule.json', raw_payload), ('origin_metadata.json', metadata)]
    manifest = '| Entry | Bytes | SHA-256 |\n' + ''.join(
        f'| {name} | {len(value)} | {sha256(value).hexdigest()} |\n' for name, value in members)
    chain = archive(members + [('REVIEW_MANIFEST.md', manifest.encode())])
    return metadata, [('origin_metadata.json', metadata), ('source_chain.zip', chain)]


def bundle(operator, *, payload=None, raw_payload=None, changes=None, extra_entries=None):
    if raw_payload is None:
        if payload is None:
            payload = dict(dates=[dict(date='2026-07-12', games=[event()])])
        raw_payload = operator.canonical_json(payload).encode()
    metadata, origins = origin_entries(raw_payload)
    evidence = archive([('synthetic_schedule.json', raw_payload)] + origins + (extra_entries or []))
    request = dict(format=operator.FORMAT, version=1, domain='MLB', subject=584, survivor=26,
        game_pk=900584, target_date='2026-07-12', old_start='2026-07-12T17:41:00Z',
        new_start='2026-07-12T17:40:00Z', evidence_sha256=sha256(evidence).hexdigest(),
        payload_entry='synthetic_schedule.json', payload_sha256=sha256(raw_payload).hexdigest(),
        origin_attestation_sha256=sha256(metadata).hexdigest(), operator_identity='Synthetic isolated test actor',
        tool_identity='Offline protocol test', implementation_commit=COMMIT, profile=PROFILE,
        duplicate_proof_approved=True, publication_attribution_clear=True)
    request.update(changes or {})
    return operator.canonical_json(request).encode(), evidence


def no_connection_factory():
    raise AssertionError('Invalid request/evidence must refuse before connection factory')


def refusal_before_connection(operator, target, raw, evidence):
    with pytest.raises(REJECTED_INPUT):
        operator.preview_arbitration(request_bytes=raw, evidence_bytes=evidence,
            target=target, connection_factory=no_connection_factory)


def test_T01_strict_synthetic_request_outputs_fixed_case_without_discovery(operator, target):
    raw, evidence = bundle(operator)
    request, db_request = operator.validate_request(raw, evidence, target)
    assert request['subject'] == 584 and request['survivor'] == 26
    assert db_request['request_sha256'] == sha256(raw).hexdigest()
    assert db_request['evidence_sha256'] == sha256(evidence).hexdigest()
    assert db_request['retirement_case']['proof']['gamePk'] == 900584
    assert db_request['retirement_case']['proof']['home_mlb_id'] == 146
    assert db_request['retirement_case']['proof']['away_mlb_id'] == 114
    assert db_request['retirement_case']['proof']['subject_start'] == '2026-07-12T17:40:00Z'


@pytest.mark.parametrize('change', [
    {'old_start': '2026-07-12T17:39:00Z'},  # Requests +60, not the approved -60.
    {'old_start': '2026-07-12T17:42:00Z'}, {'new_start': '2026-07-12T17:41:00Z'},
    {'old_start': '2026-07-12T17:41:00'}, {'new_start': 'infinity'},
    {'subject': 26}, {'survivor': 584}, {'subject': 585}, {'survivor': 27},
    {'game_pk': 823842}, {'game_pk': 900585}, {'game_pk': True},
    {'domain': 'NFL'}, {'version': True}, {'version': 2}, {'target_date': '2026-07-13'},
    {'duplicate_proof_approved': False}, {'publication_attribution_clear': False},
    {'duplicate_proof_approved': 1}, {'publication_attribution_clear': 'true'},
    {'profile': 'd' * 64}, {'implementation_commit': 'e' * 40},
])
def test_T02_T05_T13_wrong_case_or_clearance_refuses_before_connection(operator, target, change):
    raw, evidence = bundle(operator, changes=change)
    refusal_before_connection(operator, target, raw, evidence)


@pytest.mark.parametrize('key', ['format', 'old_start', 'new_start', 'game_pk',
                               'payload_sha256', 'origin_attestation_sha256', 'profile',
                               'publication_attribution_clear'])
def test_T17_missing_request_fields_refuse_before_connection(operator, target, key):
    raw, evidence = bundle(operator)
    value = json.loads(raw)
    value.pop(key)
    refusal_before_connection(operator, target, operator.canonical_json(value).encode(), evidence)


@pytest.mark.parametrize('change', [
    {'unreviewed': 1}, {'origin_attestation_sha256': None}, {'origin_attestation_sha256': 'c' * 63},
    {'origin_attestation_sha256': 'C' * 64}, {'operator_identity': ''},
    {'operator_identity': ' '}, {'tool_identity': 'x' * 1001},
    {'payload_entry': '../synthetic_schedule.json'}, {'payload_entry': r'folder\schedule.json'},
    {'payload_entry': 'not-json.txt'}, {'payload_sha256': 'f' * 64},
    {'evidence_sha256': '0' * 64},
])
def test_T17_request_field_schema_and_hash_binding_refuse(operator, target, change):
    raw, evidence = bundle(operator, changes=change)
    refusal_before_connection(operator, target, raw, evidence)


@pytest.mark.parametrize('raw', [b'not-json', b'[]', b'null', b'{"version":1,"version":1}',
                               b'{"x":NaN}', b'{"x":Infinity}', b' ' * 128001],
                         ids=['invalid_json', 'non_object_list', 'json_null', 'duplicate_keys',
                              'nonfinite_nan', 'nonfinite_infinity', 'over_request_limit'])
def test_T17_malformed_duplicate_nonfinite_or_oversized_request(operator, target, raw):
    _, evidence = bundle(operator)
    refusal_before_connection(operator, target, raw, evidence)


@pytest.mark.parametrize('payload', [None, [], {}, {'dates': None}, {'dates': {}},
    {'dates': []}, {'dates': [None]}, {'dates': [{}]},
    {'dates': [{'date': '2026-07-13', 'games': [event()]}]},
    {'dates': [{'date': '20260712', 'games': [event()]}]},
    {'dates': [{'date': '2026-07-12'}]},
    {'dates': [{'date': '2026-07-12', 'games': {}}]},
    {'dates': [{'date': '2026-07-12', 'games': [event(), None]}]},
    {'dates': [{'date': '2026-07-12', 'games': [event()]}, {'date': '2026-07-13', 'games': []}]},
])
def test_T17_entire_schedule_envelope_must_support_unique_fixed_event(operator, target, payload):
    # Explicit raw encoding preserves JSON null instead of bundle's default payload.
    raw, evidence = bundle(operator, raw_payload=operator.canonical_json(payload).encode())
    refusal_before_connection(operator, target, raw, evidence)


@pytest.mark.parametrize('change', [
    {'gamePk': 900585}, {'gamePk': True}, {'gameDate': '2026-07-12T17:41:00Z'},
    {'officialDate': '2026-07-13'}, {'gameType': 'D'}, {'gameType': 'S'}, {'gameType': 'X'},
    {'doubleHeader': 'Y'}, {'gameNumber': 2}, {'ifNecessary': 'Y'},
    {'rescheduleDate': '2026-07-13'}, {'resumeDate': '2026-07-13'},
    {'status': {'abstractGameState': 'Preview', 'detailedState': 'Scheduled', 'startTimeTBD': False}},
    {'status': {'abstractGameState': 'Final', 'detailedState': 'Final', 'startTimeTBD': True}},
])
def test_T04_T08_T17_nonfixed_or_ambiguous_event_metadata_refuses(operator, target, change):
    value = event()
    value.update(change)
    raw, evidence = bundle(operator, payload={'dates': [{'date': '2026-07-12', 'games': [value]}]})
    refusal_before_connection(operator, target, raw, evidence)


@pytest.mark.parametrize('change', ['reversal', 'wrong_home_id', 'wrong_away_id', 'wrong_home_name',
                                   'historical_alias', 'second_oriented_game', 'duplicate_gamePk',
                                   'malformed_surrounding_game'])
def test_T06_T08_T17_orientation_and_surrounding_game_conflicts_refuse(operator, target, change):
    value = event()
    games = [value]
    if change == 'reversal':
        value['teams']['home'], value['teams']['away'] = value['teams']['away'], value['teams']['home']
    elif change == 'wrong_home_id':
        value['teams']['home']['team']['id'] = 147
    elif change == 'wrong_away_id':
        value['teams']['away']['team']['id'] = 133
    elif change == 'wrong_home_name':
        value['teams']['home']['team']['name'] = 'Synthetic unresolved club'
    elif change == 'historical_alias':
        value['teams']['away']['team']['name'] = 'Cleveland Indians'
    elif change == 'second_oriented_game':
        other = deepcopy(value)
        other['gamePk'] = 900585
        other['gameDate'] = '2026-07-12T19:40:00Z'
        games.append(other)
    elif change == 'duplicate_gamePk':
        games.append(deepcopy(value))
    else:
        games.append({})
    raw, evidence = bundle(operator, payload={'dates': [{'date': '2026-07-12', 'games': games}]})
    refusal_before_connection(operator, target, raw, evidence)


@pytest.mark.parametrize('payload', [b'{"dates":[],"dates":[]}',
                                    b'{"dates":[{"date":"2026-07-12","games":[NaN]}]}',
                                    b'invalid', b' ' * 2000001],
                         ids=['duplicate_dates', 'nonfinite_game', 'invalid_json', 'over_entry_limit'])
def test_T17_raw_payload_duplicate_nonfinite_parse_and_entry_size_refuse(operator, target, payload):
    raw, evidence = bundle(operator, raw_payload=payload)
    refusal_before_connection(operator, target, raw, evidence)


def test_T17_duplicate_archive_entry_refuses(operator, target):
    payload = operator.canonical_json({'dates': [{'date': '2026-07-12', 'games': [event()]}]}).encode()
    with pytest.warns(UserWarning, match='Duplicate name'):
        raw, evidence = bundle(operator, raw_payload=payload,
                               extra_entries=[('synthetic_schedule.json', payload)])
    refusal_before_connection(operator, target, raw, evidence)


class FakeCursor:
    def __init__(self, connection):
        self.connection = connection
        self.row = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, statement, args=None):
        connection = self.connection
        connection.events.append((connection.label, 'utility' if statement.startswith('SET LOCAL') else 'execute', statement, args))
        if connection.fail_statement and connection.fail_statement in statement:
            raise RuntimeError('Synthetic statement failure')
        if 'operator_state()' in statement:
            self.row = (deepcopy(connection.state),)
        elif 'correct_exact(' in statement:
            self.row = ({'audit_id': 1, 'operation_receipt': 'synthetic-operation-receipt'},)
        else:
            self.row = (None,)

    def fetchone(self):
        return self.row


class FakeConnection:
    def __init__(self, label, target, state, events):
        self.label, self.state, self.events = label, deepcopy(state), events
        self.info = SimpleNamespace(host=target.host, port=target.port, dbname=target.database, backend_pid=901)
        self.fail_statement = None
        self.fail_commit = False
        self.fail_rollback = False
        self.committed = False

    def set_session(self, **kwargs):
        self.events.append((self.label, 'set_session', kwargs))

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.events.append((self.label, 'commit'))
        self.committed = True  # Synthetic ACK-loss case models an already durable commit.
        if self.fail_commit:
            raise RuntimeError('Synthetic commit acknowledgement loss')

    def rollback(self):
        self.events.append((self.label, 'rollback'))
        if self.fail_rollback:
            raise RuntimeError('Synthetic rollback acknowledgement loss')

    def close(self):
        self.events.append((self.label, 'close'))


@pytest.fixture
def protocol(operator, target, monkeypatch):
    events = []
    state = {'state': {'profile': PROFILE, 'topology': 1, 'audits': []},
             'business': {'synthetic_fixture': []}, 'subject_forbidden': [], 'operation': None}
    guard = {'target': target.artifact(), 'profile': PROFILE}
    monkeypatch.setattr(operator, 'verify_target', lambda connection, explicit, **kwargs: deepcopy(guard))
    monkeypatch.setattr(operator, 'verify_locked_target', lambda connection, explicit, **kwargs: deepcopy(guard))
    def migrations():
        events.append(('preflight', 'migration_reference'))
        return ((36, 'synthetic-036.sql', 'd' * 64),)
    monkeypatch.setattr(operator, 'migration_reference', migrations)
    raw, evidence = bundle(operator)
    preview_connection = FakeConnection('preview', target, state, events)
    preview = operator.preview_arbitration(request_bytes=raw, evidence_bytes=evidence, target=target,
                                           connection_factory=lambda: preview_connection)
    events.clear()
    primary = FakeConnection('X', target, state, events)
    probe = FakeConnection('probe', target, state, events)
    calls = []
    def factory():
        calls.append(len(calls))
        if len(calls) == 1:
            return primary
        if len(calls) == 2:
            return probe
        raise AssertionError('Automatic retry or unexpected third connection')
    def execute(**changes):
        kwargs = dict(request_bytes=raw, evidence_bytes=evidence, target=target, connection_factory=factory,
                      preview=preview, approved_preview_sha256=preview['preview_sha256'], acknowledge_writes=True)
        kwargs.update(changes)
        return operator.execute_arbitration(**kwargs)
    return SimpleNamespace(events=events, primary=primary, probe=probe, calls=calls,
        raw=raw, evidence=evidence, preview=preview, execute=execute, target=target)


def test_T24_T25_unit_wrapper_lock_probe_protocol_without_second_gate(protocol):
    assert protocol.execute()['audit_id'] == 1
    queries = [(entry[0], entry[2]) for entry in protocol.events if entry[1] == 'execute']
    assert queries == [('X', 'SELECT mlb036_private.acquire_exact_gate()'),
                       ('X', 'SELECT mlb036_private.lock_exact()'),
                       ('X', 'SELECT mlb036_private.operator_state()'),
                       ('probe', 'SELECT mlb036_private.operator_state()'),
                       ('X', 'SELECT mlb036_private.correct_exact(%s::jsonb,%s::jsonb,%s)'),
                       ('X', 'SET CONSTRAINTS ALL IMMEDIATE')]
    assert protocol.events[0] == ('preflight', 'migration_reference')
    assert ('X', 'set_session', {'readonly': False, 'isolation_level': 'SERIALIZABLE', 'autocommit': False}) in protocol.events
    assert ('probe', 'set_session', {'readonly': True, 'isolation_level': 'READ COMMITTED', 'autocommit': False}) in protocol.events
    utilities = [entry for entry in protocol.events if entry[1] == 'utility']
    expected_timeouts = ["SET LOCAL lock_timeout='1500ms'", "SET LOCAL statement_timeout='15000ms'"]
    assert [(entry[0], entry[2]) for entry in utilities] == [
        ('X', statement) for statement in expected_timeouts] + [
        ('probe', statement) for statement in expected_timeouts]
    gate_index = next(index for index, entry in enumerate(protocol.events)
                      if entry[1] == 'execute' and 'acquire_exact_gate()' in entry[2])
    assert all(protocol.events.index(entry) < gate_index for entry in utilities if entry[0] == 'X')
    probe_query_index = next(index for index, entry in enumerate(protocol.events)
                             if entry[0] == 'probe' and entry[1] == 'execute')
    assert all(gate_index < protocol.events.index(entry) < probe_query_index
               for entry in utilities if entry[0] == 'probe')
    assert sum(entry[1] == 'commit' for entry in protocol.events) == 1
    assert len(protocol.calls) == 2


@pytest.mark.parametrize('change', ['guard', 'fresh_state', 'approved_state', 'probe_endpoint'])
def test_T23_T24_unit_drift_refuses_before_correction(protocol, operator, monkeypatch, change):
    if change == 'guard':
        monkeypatch.setattr(operator, 'verify_locked_target', lambda *args, **kwargs: {'changed': True})
    elif change == 'fresh_state':
        protocol.probe.state['state']['topology'] = 2
    elif change == 'approved_state':
        protocol.primary.state['state']['topology'] = 2
        protocol.probe.state['state']['topology'] = 2
    else:
        protocol.probe.info.port = 59998
    with pytest.raises(operator.OperatorRefusal):
        protocol.execute()
    assert not any(entry[1] == 'execute' and 'correct_exact(' in entry[2] for entry in protocol.events)
    assert not any(entry[1] == 'commit' for entry in protocol.events)
    assert ('X', 'rollback') in protocol.events and ('X', 'close') in protocol.events


@pytest.mark.parametrize('point', ['acquire_exact_gate()', 'lock_exact()', 'correct_exact(', 'SET CONSTRAINTS'])
def test_T26_T28_unit_statement_fault_cleanup_has_no_automatic_retry(protocol, point):
    protocol.primary.fail_statement = point
    with pytest.raises(RuntimeError, match='Synthetic statement failure'):
        protocol.execute()
    assert ('X', 'rollback') in protocol.events and ('X', 'close') in protocol.events
    assert not any(entry[1] == 'commit' for entry in protocol.events)
    assert len(protocol.calls) <= 2


def test_T28_unit_uncertain_rollback_explicit_unknown_no_retry(protocol, operator):
    protocol.primary.fail_statement = 'correct_exact('
    protocol.primary.fail_rollback = True
    with pytest.raises(operator.OperatorRefusal, match='UNKNOWN correction outcome'):
        protocol.execute()
    assert len(protocol.calls) == 2 and ('X', 'close') in protocol.events


def test_T29_unit_lost_commit_acknowledgement_requires_inspection_not_retry(protocol, operator):
    protocol.primary.fail_commit = True
    with pytest.raises(operator.OperatorRefusal, match='UNKNOWN commit acknowledgement'):
        protocol.execute()
    assert protocol.primary.committed is True
    assert sum(entry[1] == 'commit' for entry in protocol.events) == 1
    assert len(protocol.calls) == 2 and ('X', 'close') in protocol.events


@pytest.mark.parametrize('field', ['request', 'db_request', 'request_sha256', 'evidence_sha256',
                                  'guard', 'state', 'preview_sha256', 'unknown_field'])
def test_T17_T32_tampered_preview_refuses_before_factory(protocol, operator, field):
    preview = deepcopy(protocol.preview)
    preview[field] = 'tampered'
    with pytest.raises(operator.OperatorRefusal, match='byte identity'):
        protocol.execute(preview=preview)
    assert protocol.calls == []


@pytest.mark.parametrize('acknowledgement', [False, None, 1, 'true'])
def test_T13_explicit_true_write_acknowledgement_required(protocol, operator, acknowledgement):
    with pytest.raises(operator.OperatorRefusal, match='write authorization'):
        protocol.execute(acknowledge_writes=acknowledgement)
    assert protocol.calls == []


def test_T17_preview_emitted_exact_bytes_must_be_reused(protocol, operator):
    semantically_same_raw = json.dumps(json.loads(protocol.raw), indent=2).encode()
    assert semantically_same_raw != protocol.raw
    with pytest.raises(operator.OperatorRefusal, match='byte identity'):
        protocol.execute(request_bytes=semantically_same_raw)
    assert protocol.calls == []


@pytest.mark.parametrize('change', ['float_game_pk', 'bool_game_number', 'float_home_id',
                                   'float_away_id', 'bool_home_score', 'string_away_score',
                                   'negative_home_score', 'missing_away_score'])
def test_T17_authoritative_provider_identity_and_result_fields_require_strict_types(
        operator, target, change):
    value = event()
    if change == 'float_game_pk':
        value['gamePk'] = 900584.0
    elif change == 'bool_game_number':
        value['gameNumber'] = True
    elif change == 'float_home_id':
        value['teams']['home']['team']['id'] = 146.0
    elif change == 'float_away_id':
        value['teams']['away']['team']['id'] = 114.0
    elif change == 'bool_home_score':
        value['teams']['home']['score'] = True
    elif change == 'string_away_score':
        value['teams']['away']['score'] = '1'
    elif change == 'negative_home_score':
        value['teams']['home']['score'] = -1
    else:
        value['teams']['away'].pop('score')
    raw, evidence = bundle(operator, payload={'dates': [{'date': '2026-07-12', 'games': [value]}]})
    refusal_before_connection(operator, target, raw, evidence)


def test_T24_missing_fresh_probe_factory_refuses_without_correction_or_retry(protocol, operator):
    calls = []
    def factory():
        calls.append('connect')
        if len(calls) == 1:
            return protocol.primary
        raise operator.OperatorRefusal('Synthetic fresh probe unavailable')
    with pytest.raises(operator.OperatorRefusal, match='probe unavailable'):
        protocol.execute(connection_factory=factory)
    assert calls == ['connect', 'connect']
    assert ('X', 'rollback') in protocol.events and ('X', 'close') in protocol.events
    assert not any(entry[1] == 'execute' and 'correct_exact(' in entry[2] for entry in protocol.events)
    assert not any(entry[1] == 'commit' for entry in protocol.events)


@pytest.mark.parametrize('change', ['string_request', 'bytearray_request', 'string_evidence',
                                   'bytearray_evidence', 'untyped_target', 'oversized_evidence'])
def test_T17_explicit_bounded_byte_and_target_boundaries_refuse(operator, target, change):
    raw, evidence = bundle(operator)
    if change == 'string_request':
        raw = raw.decode()
    elif change == 'bytearray_request':
        raw = bytearray(raw)
    elif change == 'string_evidence':
        evidence = 'synthetic-evidence-not-bytes'
    elif change == 'bytearray_evidence':
        evidence = bytearray(evidence)
    elif change == 'untyped_target':
        target = SimpleNamespace(host='127.0.0.1', port=59999)
    else:
        evidence = b'x' * 10000001
    refusal_before_connection(operator, target, raw, evidence)


def operation_for(protocol):
    return dict(request_sha256=sha256(protocol.raw).hexdigest(),
                approval_sha256=protocol.preview['preview_sha256'], post_state_current=True,
                audit_id=1, operation_receipt={'fixture': 'committed synthetic operation'})


def assert_no_mock_correction_or_commit(protocol):
    assert not any(entry[1] == 'execute' and 'correct_exact(' in entry[2] for entry in protocol.events)
    assert not any(entry[1] == 'commit' for entry in protocol.events)


def test_T31_exact_applied_operation_replay_refuses_without_mutation(protocol, operator):
    applied = operation_for(protocol)
    protocol.primary.state['operation'] = deepcopy(applied)
    protocol.probe.state['operation'] = deepcopy(applied)
    with pytest.raises(operator.OperatorRefusal, match='ALREADY_APPLIED_REFUSAL'):
        protocol.execute()
    assert_no_mock_correction_or_commit(protocol)
    assert len(protocol.calls) == 2
    assert ('X', 'rollback') in protocol.events and ('X', 'close') in protocol.events


@pytest.mark.parametrize('change', ['request_hash', 'approval_hash', 'stale_poststate',
                                   'missing_request_hash', 'missing_approval_hash',
                                   'unproven_poststate', 'fresh_probe_mismatch'])
def test_T32_applied_operation_replay_mismatch_refuses_without_mutation(protocol, operator, change):
    applied = operation_for(protocol)
    if change == 'request_hash':
        applied['request_sha256'] = 'd' * 64
    elif change == 'approval_hash':
        applied['approval_sha256'] = 'e' * 64
    elif change == 'stale_poststate':
        applied['post_state_current'] = False
    elif change == 'missing_request_hash':
        applied.pop('request_sha256')
    elif change == 'missing_approval_hash':
        applied.pop('approval_sha256')
    elif change == 'unproven_poststate':
        applied['post_state_current'] = None
    protocol.primary.state['operation'] = deepcopy(applied)
    protocol.probe.state['operation'] = deepcopy(applied)
    if change == 'fresh_probe_mismatch':
        protocol.probe.state['operation']['audit_id'] = 2
    with pytest.raises(operator.OperatorRefusal, match='operation.*mismatch'):
        protocol.execute()
    assert_no_mock_correction_or_commit(protocol)
    assert len(protocol.calls) == 2 and ('X', 'close') in protocol.events


def inspect_operation(operator, protocol, connection, request_hash=None):
    calls = []
    def factory():
        calls.append('inspection')
        assert len(calls) == 1, 'Inspection must not retry or execute another correction'
        return connection
    result = operator.inspect_arbitration(request_sha256=request_hash or sha256(protocol.raw).hexdigest(),
        target=protocol.target, connection_factory=factory)
    assert calls == ['inspection']
    return result


def test_T29_readonly_operation_inspection_returns_committed_applied_evidence(protocol, operator):
    applied = operation_for(protocol)
    connection = FakeConnection('inspection', protocol.target, {'operation': applied}, protocol.events)
    result = inspect_operation(operator, protocol, connection)
    assert result['status'] == 'COMMITTED_APPLIED'
    assert result['operation'] == applied and result['retry_authorized'] is False
    assert result['label'] == 'RAW_FORENSIC' and result['historically_certified'] is False
    assert ('inspection', 'set_session', {'readonly': True, 'isolation_level': 'REPEATABLE READ',
                                         'autocommit': False}) in protocol.events
    assert ('inspection', 'rollback') in protocol.events and ('inspection', 'close') in protocol.events
    assert_no_mock_correction_or_commit(protocol)


def test_T30_absent_committed_operation_is_indeterminate_never_rollback_or_retry_proof(protocol, operator):
    connection = FakeConnection('inspection', protocol.target, {'operation': None}, protocol.events)
    result = inspect_operation(operator, protocol, connection)
    assert result['status'] == 'INDETERMINATE_NO_COMMITTED_RECEIPT'
    assert result['retry_authorized'] is False and result['rollback_proven'] is False
    assert result['label'] == 'RAW_FORENSIC' and result['historically_certified'] is False
    assert_no_mock_correction_or_commit(protocol)
    assert ('inspection', 'rollback') in protocol.events and ('inspection', 'close') in protocol.events


@pytest.mark.parametrize('change', ['request_hash', 'missing_hash', 'stale_poststate', 'unproven_poststate'])
def test_T29_T32_inspection_identity_or_poststate_mismatch_refuses_and_cleans_up(protocol, operator, change):
    applied = operation_for(protocol)
    if change == 'request_hash':
        applied['request_sha256'] = 'f' * 64
    elif change == 'missing_hash':
        applied.pop('request_sha256')
    else:
        applied['post_state_current'] = False if change == 'stale_poststate' else None
    connection = FakeConnection('inspection', protocol.target, {'operation': applied}, protocol.events)
    with pytest.raises(operator.OperatorRefusal, match='identity/post-state differs'):
        inspect_operation(operator, protocol, connection)
    assert_no_mock_correction_or_commit(protocol)
    assert ('inspection', 'rollback') in protocol.events and ('inspection', 'close') in protocol.events


@pytest.mark.parametrize('request_hash', [None, 1, '', 'a' * 63, 'A' * 64, 'z' * 64])
def test_T17_inspection_hash_shape_refuses_before_factory(operator, target, request_hash):
    with pytest.raises(operator.OperatorRefusal, match='Exact operation request hash'):
        operator.inspect_arbitration(request_sha256=request_hash, target=target,
                                    connection_factory=no_connection_factory)


@pytest.mark.parametrize('failure', ['state_read', 'target_guard', 'rollback'])
def test_T28_readonly_inspection_closes_on_each_fault(protocol, operator, monkeypatch, failure):
    connection = FakeConnection('inspection', protocol.target, {'operation': None}, protocol.events)
    if failure == 'state_read':
        connection.fail_statement = 'operator_state()'
    elif failure == 'rollback':
        connection.fail_rollback = True
    else:
        def fail_guard(*args, **kwargs):
            raise RuntimeError('Synthetic target guard failure')
        monkeypatch.setattr(operator, 'verify_target', fail_guard)
    with pytest.raises(RuntimeError, match='Synthetic'):
        inspect_operation(operator, protocol, connection)
    assert ('inspection', 'close') in protocol.events
    assert_no_mock_correction_or_commit(protocol)


def test_T29_unknown_commit_can_be_followed_only_by_readonly_operation_inspection(protocol, operator):
    protocol.primary.fail_commit = True
    with pytest.raises(operator.OperatorRefusal, match='UNKNOWN commit acknowledgement'):
        protocol.execute()
    connection = FakeConnection('inspection', protocol.target, {'operation': operation_for(protocol)}, protocol.events)
    result = inspect_operation(operator, protocol, connection)
    assert result['status'] == 'COMMITTED_APPLIED' and result['retry_authorized'] is False
    assert sum(entry[1] == 'commit' for entry in protocol.events) == 1
    assert len(protocol.calls) == 2  # Never calls the correction factory again.
    assert ('inspection', 'rollback') in protocol.events and ('inspection', 'close') in protocol.events
