"""Actual committed-X replay/inspection leaves; no simulated lost-ACK claim.

The integration owner supplies the unchanged prepared request/evidence/preview.
All database reads are real; a counting connection refuses any attempted commit.
"""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import json
import os

import psycopg2
import pytest

from sportsmodel.database.mlb_canonical_time_repository import OperatorTarget
from sportsmodel.database.mlb_operator_guard import OperatorRefusal, canonical_json, digest
from sportsmodel.operations import mlb_canonical_time_arbitration as operator
from tests.database.test_mlb_canonical_time_postgres import (
    DATABASE, ENABLED, TARGETS, prepared_case,
)
from tests.database.test_mlb_canonical_time_subject_admission_postgres import full_retained_state

pytestmark = pytest.mark.skipif(
    ENABLED not in TARGETS,
    reason='requires integration-owner prepared committed-X arbitration210 fixture',
)


class CountingConnection:
    """Delegate actual PostgreSQL operations; never allow this refusal test to commit."""
    def __init__(self, connection):
        self.connection = connection
        self.commit_calls = self.rollback_calls = self.close_calls = 0
        self.sessions = []

    def __getattr__(self, name):
        return getattr(self.connection, name)

    def set_session(self, *args, **kwargs):
        self.sessions.append(dict(kwargs))
        return self.connection.set_session(*args, **kwargs)

    def commit(self):
        self.commit_calls += 1
        raise AssertionError('Replay/inspection must never attempt commit')

    def rollback(self):
        self.rollback_calls += 1
        return self.connection.rollback()

    def close(self):
        self.close_calls += 1
        return self.connection.close()


@pytest.fixture
def replay_case(prepared_case):
    root = Path(os.environ['SPORTSMODEL_ARBITRATION_CASE_BYTES'])
    assert root.name == 'CASE_BYTES_' + ENABLED.rsplit('-', 1)[-1].upper()
    assert root.is_dir() and not root.is_symlink()
    paths = [root / name for name in ('REQUEST.json', 'SYNTHETIC_EVIDENCE.zip', 'PREVIEW.json')]
    raw, evidence, preview_bytes = [path.read_bytes() for path in paths]
    hashes = [sha256(value).hexdigest() for value in (raw, evidence, preview_bytes)]
    preview = json.loads(preview_bytes)
    identity = prepared_case.rows('SELECT host(inet_server_addr()),inet_server_port(),'
        'pg_postmaster_start_time(),(pg_control_system()).system_identifier::text')[0]
    target = OperatorTarget(host='127.0.0.1', port=prepared_case.port, database=DATABASE,
        server_address=identity[0], server_port=identity[1],
        postmaster_started_at=identity[2].isoformat(), identity_kind='isolated',
        system_identifier=identity[3])
    request, db_request = operator.validate_request(raw, evidence, target)
    assert preview['request'] == request and preview['db_request'] == db_request
    assert preview['preview_sha256'] == digest({k: v for k, v in preview.items() if k != 'preview_sha256'})
    retained = full_retained_state(prepared_case)
    audits = retained['protected']['audits']
    assert len(audits) == 1
    audit = audits[0]
    assert audit['request_sha256'] == hashes[0]
    assert audit['approval_sha256'] == preview['preview_sha256']
    connections = []

    def factory():
        connection = CountingConnection(psycopg2.connect(
            host='127.0.0.1', port=prepared_case.port, dbname=DATABASE,
            user=prepared_case.roles['operator'], password=prepared_case._password,
            connect_timeout=5, options='-c lock_timeout=1500ms -c statement_timeout=15000ms'))
        connections.append(connection)
        return connection

    capsule = dict(case=prepared_case, raw=raw, evidence=evidence, preview=preview,
                   target=target, factory=factory, connections=connections, audit=audit)
    try:
        yield capsule
    finally:
        for connection in connections:
            assert connection.commit_calls == 0
            assert connection.rollback_calls >= 1
            assert connection.close_calls == 1
            assert connection.connection.closed
        assert full_retained_state(prepared_case) == retained
        assert [sha256(path.read_bytes()).hexdigest() for path in paths] == hashes


def execute(capsule, *, raw=None, preview=None, approval=None):
    selected_preview = capsule['preview'] if preview is None else preview
    return operator.execute_arbitration(
        request_bytes=capsule['raw'] if raw is None else raw,
        evidence_bytes=capsule['evidence'], target=capsule['target'],
        connection_factory=capsule['factory'], preview=selected_preview,
        approved_preview_sha256=selected_preview['preview_sha256'] if approval is None else approval,
        acknowledge_writes=True)


def test_T31_actual_exact_committed_replay_refuses_without_commit(replay_case):
    with pytest.raises(OperatorRefusal, match='^ALREADY_APPLIED_REFUSAL$'):
        execute(replay_case)
    connections = replay_case['connections']
    assert len(connections) == 2
    assert connections[0].sessions == [dict(readonly=False, isolation_level='SERIALIZABLE', autocommit=False)]
    assert connections[1].sessions == [dict(readonly=True, isolation_level='READ COMMITTED', autocommit=False)]


def test_T31_actual_committed_receipt_inspection_is_read_only(replay_case):
    observed = operator.inspect_arbitration(
        request_sha256=sha256(replay_case['raw']).hexdigest(), target=replay_case['target'],
        connection_factory=replay_case['factory'])
    assert observed['status'] == 'COMMITTED_APPLIED'
    assert observed['retry_authorized'] is False and observed['historically_certified'] is False
    assert observed['label'] == 'RAW_FORENSIC'
    operation = observed['operation']
    assert operation['audit_id'] == replay_case['audit']['audit_id']
    assert operation['request_sha256'] == sha256(replay_case['raw']).hexdigest()
    assert operation['approval_sha256'] == replay_case['preview']['preview_sha256']
    assert operation['post_state_current'] is True
    events = full_retained_state(replay_case['case'])['protected']['events']
    assert len(events) == 1 and events[0]['audit_reference'] == operation['audit_id']
    assert operation['receipt'] == events[0]['operation_receipt']
    assert len(replay_case['connections']) == 1
    assert replay_case['connections'][0].sessions == [
        dict(readonly=True, isolation_level='REPEATABLE READ', autocommit=False)]


@pytest.mark.parametrize('changed', ['request_bytes', 'approval'])
def test_T32_preparse_replay_byte_or_approval_change_opens_no_connection(replay_case, changed):
    kwargs = {'raw': replay_case['raw'] + b'\n'} if changed == 'request_bytes' else {'approval': 'f' * 64}
    with pytest.raises(OperatorRefusal, match='^Exact request/evidence/preview byte identity required$'):
        execute(replay_case, **kwargs)
    assert replay_case['connections'] == []


@pytest.mark.parametrize('changed', ['request_identity', 'approval_identity'])
def test_T32_actual_committed_identity_mismatch_refuses_no_replay(replay_case, changed):
    preview = deepcopy(replay_case['preview'])
    raw = replay_case['raw']
    if changed == 'request_identity':
        request = deepcopy(preview['request'])
        request['operator_identity'] = 'SYNTHETIC_ONLY_CHANGED_REPLAY_IDENTITY'
        raw = canonical_json(request).encode('utf-8')
        request, db_request = operator.validate_request(raw, replay_case['evidence'], replay_case['target'])
        preview.update(request=request, db_request=db_request, request_sha256=sha256(raw).hexdigest())
    else:
        # Change only the purported approved preview identity. This is not a new
        # authorized operation; the committed audit must reject its new digest.
        preview['state']['SYNTHETIC_CHANGED_APPROVAL'] = True
    preview['preview_sha256'] = digest({k: v for k, v in preview.items() if k != 'preview_sha256'})
    assert preview['preview_sha256'] != replay_case['preview']['preview_sha256']
    with pytest.raises(OperatorRefusal, match='^Applied operation request/approval/post-state mismatch; no replay$'):
        execute(replay_case, raw=raw, preview=preview)
    assert len(replay_case['connections']) == 2


def test_T32_actual_receipt_inspection_wrong_request_refuses(replay_case):
    wrong = '0' * 64
    assert wrong != replay_case['audit']['request_sha256']
    with pytest.raises(OperatorRefusal, match='^Operation identity/post-state differs; no retry$'):
        operator.inspect_arbitration(request_sha256=wrong, target=replay_case['target'],
                                    connection_factory=replay_case['factory'])
    assert len(replay_case['connections']) == 1
