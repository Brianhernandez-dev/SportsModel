"""Actual N10 current-clock-behind-protected-high-water rollback controls.

Trusted fixture advances only the private high-water inside a transaction. It
does not set the OS/host clock, rewrite audits, fabricate a receipt, disable a
guard or commit altered authority. Production and external providers are unused.
"""
import json

import psycopg2
import pytest

from tests.database.test_mlb_canonical_time_postgres import ENABLED, TARGETS, prepared_case, committed_proof
from tests.database.test_mlb_canonical_time_receipt_postgres import full_retained_state

pytestmark = pytest.mark.skipif(ENABLED not in TARGETS,
    reason='requires integration-owner prepared committed-X/Y isolated fixture')


@pytest.mark.parametrize('consumer', ['issuer', 'certified_read', 'validate_for_write', 'reserve_run'])
def test_N10_current_clock_behind_stored_high_water_refuses_before_effects(prepared_case, committed_proof, consumer):
    before = full_retained_state(prepared_case)
    count_sql = ('SELECT (SELECT count(*) FROM mlb036_private.knowledge_receipts),'
        '(SELECT count(*) FROM public.moneyline_prediction_runs),'
        '(SELECT count(*) FROM public.moneyline_game_predictions)')
    original_counts = prepared_case.rows(count_sql)[0]
    predictions_before = prepared_case.rows('SELECT to_jsonb(p)::text FROM public.moneyline_game_predictions p ORDER BY moneyline_game_prediction_id')
    receipt, cutoff = committed_proof
    try:
        with prepared_case.session() as connection:
            connection.rollback()
            connection.set_session(readonly=False, isolation_level='READ COMMITTED')
            with connection.cursor() as cursor:
                cursor.execute("UPDATE mlb036_private.authority SET observed_high_water=clock_timestamp()+interval'1 day' WHERE singleton")
                assert cursor.rowcount == 1
                cursor.execute('SELECT observed_high_water>clock_timestamp() FROM mlb036_private.authority')
                assert cursor.fetchone() == (True,)
                cursor.execute('SAVEPOINT clock_comparison_refusal')
                if consumer == 'certified_read':
                    # Read-only mode may be strengthened in this trusted fixture
                    # transaction; the actual restricted Z SQL still checks it.
                    cursor.execute('SET LOCAL transaction_read_only=on')
                    cursor.execute('SHOW transaction_read_only')
                    assert cursor.fetchone() == ('on',)
                cursor.execute('SET SESSION AUTHORIZATION '+('arbitration210_knowledge' if consumer == 'issuer' else 'arbitration210_reader'))
                with pytest.raises(psycopg2.Error) as refused:
                    if consumer == 'issuer':
                        cursor.execute('SELECT mlb036_private.issue_knowledge()')
                    elif consumer == 'certified_read':
                        cursor.execute("SELECT mlb036_private.certified_data(%s,%s,'game','{\"id\":26}')", (receipt['receipt_id'], cutoff))
                    elif consumer == 'validate_for_write':
                        cursor.execute('SELECT mlb036_private.validate_knowledge(%s,%s,false)', (receipt['receipt_id'], cutoff))
                    else:
                        request = dict(target_date='2026-11-30', run_type='preview', model_version='SYNTHETIC_NO_MODEL',
                            feature_schema_version='SYNTHETIC', model_artifact_sha256='0'*64, model_training_cutoff=None)
                        cursor.execute('SELECT mlb036_private.reserve_run(%s,%s,%s::jsonb)', (receipt['receipt_id'], cutoff, json.dumps(request)))
                assert refused.value.pgcode == 'P0001'
                assert refused.value.diag.message_primary == '036 authority/clock/capability drift'
                cursor.execute('ROLLBACK TO SAVEPOINT clock_comparison_refusal')
                cursor.execute('RESET SESSION AUTHORIZATION')
                cursor.execute(count_sql)
                counts = cursor.fetchone()
                assert counts == original_counts
    finally:
        assert full_retained_state(prepared_case) == before
        assert prepared_case.rows('SELECT to_jsonb(p)::text FROM public.moneyline_game_predictions p ORDER BY moneyline_game_prediction_id') == predictions_before
