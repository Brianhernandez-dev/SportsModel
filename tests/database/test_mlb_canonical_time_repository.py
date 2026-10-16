"""MLB036 client contract tests, using inert connections and no external state.

These are unit proofs only. They do not establish PostgreSQL MVCC, role isolation,
the two-transaction gap, or any complete acceptance-scenario PASS by themselves.
"""
from dataclasses import FrozenInstanceError, replace
from datetime import date, datetime, timedelta, timezone, tzinfo
import json
from types import SimpleNamespace

import pytest

from sportsmodel.database import mlb_canonical_time_repository as repository
from sportsmodel.database.mlb_operator_guard import OperatorRefusal


PROFILE = 'a' * 64
BODY = 'b' * 64
ENDPOINT = ('127.0.0.1', 55572, 'sportsmodel_test_arbitration210_36')
AVAILABLE = datetime(2026, 10, 12, 12, tzinfo=timezone.utc)
CUTOFF = AVAILABLE + timedelta(seconds=1)
_DEFAULT_VALIDATION = object()
TIMEOUT_STATEMENTS = (
    ('execute', "SET LOCAL lock_timeout='1500ms'", None),
    ('execute', "SET LOCAL statement_timeout='15000ms'", None),
)
VALIDATE_WRITE_SQL = 'SELECT mlb036_private.validate_knowledge(%s,%s,false)'


class _Cursor:
    def __init__(self, connection):
        self.connection = connection
        self.last_sql = ''

    def __enter__(self):
        self.connection.events.append('cursor_enter')
        return self

    def __exit__(self, *_):
        self.connection.events.append('cursor_exit')

    def execute(self, sql, params=None):
        self.connection.events.append(('execute', sql, params))
        self.last_sql = sql
        if sql.startswith('SET LOCAL '):
            return
        if self.connection.execute_error:
            raise self.connection.execute_error

    def fetchone(self):
        self.connection.events.append('fetchone')
        assert not self.last_sql.startswith('SET LOCAL '), 'Utility statements have no result rows'
        if self.last_sql == VALIDATE_WRITE_SQL:
            return (self.connection.validated_row,)
        return (self.connection.row,)


class _Connection:
    """No connect implementation: every database operation is a recorded fake."""
    def __init__(self, row, *, endpoint=ENDPOINT, execute_error=None,
                 commit_error=None, rollback_error=None, validated_row=_DEFAULT_VALIDATION):
        self.info = SimpleNamespace(host=endpoint[0], port=endpoint[1], dbname=endpoint[2])
        self.row = row
        self.events = []
        self.execute_error = execute_error
        self.commit_error = commit_error
        self.rollback_error = rollback_error
        self.validated_row = ({'receipt': {'receipt_body_sha256': BODY}}
                              if validated_row is _DEFAULT_VALIDATION else validated_row)

    def set_session(self, **kwargs):
        self.events.append(('session', kwargs))

    def cursor(self):
        return _Cursor(self)

    def commit(self):
        self.events.append('commit')
        if self.commit_error:
            raise self.commit_error

    def rollback(self):
        self.events.append('rollback')
        if self.rollback_error:
            raise self.rollback_error

    def close(self):
        self.events.append('close')


@pytest.fixture(autouse=True)
def _pin_synthetic_profile(monkeypatch):
    monkeypatch.setattr(repository, 'profile_fingerprint', lambda: PROFILE)


@pytest.fixture
def receipt():
    return repository.KnowledgeReceipt(1, BODY, AVAILABLE, PROFILE, ENDPOINT)


def _issuer_row():
    return dict(receipt_id=1, receipt_body_sha256=BODY,
                available_at=AVAILABLE.isoformat(), schema_capability_profile=PROFILE)


def _packet(**changes):
    row = dict(certification='MLB036_CERTIFIED', receipt_id=1,
               receipt_body_sha256=BODY, cutoff_time=CUTOFF.isoformat(), state_fingerprint='c' * 64, rows=[])
    row.update(changes)
    return row


def _executes(connection):
    return [event for event in connection.events if isinstance(event, tuple) and event[0] == 'execute']


def _selects(connection):
    return [event for event in _executes(connection) if event[1].startswith('SELECT ')]


def test_knowledge_wrapper_commits_once_before_returning_locator():
    connection = _Connection(_issuer_row())
    calls = []
    def factory():
        calls.append('open')
        return connection
    receipt = repository.issue_knowledge(connection_factory=factory)
    assert calls == ['open']
    assert receipt == repository.KnowledgeReceipt(1, BODY, AVAILABLE, PROFILE, ENDPOINT)
    assert connection.events[0] == ('session', {'readonly': False, 'isolation_level': 'READ COMMITTED', 'autocommit': False})
    assert connection.events[-2:] == ['commit', 'close']
    assert _executes(connection) == [*TIMEOUT_STATEMENTS, ('execute', 'SELECT mlb036_private.issue_knowledge()', None)]
    assert 'rollback' not in connection.events


def test_knowledge_wrapper_never_retries_after_commit_acknowledgement_loss():
    connection = _Connection(_issuer_row(), commit_error=RuntimeError('synthetic acknowledgement loss'))
    calls = []
    def factory():
        calls.append('open')
        return connection
    with pytest.raises(OperatorRefusal, match='UNKNOWN issuance acknowledgement.*no retry'):
        repository.issue_knowledge(connection_factory=factory)
    assert calls == ['open']
    assert connection.events.count('commit') == 1
    assert connection.events[-2:] == ['rollback', 'close']


def test_knowledge_wrapper_preserves_precommit_failure_and_closes():
    error = RuntimeError('synthetic issuer refusal')
    connection = _Connection(None, execute_error=error)
    with pytest.raises(RuntimeError) as caught:
        repository.issue_knowledge(connection_factory=lambda: connection)
    assert caught.value is error
    assert 'commit' not in connection.events
    assert connection.events[-2:] == ['rollback', 'close']


def test_knowledge_wrapper_failed_rollback_is_uncertain_and_still_closes():
    connection = _Connection(None, execute_error=RuntimeError('synthetic issuer refusal'),
                             rollback_error=RuntimeError('synthetic rollback loss'))
    with pytest.raises(OperatorRefusal, match='UNKNOWN issuance outcome.*no retry'):
        repository.issue_knowledge(connection_factory=lambda: connection)
    assert 'commit' not in connection.events
    assert connection.events[-1] == 'close'


@pytest.mark.parametrize('field,value', [
    ('receipt_id', True), ('receipt_id', 0), ('receipt_id', -1), ('receipt_id', '1'),
    ('body_sha256', ''), ('body_sha256', 'g' * 64), ('body_sha256', 'b' * 63),
    ('profile', ''), ('profile', 'g' * 64), ('profile', 'a' * 63),
    ('available_at', datetime(2026, 10, 12)), ('available_at', '2026-10-12T12:00:00Z'),
    ('endpoint', ('localhost', 55572, 'sportsmodel_test_arbitration210_36')),
    ('endpoint', ('127.0.0.1', True, 'sportsmodel_test_arbitration210_36')),
    ('endpoint', ('127.0.0.1', 0, 'sportsmodel_test_arbitration210_36')),
    ('endpoint', ('127.0.0.1', 55572, '')),
])
def test_typed_locator_rejects_malformed_fields_at_construction(receipt, field, value):
    with pytest.raises(OperatorRefusal):
        replace(receipt, **{field: value})


def test_validate_knowledge_binds_exact_cutoff_endpoint_and_body(receipt):
    result = {'receipt': {'receipt_body_sha256': BODY}, 'state': {'synthetic': True}}
    connection = _Connection(result)
    assert repository.validate_knowledge(_Cursor(connection), receipt, cutoff_time=CUTOFF) is result
    assert connection.events == [
        ('execute', 'SELECT mlb036_private.validate_knowledge(%s,%s,%s)', (1, CUTOFF, True)),
        'fetchone',
    ]


@pytest.mark.parametrize('receipt_change,cutoff,endpoint', [
    ({}, AVAILABLE - timedelta(microseconds=1), ENDPOINT),
    ({}, CUTOFF.replace(tzinfo=None), ENDPOINT),
    ({'profile': 'c' * 64}, CUTOFF, ENDPOINT),
    ({}, CUTOFF, ('127.0.0.1', 55573, ENDPOINT[2])),
    ({}, CUTOFF, ('127.0.0.1', ENDPOINT[1], ENDPOINT[2] + '_other')),
])
def test_validation_refuses_local_mismatch_before_sql(receipt, receipt_change, cutoff, endpoint):
    connection = _Connection(None, endpoint=endpoint)
    with pytest.raises(OperatorRefusal):
        repository.validate_knowledge(_Cursor(connection), replace(receipt, **receipt_change), cutoff_time=cutoff)
    assert connection.events == []


def test_validation_refuses_changed_server_receipt_body(receipt):
    connection = _Connection({'receipt': {'receipt_body_sha256': 'c' * 64}})
    with pytest.raises(OperatorRefusal, match='receipt bytes changed'):
        repository.validate_knowledge(_Cursor(connection), receipt, cutoff_time=CUTOFF)


class _NonAwareZone(tzinfo):
    def utcoffset(self, _):
        return None


@pytest.mark.parametrize('factory,cutoff', [
    (None, CUTOFF), (object(), CUTOFF), (lambda: None, None),
    (lambda: None, CUTOFF.replace(tzinfo=None)),
    (lambda: None, datetime(2026, 10, 12, tzinfo=_NonAwareZone())),
])
def test_reader_requires_factory_and_genuinely_aware_cutoff(receipt, factory, cutoff):
    with pytest.raises(OperatorRefusal):
        repository.CertifiedReader(factory, receipt, cutoff)


def test_reader_cutoff_and_receipt_binding_are_immutable(receipt):
    reader = repository.CertifiedReader(lambda: None, receipt, CUTOFF)
    with pytest.raises(FrozenInstanceError):
        reader.cutoff_time = CUTOFF + timedelta(seconds=1)
    with pytest.raises(FrozenInstanceError):
        reader.receipt = replace(receipt, receipt_id=2)


def test_empty_reader_result_still_calls_gateway_then_rolls_back_and_closes(receipt):
    connection = _Connection(_packet())
    reader = repository.CertifiedReader(lambda: connection, receipt, CUTOFF)
    assert reader.rows('game', id=26) == ()
    assert connection.events[0] == ('session', {'readonly': True, 'isolation_level': 'READ COMMITTED', 'autocommit': False})
    assert _executes(connection) == [*TIMEOUT_STATEMENTS, ('execute', 'SELECT mlb036_private.certified_data(%s,%s,%s,%s::jsonb)',
                         (1, CUTOFF, 'game', '{"id": 26}'))]
    assert connection.events[-2:] == ['rollback', 'close']
    assert 'commit' not in connection.events


@pytest.mark.parametrize('changes', [
    {'certification': 'RAW_FORENSIC'}, {'receipt_id': 2},
    {'receipt_id': True},
    {'receipt_body_sha256': 'c' * 64}, {'receipt_body_sha256': None},
    {'state_fingerprint': ''}, {'state_fingerprint': 'g' * 64},
    {'state_fingerprint': 'c' * 63}, {'unexpected': 'not reviewed'},
    {'cutoff_time': (CUTOFF + timedelta(microseconds=1)).isoformat()},
])
def test_reader_refuses_wrong_server_packet_identity(receipt, changes):
    connection = _Connection(_packet(**changes))
    reader = repository.CertifiedReader(lambda: connection, receipt, CUTOFF)
    with pytest.raises(OperatorRefusal, match='certified result identity differs'):
        reader.rows('game', id=26)
    assert connection.events[-2:] == ['rollback', 'close']


@pytest.mark.parametrize('rows', [{}, '', None, [None], ['not a row'], [26]])
def test_reader_malformed_rows_cannot_masquerade_as_successful_empty_result(receipt, rows):
    connection = _Connection(_packet(rows=rows))
    reader = repository.CertifiedReader(lambda: connection, receipt, CUTOFF)
    with pytest.raises(OperatorRefusal):
        reader.rows('game', id=26)
    assert connection.events[-2:] == ['rollback', 'close']


def test_reader_mapping_rows_preserve_order_and_content(receipt):
    rows = [{'game_id': 26}, {'game_id': 584}]
    connection = _Connection(_packet(rows=rows))
    reader = repository.CertifiedReader(lambda: connection, receipt, CUTOFF)
    assert reader.rows('game', id=26) == tuple(rows)
    assert connection.events[-2:] == ['rollback', 'close']


@pytest.mark.parametrize('cutoff', [None, '2026-10-12T12:00:01Z',
                                    datetime(2026, 10, 12, tzinfo=_NonAwareZone())])
def test_validate_requires_genuinely_aware_datetime_before_sql(receipt, cutoff):
    connection = _Connection(None)
    with pytest.raises(OperatorRefusal):
        repository.validate_knowledge(_Cursor(connection), receipt, cutoff_time=cutoff)
    assert connection.events == []


@pytest.mark.parametrize('changes', [{'profile': 'c' * 64}, {'available_at': CUTOFF + timedelta(seconds=1)}])
def test_reader_profile_or_availability_mismatch_never_opens_connection(receipt, changes):
    calls = []
    reader = repository.CertifiedReader(lambda: calls.append('unexpected'), replace(receipt, **changes), CUTOFF)
    with pytest.raises(OperatorRefusal):
        reader.rows('game', id=26)
    assert calls == []


def test_reader_wrong_endpoint_closes_without_sql_or_session_change(receipt):
    connection = _Connection(None, endpoint=('127.0.0.1', 55573, ENDPOINT[2]))
    reader = repository.CertifiedReader(lambda: connection, receipt, CUTOFF)
    with pytest.raises(OperatorRefusal, match='client endpoint differs'):
        reader.rows('game', id=26)
    assert connection.events == ['rollback', 'close']


def test_reader_gateway_failure_has_no_fallback_no_commit_and_closes(receipt):
    error = RuntimeError('synthetic server proof refusal')
    connection = _Connection(None, execute_error=error)
    reader = repository.CertifiedReader(lambda: connection, receipt, CUTOFF)
    with pytest.raises(RuntimeError) as caught:
        reader.rows('game', id=26)
    assert caught.value is error
    assert len(_selects(connection)) == 1
    assert 'commit' not in connection.events
    assert connection.events[-2:] == ['rollback', 'close']


def test_reader_cleanup_closes_even_if_readonly_rollback_fails(receipt):
    connection = _Connection(_packet(), rollback_error=RuntimeError('synthetic cleanup failure'))
    reader = repository.CertifiedReader(lambda: connection, receipt, CUTOFF)
    with pytest.raises(RuntimeError, match='synthetic cleanup failure'):
        reader.rows('game', id=26)
    assert connection.events[-2:] == ['rollback', 'close']


def _reserve_kwargs(**changes):
    result = dict(target_date=date(2026, 10, 12), model_version='synthetic-model-v1',
                  feature_schema_version='synthetic-features-v1', model_artifact_sha256='d' * 64,
                  model_training_cutoff=AVAILABLE - timedelta(days=1), run_type='preview')
    result.update(changes)
    return result


def _prediction(**changes):
    from sportsmodel.models.moneyline_prediction import MoneylineGamePrediction
    values = dict(moneyline_prediction_run_id=7, game_id=26, mlb_game_id=900584,
                  game_start_time=CUTOFF + timedelta(hours=1), prediction_time=CUTOFF,
                  home_team_id=14, away_team_id=76, home_starting_pitcher_id=None,
                  away_starting_pitcher_id=None, home_starting_pitcher_mlb_id=None,
                  away_starting_pitcher_mlb_id=None, home_starter_features_available=False,
                  away_starter_features_available=False, starter_coverage='none',
                  missing_raw_value_count=0, home_win_probability=0.6, away_win_probability=0.4,
                  predicted_team_id=14, predicted_probability=0.6)
    values.update(changes)
    return MoneylineGamePrediction(**values)


def _lifecycle_call(reader, operation):
    if operation == 'reserve':
        return reader.reserve_run(**_reserve_kwargs())
    if operation == 'finish':
        return reader.finish_run(run_id=7, outcome='completed', games_received=10,
                                 predictions_created=7, games_skipped=3)
    if operation == 'prediction':
        return reader.insert_prediction(_prediction())
    raise AssertionError('Unknown synthetic test operation')


@pytest.mark.parametrize('operation', ['reserve', 'finish', 'prediction'])
def test_lifecycle_uses_dedicated_rc_write_and_one_fixed_statement(receipt, operation):
    connection = _Connection(None if operation == 'finish' else 7)
    reader = repository.CertifiedReader(lambda: connection, receipt, CUTOFF)
    assert _lifecycle_call(reader, operation) == (None if operation == 'finish' else 7)
    assert connection.events[0] == ('session', {'readonly': False, 'isolation_level': 'READ COMMITTED', 'autocommit': False})
    assert connection.events[-2:] == ['commit', 'close']
    assert connection.events.count('commit') == 1 and 'rollback' not in connection.events
    assert _executes(connection)[:2] == list(TIMEOUT_STATEMENTS)
    selects = _selects(connection)
    assert len(selects) == (1 if operation == 'finish' else 2)
    if operation != 'finish':
        assert selects[0] == ('execute', VALIDATE_WRITE_SQL, (receipt.receipt_id, CUTOFF))
    _, sql, params = selects[-1]
    if operation == 'reserve':
        assert sql == 'SELECT mlb036_private.reserve_run(%s,%s,%s::jsonb)'
        assert params[:2] == (receipt.receipt_id, CUTOFF)
        request = json.loads(params[2])
        assert set(request) == {'target_date', 'run_type', 'model_version', 'feature_schema_version',
                                'model_artifact_sha256', 'model_training_cutoff'}
        assert request['target_date'] == '2026-10-12'
        assert request['model_training_cutoff'] == (AVAILABLE - timedelta(days=1)).isoformat()
    elif operation == 'finish':
        assert sql == 'SELECT mlb036_private.finish_run(%s,%s,%s,%s,%s,%s::jsonb,%s)'
        assert params[:5] == (receipt.receipt_id, CUTOFF, BODY, 7, 'completed')
        assert json.loads(params[5]) == {'games_received': 10, 'predictions_created': 7, 'games_skipped': 3}
        assert params[6] is None
    else:
        assert sql == 'SELECT mlb036_private.insert_prediction(%s,%s,%s::jsonb)'
        assert params[:2] == (receipt.receipt_id, CUTOFF)
        request = json.loads(params[2])
        assert len(request) == 19
        assert request['moneyline_prediction_run_id'] == 7
        assert request['prediction_time'] == CUTOFF.isoformat()
        assert request['game_start_time'] == (CUTOFF + timedelta(hours=1)).isoformat()


@pytest.mark.parametrize('operation', ['reserve', 'finish', 'prediction'])
def test_lifecycle_profile_mismatch_never_opens_connection(receipt, operation):
    calls = []
    reader = repository.CertifiedReader(lambda: calls.append('unexpected'),
                                       replace(receipt, profile='c' * 64), CUTOFF)
    with pytest.raises(OperatorRefusal):
        _lifecycle_call(reader, operation)
    assert calls == []


@pytest.mark.parametrize('operation', ['reserve', 'finish', 'prediction'])
def test_lifecycle_endpoint_mismatch_never_executes_or_commits(receipt, operation):
    connection = _Connection(None, endpoint=('127.0.0.1', 55573, ENDPOINT[2]))
    reader = repository.CertifiedReader(lambda: connection, receipt, CUTOFF)
    with pytest.raises(OperatorRefusal, match='lifecycle endpoint differs'):
        _lifecycle_call(reader, operation)
    assert connection.events == ['rollback', 'close']


@pytest.mark.parametrize('operation', ['reserve', 'finish', 'prediction'])
def test_lifecycle_lost_commit_acknowledgement_never_retries(receipt, operation):
    connection = _Connection(None if operation == 'finish' else 7,
                             commit_error=RuntimeError('synthetic acknowledgement loss'))
    calls = []
    def factory():
        calls.append('open')
        return connection
    reader = repository.CertifiedReader(factory, receipt, CUTOFF)
    with pytest.raises(OperatorRefusal, match='UNKNOWN lifecycle acknowledgement.*no retry'):
        _lifecycle_call(reader, operation)
    assert calls == ['open']
    assert connection.events.count('commit') == 1
    assert len(_selects(connection)) == (1 if operation == 'finish' else 2)
    assert connection.events[-2:] == ['rollback', 'close']


@pytest.mark.parametrize('operation', ['reserve', 'finish', 'prediction'])
def test_lifecycle_server_refusal_rolls_back_and_closes_without_fallback(receipt, operation):
    error = RuntimeError('synthetic server proof refusal')
    connection = _Connection(None, execute_error=error)
    reader = repository.CertifiedReader(lambda: connection, receipt, CUTOFF)
    with pytest.raises(RuntimeError) as caught:
        _lifecycle_call(reader, operation)
    assert caught.value is error
    assert 'commit' not in connection.events
    assert len(_selects(connection)) == 1
    assert connection.events[-2:] == ['rollback', 'close']


def test_lifecycle_rollback_failure_is_uncertain_and_connection_still_closes(receipt):
    connection = _Connection(None, execute_error=RuntimeError('synthetic refusal'),
                             rollback_error=RuntimeError('synthetic cleanup failure'))
    reader = repository.CertifiedReader(lambda: connection, receipt, CUTOFF)
    with pytest.raises(OperatorRefusal, match='UNKNOWN lifecycle outcome.*no retry'):
        reader.reserve_run(**_reserve_kwargs())
    assert 'commit' not in connection.events
    assert connection.events[-2:] == ['rollback', 'close']


def test_lifecycle_absent_result_rolls_back_without_commit(receipt, monkeypatch):
    connection = _Connection(None)
    fetchone = _Cursor.fetchone
    monkeypatch.setattr(_Cursor, 'fetchone', lambda self: None if self.last_sql.startswith(
        'SELECT mlb036_private.reserve_run(') else fetchone(self))
    reader = repository.CertifiedReader(lambda: connection, receipt, CUTOFF)
    with pytest.raises(OperatorRefusal, match='returned no result'):
        reader.reserve_run(**_reserve_kwargs())
    assert 'commit' not in connection.events
    assert connection.events[-2:] == ['rollback', 'close']


@pytest.mark.parametrize('operation', ['raw', 'SELECT 1', 'reserve; SELECT 1', '', None])
def test_lifecycle_cannot_supply_arbitrary_sql_or_unknown_operation(receipt, operation):
    calls = []
    reader = repository.CertifiedReader(lambda: calls.append('unexpected'), receipt, CUTOFF)
    with pytest.raises(OperatorRefusal):
        reader._write(operation, ())
    assert calls == []


@pytest.mark.parametrize('changes', [
    {'target_date': '2026-10-12'}, {'target_date': CUTOFF},
    {'model_training_cutoff': '2026-10-11T12:00:00Z'},
    {'model_training_cutoff': CUTOFF.replace(tzinfo=None)},
    {'model_training_cutoff': datetime(2026, 10, 11, tzinfo=_NonAwareZone())},
    {'model_training_cutoff': CUTOFF + timedelta(microseconds=1)},
    {'model_version': ''}, {'model_version': 'x' * 101}, {'model_version': 1},
    {'feature_schema_version': ''}, {'feature_schema_version': 'x' * 51}, {'feature_schema_version': 1},
    {'model_artifact_sha256': 'D' * 64}, {'model_artifact_sha256': 'd' * 63}, {'model_artifact_sha256': 1},
    {'run_type': 'historical'}, {'run_type': None},
])
def test_reservation_malformed_request_refuses_before_connection(receipt, changes):
    calls = []
    reader = repository.CertifiedReader(lambda: calls.append('unexpected'), receipt, CUTOFF)
    with pytest.raises(OperatorRefusal):
        reader.reserve_run(**_reserve_kwargs(**changes))
    assert calls == []


def test_reservation_null_training_cutoff_is_preserved_not_backfilled(receipt):
    connection = _Connection(7)
    reader = repository.CertifiedReader(lambda: connection, receipt, CUTOFF)
    assert reader.reserve_run(**_reserve_kwargs(model_training_cutoff=None)) == 7
    execute = _selects(connection)[-1]
    assert json.loads(execute[2][2])['model_training_cutoff'] is None


@pytest.mark.parametrize('changes', [
    {'run_id': True}, {'run_id': 0}, {'run_id': '7'}, {'outcome': 'running'},
    {'games_received': True}, {'games_received': -1}, {'games_received': 10.0},
    {'predictions_created': True}, {'predictions_created': -1}, {'predictions_created': 7.0},
    {'games_skipped': True}, {'games_skipped': -1}, {'games_skipped': 3.0},
    {'games_received': 9},
    {'outcome': 'failed', 'error_message': None}, {'outcome': 'failed', 'error_message': ''},
    {'outcome': 'failed', 'error_message': 'x' * 1001}, {'outcome': 'failed', 'error_message': 1},
    {'outcome': 'failed', 'error_message': '   '}, {'error_message': 'unnecessary success reason'},
])
def test_completion_malformed_counts_status_or_failure_reason_refuses_before_connection(receipt, changes):
    calls = []
    reader = repository.CertifiedReader(lambda: calls.append('unexpected'), receipt, CUTOFF)
    params = dict(run_id=7, outcome='completed', games_received=10, predictions_created=7,
                  games_skipped=3, error_message=None)
    params.update(changes)
    with pytest.raises(OperatorRefusal):
        reader.finish_run(**params)
    assert calls == []


def test_failed_completion_preserves_bounded_reason(receipt):
    connection = _Connection(None)
    reader = repository.CertifiedReader(lambda: connection, receipt, CUTOFF)
    reader.finish_run(run_id=7, outcome='failed', games_received=10, predictions_created=7,
                      games_skipped=3, error_message='synthetic bounded refusal')
    execute = _selects(connection)[-1]
    assert execute[2][:5] == (receipt.receipt_id, CUTOFF, BODY, 7, 'failed')
    assert execute[2][6] == 'synthetic bounded refusal'
    assert connection.events[-2:] == ['commit', 'close']


@pytest.mark.parametrize('prediction', [None, {}, object(),
                                       _prediction(prediction_time=CUTOFF - timedelta(microseconds=1)),
                                       _prediction(prediction_time=CUTOFF + timedelta(microseconds=1))])
def test_prediction_requires_typed_input_at_original_cutoff_before_connection(receipt, prediction):
    calls = []
    reader = repository.CertifiedReader(lambda: calls.append('unexpected'), receipt, CUTOFF)
    with pytest.raises(OperatorRefusal):
        reader.insert_prediction(prediction)
    assert calls == []


@pytest.mark.parametrize('operation', ['reserve', 'prediction'])
@pytest.mark.parametrize('validated_row', [None, {}, {'receipt': {}},
                                          {'receipt': {'receipt_body_sha256': 'c' * 64}},
                                          {'receipt': {'receipt_body_sha256': None}}, 7])
def test_lifecycle_forged_or_missing_protected_body_refuses_before_effect(receipt, operation, validated_row):
    connection = _Connection(7, validated_row=validated_row)
    reader = repository.CertifiedReader(lambda: connection, receipt, CUTOFF)
    with pytest.raises(OperatorRefusal, match='receipt bytes differ'):
        _lifecycle_call(reader, operation)
    assert _selects(connection) == [('execute', VALIDATE_WRITE_SQL, (receipt.receipt_id, CUTOFF))]
    assert _executes(connection)[:2] == list(TIMEOUT_STATEMENTS)
    assert 'commit' not in connection.events
    assert connection.events[-2:] == ['rollback', 'close']


@pytest.mark.parametrize('profile', ['c' * 64, None])
def test_issuance_wrong_profile_refuses_and_rolls_back_before_commit(profile):
    row = _issuer_row()
    row['schema_capability_profile'] = profile
    connection = _Connection(row)
    with pytest.raises(OperatorRefusal, match='issuance source/profile differs'):
        repository.issue_knowledge(connection_factory=lambda: connection)
    assert _executes(connection) == [*TIMEOUT_STATEMENTS, ('execute', 'SELECT mlb036_private.issue_knowledge()', None)]
    assert 'commit' not in connection.events
    assert connection.events[-2:] == ['rollback', 'close']


@pytest.mark.parametrize('method', [repository.issue_knowledge, repository.inspect_knowledge])
def test_knowledge_profile_load_failure_happens_before_connection(method, monkeypatch):
    calls = []
    def refuse_profile():
        raise OperatorRefusal('synthetic candidate reference refusal')
    monkeypatch.setattr(repository, 'profile_fingerprint', refuse_profile)
    with pytest.raises(OperatorRefusal, match='candidate reference refusal'):
        method(connection_factory=lambda: calls.append('unexpected'))
    assert calls == []


def test_knowledge_inspection_returns_committed_locator_without_issuance_or_commit():
    row = dict(status='CURRENT_COMMITTED_RECEIPT', receipt=_issuer_row(), retry_authorized=False)
    connection = _Connection(row)
    assert repository.inspect_knowledge(connection_factory=lambda: connection) == repository.KnowledgeReceipt(
        1, BODY, AVAILABLE, PROFILE, ENDPOINT)
    assert connection.events[0] == ('session', {'readonly': True, 'isolation_level': 'READ COMMITTED', 'autocommit': False})
    assert _executes(connection) == [*TIMEOUT_STATEMENTS, ('execute', 'SELECT mlb036_private.inspect_knowledge()', None)]
    assert 'commit' not in connection.events
    assert connection.events[-2:] == ['rollback', 'close']


def test_knowledge_absence_is_indeterminate_not_rollback_or_retry_permission():
    row = dict(status='INDETERMINATE_NO_CURRENT_COMMITTED_RECEIPT',
               retry_authorized=False, rollback_proven=False)
    connection = _Connection(row)
    assert repository.inspect_knowledge(connection_factory=lambda: connection) == row
    assert _selects(connection) == [('execute', 'SELECT mlb036_private.inspect_knowledge()', None)]
    assert 'commit' not in connection.events
    assert connection.events[-2:] == ['rollback', 'close']


@pytest.mark.parametrize('row', [
    {'status': 'ROLLED_BACK'}, {},
    {'status': 'CURRENT_COMMITTED_RECEIPT', 'receipt': dict(_issuer_row(), schema_capability_profile='c' * 64)},
    {'status': 'CURRENT_COMMITTED_RECEIPT', 'receipt': {}},
])
def test_knowledge_inspection_unknown_status_or_profile_refuses(row):
    connection = _Connection(row)
    with pytest.raises(OperatorRefusal, match='inspected receipt/profile differs'):
        repository.inspect_knowledge(connection_factory=lambda: connection)
    assert 'commit' not in connection.events
    assert connection.events[-2:] == ['rollback', 'close']


def test_knowledge_inspection_cleanup_closes_after_rollback_failure():
    connection = _Connection({'status': 'INDETERMINATE_NO_CURRENT_COMMITTED_RECEIPT',
                              'retry_authorized': False, 'rollback_proven': False},
                             rollback_error=RuntimeError('synthetic cleanup failure'))
    with pytest.raises(RuntimeError, match='synthetic cleanup failure'):
        repository.inspect_knowledge(connection_factory=lambda: connection)
    assert connection.events[-2:] == ['rollback', 'close']


@pytest.mark.parametrize('operation', [None, {'request_sha256': BODY, 'post_state_current': True}])
def test_correction_inspection_is_readonly_and_never_authorizes_retry(operation, monkeypatch):
    from sportsmodel.operations import mlb_canonical_time_arbitration as arbitration
    guard = {'synthetic': 'verified metadata'}
    monkeypatch.setattr(arbitration, 'verify_target', lambda *a, **k: guard)
    connection = _Connection({'operation': operation})
    result = arbitration.inspect_arbitration(request_sha256=BODY, target=object(), connection_factory=lambda: connection)
    assert result['status'] == ('INDETERMINATE_NO_COMMITTED_RECEIPT' if operation is None else 'COMMITTED_APPLIED')
    assert result['retry_authorized'] is False
    assert result['label'] == 'RAW_FORENSIC' and result['historically_certified'] is False
    if operation is None:
        assert result['rollback_proven'] is False
    else:
        assert result['operation'] == operation
    assert connection.events[0] == ('session', {'readonly': True, 'isolation_level': 'REPEATABLE READ', 'autocommit': False})
    assert _selects(connection) == [('execute', 'SELECT mlb036_private.operator_state()', None)]
    assert 'commit' not in connection.events
    assert connection.events[-2:] == ['rollback', 'close']


@pytest.mark.parametrize('operation', [
    {'request_sha256': 'c' * 64, 'post_state_current': True},
    {'request_sha256': BODY, 'post_state_current': False},
])
def test_correction_inspection_wrong_request_or_poststate_refuses(operation, monkeypatch):
    from sportsmodel.operations import mlb_canonical_time_arbitration as arbitration
    monkeypatch.setattr(arbitration, 'verify_target', lambda *a, **k: {'synthetic': 'verified'})
    connection = _Connection({'operation': operation})
    with pytest.raises(OperatorRefusal, match='Operation identity/post-state differs; no retry'):
        arbitration.inspect_arbitration(request_sha256=BODY, target=object(), connection_factory=lambda: connection)
    assert 'commit' not in connection.events
    assert connection.events[-2:] == ['rollback', 'close']


@pytest.mark.parametrize('request_hash', ['', 'B' * 64, 'b' * 63, None])
def test_correction_inspection_malformed_hash_never_opens_connection(request_hash):
    from sportsmodel.operations import mlb_canonical_time_arbitration as arbitration
    calls = []
    with pytest.raises(OperatorRefusal, match='Exact operation request hash required'):
        arbitration.inspect_arbitration(request_sha256=request_hash, target=object(),
                                       connection_factory=lambda: calls.append('unexpected'))
    assert calls == []
