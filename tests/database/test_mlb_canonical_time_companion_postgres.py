"""Actual N16 immutable036 companion/input leaves, synthetic and rollback-only.

Historical NULL/v1/v2 upgrade preservation is intentionally not fabricated here.
No model runs, predictions, receipts, commits or trigger bypasses are performed.
"""
from contextlib import contextmanager
from copy import deepcopy
from datetime import date, datetime, timedelta
import json

import psycopg2
from psycopg2 import sql
import pytest

from tests.database.test_mlb_canonical_time_postgres import (
    ENABLED, TARGETS, prepared_case, committed_proof,
)
from tests.database.test_mlb_canonical_time_subject_admission_postgres import full_retained_state

pytestmark = pytest.mark.skipif(
    ENABLED not in TARGETS,
    reason='requires integration-owner prepared committed-X/Y arbitration210 fixture',
)

COMPANION_FIELDS = (
    'version', 'receipt_id', 'receipt_body_sha256', 'correction_state_fingerprint',
    'identity034_digest', 'identity035_digest', 'identity_topology_epoch',
    'available_at', 'cutoff_time', 'deployment_id', 'authority_epoch',
    'system_identifier', 'database_oid', 'database_name', 'server_address',
    'server_port', 'postmaster_started_at', 'schema_capability_profile',
    'correction_policy_version', 'target_date', 'target_state',
)
HASH_FIELDS = {
    'receipt_body_sha256', 'correction_state_fingerprint', 'identity034_digest',
    'identity035_digest', 'schema_capability_profile',
}
TIMESTAMP_FIELDS = {'available_at', 'cutoff_time', 'postmaster_started_at'}
INPUT_FIELDS = (
    'target_date', 'run_type', 'model_version', 'feature_schema_version',
    'model_artifact_sha256', 'model_training_cutoff', 'started_at',
)


@contextmanager
def admitted_empty_run(case, committed):
    before = full_retained_state(case)
    receipt, cutoff = committed
    try:
        with case.session() as connection:
            connection.rollback()
            connection.set_session(readonly=False, isolation_level='READ COMMITTED')
            with connection.cursor() as cursor:
                cursor.execute("SELECT (%s::timestamptz AT TIME ZONE 'America/Los_Angeles')::date+31", (cutoff,))
                target = cursor.fetchone()[0]
                cursor.execute("SELECT count(*) FROM public.games WHERE (game_date AT TIME ZONE 'America/Los_Angeles')::date=%s", (target,))
                assert cursor.fetchone() == (0,), 'This control requires an actually empty slate'
                cursor.execute('SET SESSION AUTHORIZATION arbitration210_reader')
                request = dict(target_date=target.isoformat(), run_type='preview',
                    model_version='SYNTHETIC_NO_MODEL', feature_schema_version='SYNTHETIC',
                    model_artifact_sha256='0' * 64, model_training_cutoff=None)
                cursor.execute('SELECT mlb036_private.reserve_run(%s,%s,%s::jsonb)',
                    (receipt['receipt_id'], cutoff, json.dumps(request)))
                run_id = cursor.fetchone()[0]
                assert type(run_id) is int and run_id > 0
                cursor.execute('RESET SESSION AUTHORIZATION')
                cursor.execute('SELECT to_jsonb(r) FROM public.moneyline_prediction_runs r '
                               'WHERE moneyline_prediction_run_id=%s', (run_id,))
                admitted = cursor.fetchone()[0]
                companion = admitted['canonical_time_knowledge']
                assert set(companion) == set(COMPANION_FIELDS)
                assert companion['target_state'] == []
                assert companion['receipt_id'] == receipt['receipt_id']
                assert datetime.fromisoformat(companion['cutoff_time']) == cutoff
                cursor.execute('SELECT count(*) FROM public.moneyline_game_predictions '
                               'WHERE moneyline_prediction_run_id=%s', (run_id,))
                assert cursor.fetchone() == (0,)
                yield cursor, run_id, admitted, cutoff
                cursor.execute('SET CONSTRAINTS ALL IMMEDIATE')
    finally:
        assert full_retained_state(case) == before


def wrong_companion_value(field, value):
    if field in HASH_FIELDS:
        return 'f' * 64 if value != 'f' * 64 else '0' * 64
    if field in TIMESTAMP_FIELDS:
        return (datetime.fromisoformat(value) + timedelta(seconds=1)).isoformat()
    if field == 'target_date':
        return (date.fromisoformat(value) + timedelta(days=1)).isoformat()
    if field == 'target_state':
        assert value == []
        return [{'SYNTHETIC_UNBOUND_TARGET': True}]
    if field == 'deployment_id':
        result = '00000000-0000-0000-0000-000000000001'
        assert value != result
        return result
    if field == 'system_identifier':
        return str(int(value) + 1)
    if field == 'database_oid':
        assert type(value) in (str, int)
        return str(int(value) + 1) if type(value) is str else value + 1
    if field == 'database_name':
        return 'sportsmodel_test_SYNTHETIC_CHANGED'
    if field == 'server_address':
        result = '127.0.0.2'
        assert value != result
        return result
    if field == 'correction_policy_version':
        return '9.9.9'
    assert field in {'version', 'receipt_id', 'identity_topology_epoch', 'authority_epoch',
                     'server_port'}
    assert type(value) is int
    return value + 1


def refuse_and_verify_original(cursor, run_id, admitted, statement, args, message):
    cursor.execute('SAVEPOINT immutable_companion_attempt')
    with pytest.raises(psycopg2.Error) as refused:
        cursor.execute(statement, args)
    assert refused.value.pgcode == 'P0001'
    assert refused.value.diag.message_primary == message
    cursor.execute('ROLLBACK TO SAVEPOINT immutable_companion_attempt')
    cursor.execute('SELECT to_jsonb(r) FROM public.moneyline_prediction_runs r '
                   'WHERE moneyline_prediction_run_id=%s', (run_id,))
    assert cursor.fetchone()[0] == admitted
    cursor.execute('SELECT count(*) FROM public.moneyline_game_predictions '
                   'WHERE moneyline_prediction_run_id=%s', (run_id,))
    assert cursor.fetchone() == (0,)


@pytest.mark.parametrize('field', COMPANION_FIELDS)
@pytest.mark.parametrize('change', ['wrong_value', 'null', 'remove'])
def test_N16_each_server_companion_field_is_immutable(
        prepared_case, committed_proof, field, change):
    with admitted_empty_run(prepared_case, committed_proof) as (cursor, run_id, admitted, _):
        altered = deepcopy(admitted['canonical_time_knowledge'])
        if change == 'wrong_value':
            altered[field] = wrong_companion_value(field, altered[field])
        elif change == 'null':
            altered[field] = None
        else:
            assert change == 'remove'
            del altered[field]
        assert altered != admitted['canonical_time_knowledge']
        refuse_and_verify_original(cursor, run_id, admitted,
            'UPDATE public.moneyline_prediction_runs SET canonical_time_knowledge=%s::jsonb '
            'WHERE moneyline_prediction_run_id=%s', (json.dumps(altered), run_id),
            '036 immutable run companion; no backfill')


@pytest.mark.parametrize('change', ['extra_field', 'whole_sql_null'])
def test_N16_extra_companion_field_or_removal_of_entire_companion_refuses(
        prepared_case, committed_proof, change):
    with admitted_empty_run(prepared_case, committed_proof) as (cursor, run_id, admitted, _):
        if change == 'extra_field':
            altered = deepcopy(admitted['canonical_time_knowledge'])
            altered['SYNTHETIC_EXTRA_FIELD'] = True
            statement = 'UPDATE public.moneyline_prediction_runs SET canonical_time_knowledge=%s::jsonb WHERE moneyline_prediction_run_id=%s'
            args = (json.dumps(altered), run_id)
        else:
            assert change == 'whole_sql_null'
            statement = 'UPDATE public.moneyline_prediction_runs SET canonical_time_knowledge=NULL WHERE moneyline_prediction_run_id=%s'
            args = (run_id,)
        refuse_and_verify_original(cursor, run_id, admitted, statement, args,
                                   '036 immutable run companion; no backfill')


@pytest.mark.parametrize('field', INPUT_FIELDS)
def test_N16_certified_run_inputs_cannot_be_rewritten(
        prepared_case, committed_proof, field):
    with admitted_empty_run(prepared_case, committed_proof) as (cursor, run_id, admitted, cutoff):
        if field == 'target_date':
            changed = date.fromisoformat(admitted[field]) + timedelta(days=1)
        elif field == 'run_type':
            assert admitted[field] == 'preview'
            changed = 'official'
        elif field == 'model_artifact_sha256':
            changed = 'f' * 64
        elif field == 'model_training_cutoff':
            assert admitted[field] is None
            changed = cutoff - timedelta(days=1)
        elif field == 'started_at':
            changed = datetime.fromisoformat(admitted[field]) + timedelta(seconds=1)
        else:
            assert field in ('model_version', 'feature_schema_version')
            changed = admitted[field] + '_MUTATED'
        statement = sql.SQL('UPDATE public.moneyline_prediction_runs SET {}=%s '
                            'WHERE moneyline_prediction_run_id=%s').format(sql.Identifier(field))
        refuse_and_verify_original(cursor, run_id, admitted, statement, (changed, run_id),
                                   '036 immutable certified run inputs')
