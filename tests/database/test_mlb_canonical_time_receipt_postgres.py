"""Actual committed-knowledge lifecycle leaves, positively isolated and rolled back."""
import json
import threading
import time
import psycopg2
import pytest
from tests.database.test_mlb_canonical_time_postgres import (
    ENABLED, TARGETS, prepared_case, committed_proof,
)
from tests.database.test_mlb_canonical_time_admission_postgres import exact_admission

pytestmark=pytest.mark.skipif(ENABLED not in TARGETS,
    reason='requires integration-owner prepared arbitration210 PG16 fixture')


def full_retained_state(case):
    return case.rows('SELECT mlb036_private.business_snapshot(),mlb036_private.state(),'
        '(SELECT to_jsonb(a) FROM mlb036_private.authority a),'
        "(SELECT coalesce(jsonb_agg(to_jsonb(r) ORDER BY receipt_id),'[]'::jsonb) FROM mlb036_private.knowledge_receipts r),"
        "(SELECT coalesce(jsonb_agg(to_jsonb(r) ORDER BY moneyline_prediction_run_id),'[]'::jsonb) FROM public.moneyline_prediction_runs r)")


@pytest.mark.parametrize('scope',['top_level','savepoint'])
def test_N01_actual_own_X_is_not_issuance_authority_and_stamps_top_xid(
        prepared_case,exact_admission,scope):
    before=full_retained_state(prepared_case)
    try:
        with prepared_case.session(isolation='SERIALIZABLE') as connection:
            connection.rollback();connection.set_session(readonly=False,isolation_level='SERIALIZABLE')
            with connection.cursor() as cur:
                cur.execute('SELECT pg_current_xact_id()::text');top=cur.fetchone()[0]
                if scope=='savepoint':cur.execute('SAVEPOINT correction_child')
                cur.execute('SET SESSION AUTHORIZATION arbitration210_operator')
                cur.execute('SELECT mlb036_private.acquire_exact_gate()')
                cur.execute('SELECT mlb036_private.operator_state()');state=cur.fetchone()[0]
                cur.execute('SELECT mlb036_private.correct_exact(%s::jsonb,%s::jsonb,%s)',
                    (json.dumps(exact_admission['db_request']),json.dumps(state),exact_admission['preview_sha256']))
                assert cur.fetchone()[0]['status']=='APPLIED'
                cur.execute('SET CONSTRAINTS ALL IMMEDIATE')
                cur.execute('RESET SESSION AUTHORIZATION')
                cur.execute('SELECT writer_xid8::text FROM mlb036_private.arbitrations')
                assert cur.fetchall()==[(top,)]
                cur.execute('SELECT writer_xid8::text FROM mlb036_private.arbitration_events')
                assert cur.fetchall()==[(top,)]
                cur.execute('SET SESSION AUTHORIZATION arbitration210_knowledge')
                # Legal X is SERIALIZABLE; Y requires a distinct RC transaction.
                # Preserve that earlier refusal, not claim an unreachable later branch.
                with pytest.raises(psycopg2.Error,match='certified RC transaction required') as refused:
                    cur.execute('SELECT mlb036_private.issue_knowledge()')
                assert refused.value.pgcode=='P0001'
    finally:
        assert full_retained_state(prepared_case)==before


@pytest.mark.parametrize('scope',['top_level','savepoint'])
@pytest.mark.parametrize('consumer',['validate','certified_data','reserve_run'])
def test_N02_own_uncommitted_Y_cannot_admit_read_or_run(prepared_case,committed_proof,scope,consumer):
    before=full_retained_state(prepared_case)
    original_receipt,_=committed_proof
    try:
        with prepared_case.session() as connection:
            connection.rollback();connection.set_session(readonly=False,isolation_level='READ COMMITTED')
            with connection.cursor() as cur:
                cur.execute('SELECT pg_current_xact_id()::text');top=cur.fetchone()[0]
                if scope=='savepoint':cur.execute('SAVEPOINT issuance_child')
                # Trusted rollback-only fixture drift gives Y a new observed state.
                # No audit, receipt, time or availability row is directly fabricated.
                cur.execute('UPDATE public.mlb_identity_topology_fence SET epoch=epoch+1 WHERE singleton')
                cur.execute('SET SESSION AUTHORIZATION arbitration210_knowledge')
                cur.execute('SELECT mlb036_private.issue_knowledge()');provisional=cur.fetchone()[0]
                assert provisional['receipt_id']!=original_receipt['receipt_id']
                assert provisional['issuer_xid8']==top
                cur.execute('SELECT clock_timestamp()');cutoff=cur.fetchone()[0]
                cur.execute('SET SESSION AUTHORIZATION arbitration210_reader')
                request=dict(target_date='2026-10-13',run_type='preview',model_version='SYNTHETIC_NO_MODEL',
                    feature_schema_version='SYNTHETIC',model_artifact_sha256='0'*64,model_training_cutoff=None)
                if consumer=='validate':
                    statement='SELECT mlb036_private.validate_knowledge(%s,%s,false)'
                    args=(provisional['receipt_id'],cutoff)
                    reason='committed other-transaction receipt required'
                elif consumer=='reserve_run':
                    statement='SELECT mlb036_private.reserve_run(%s,%s,%s::jsonb)'
                    args=(provisional['receipt_id'],cutoff,json.dumps(request))
                    reason='committed other-transaction receipt required'
                else:
                    statement="SELECT mlb036_private.certified_data(%s,%s,'game','{\"id\":26}')"
                    args=(provisional['receipt_id'],cutoff)
                    # A same-transaction Y write cannot satisfy read-only Z first.
                    # Do not claim the later own-XID branch executed in this path.
                    reason='certified RC transaction required'
                with pytest.raises(psycopg2.Error,match=reason) as refused:
                    cur.execute(statement,args)
                assert refused.value.pgcode=='P0001'
    finally:
        assert full_retained_state(prepared_case)==before


@pytest.mark.parametrize('scope',['top_level','savepoint'])
def test_N03_other_session_cannot_see_provisional_Y_or_rolled_back_locator(
        prepared_case,committed_proof,scope):
    before=full_retained_state(prepared_case)
    try:
        with prepared_case.session() as connection:
            connection.rollback();connection.set_session(readonly=False,isolation_level='READ COMMITTED')
            with connection.cursor() as cur:
                if scope=='savepoint':cur.execute('SAVEPOINT issuance_child')
                cur.execute('UPDATE public.mlb_identity_topology_fence SET epoch=epoch+1 WHERE singleton')
                cur.execute('SET SESSION AUTHORIZATION arbitration210_knowledge')
                cur.execute('SELECT mlb036_private.issue_knowledge()');provisional=cur.fetchone()[0]
                assert provisional['receipt_id']!=committed_proof[0]['receipt_id']
                prepared_case.denial('SELECT mlb036_private.validate_knowledge(%s,clock_timestamp())',
                    (provisional['receipt_id'],),message='committed receipt required',sqlstates={'P0001'})
                # The committed old state/proof remains coherent to the other session.
                packet=prepared_case.rows('SELECT mlb036_private.validate_knowledge(%s,clock_timestamp())',
                    (committed_proof[0]['receipt_id'],),principal='reader')[0][0]
                assert packet['receipt']['receipt_id']==committed_proof[0]['receipt_id']
        prepared_case.denial('SELECT mlb036_private.validate_knowledge(%s,clock_timestamp())',
            (provisional['receipt_id'],),message='committed receipt required',sqlstates={'P0001'})
    finally:
        assert full_retained_state(prepared_case)==before


def test_N13_exact_committed_state_reuse_does_not_mutate_clock_or_business(
        prepared_case,committed_proof):
    before=full_retained_state(prepared_case)
    with prepared_case.session('knowledge') as connection:
        connection.rollback();connection.set_session(readonly=False,isolation_level='READ COMMITTED')
        with connection.cursor() as cur:
            cur.execute('SELECT mlb036_private.issue_knowledge()');first=cur.fetchone()[0]
            cur.execute('SELECT mlb036_private.issue_knowledge()');second=cur.fetchone()[0]
            assert first==second==committed_proof[0]
    assert full_retained_state(prepared_case)==before


def test_N13_concurrent_exact_state_issuers_serialize_without_business_mutation(
        prepared_case, committed_proof):
    """Prove the clock-row wait in pg_stat_activity, not from an elapsed sleep."""
    before = full_retained_state(prepared_case)
    ready = threading.Event()
    outcome = {}

    def issue_second():
        try:
            with prepared_case.session('knowledge') as connection:
                connection.rollback()
                connection.set_session(readonly=False, isolation_level='READ COMMITTED')
                with connection.cursor() as cursor:
                    cursor.execute('SELECT pg_backend_pid()')
                    outcome['pid'] = cursor.fetchone()[0]
                    ready.set()
                    cursor.execute('SELECT mlb036_private.issue_knowledge()')
                    outcome['receipt'] = cursor.fetchone()[0]
        except BaseException as error:
            outcome['error'] = error
            ready.set()

    worker = threading.Thread(target=issue_second)
    try:
        with prepared_case.session('knowledge') as first:
            first.rollback()
            first.set_session(readonly=False, isolation_level='READ COMMITTED')
            with first.cursor() as cursor:
                cursor.execute('SELECT pg_backend_pid()')
                first_pid = cursor.fetchone()[0]
                cursor.execute('SELECT mlb036_private.issue_knowledge()')
                assert cursor.fetchone()[0] == committed_proof[0]
                worker.start()
                assert ready.wait(2) and 'error' not in outcome
                deadline = time.monotonic() + 1
                barrier = None
                while time.monotonic() < deadline:
                    rows = prepared_case.rows(
                        'SELECT wait_event_type,pg_blocking_pids(pid) FROM pg_stat_activity WHERE pid=%s',
                        (outcome['pid'],))
                    if rows and rows[0][0] == 'Lock' and first_pid in rows[0][1]:
                        barrier = rows[0]
                        break
                    time.sleep(.01)
                assert barrier is not None, 'Concurrent issuer never reached a server-proven clock-row wait'
            first.rollback()
        worker.join(3)
        assert not worker.is_alive() and 'error' not in outcome, repr(outcome.get('error'))
        assert outcome['receipt'] == committed_proof[0]
    finally:
        if worker.ident is not None:
            worker.join(3)
        assert full_retained_state(prepared_case) == before
