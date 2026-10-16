"""Actual deferred036 business-preservation leaves, always rolled back.

These protected SQL tests do not claim public operator approval or fault-injected
network recovery. The original request/evidence capsule is never rewritten.
"""
import json

import psycopg2
import pytest

from tests.database.test_mlb_canonical_time_postgres import ENABLED, TARGETS, prepared_case
from tests.database.test_mlb_canonical_time_admission_postgres import exact_admission
from tests.database.test_mlb_canonical_time_subject_admission_postgres import (
    clone_row, full_retained_state, PROVENANCE_COLUMNS,
)

pytestmark = pytest.mark.skipif(
    ENABLED not in TARGETS,
    reason='requires integration-owner prepared isolated pre-X arbitration210 fixture',
)


def prepare_mutable_market(cursor, *, first_response=False):
    """Never alter an028 immutable quote or an already-known provider response.

    The setup is ordinary synthetic data within this same rollback transaction.
    It precedes X and is part of X's independently captured business snapshot.
    """
    changes = {name: None for name in PROVENANCE_COLUMNS}
    if first_response:
        cursor.execute('INSERT INTO public.odds_ingestion_runs('
            'sport,source_name,status,snapshot_role,request_path,request_regions,'
            'request_markets,request_odds_format,request_started_at) '
            "VALUES('baseball_mlb','odds_api','running','legacy',"
            "'/SYNTHETIC_OFFLINE_ONLY','us','h2h','american',clock_timestamp()) "
            'RETURNING odds_ingestion_run_id')
        run = cursor.fetchone()[0]
        changes['odds_ingestion_run_id'] = run
    else:
        run = None
    quote = clone_row(cursor, 'odds_market_snapshots', changes)
    return quote, run


@pytest.mark.parametrize('case', [
    'market_price', 'market_line', 'market_availability',
    'team_metric', 'pitching_metric', 'result_score', 'first_ingestion_response',
])
def test_T_atomicity_deferred_constraint_refuses_post_X_business_drift(
        prepared_case, exact_admission, case):
    before = full_retained_state(prepared_case)
    try:
        with prepared_case.session(isolation='SERIALIZABLE') as connection:
            connection.rollback()
            connection.set_session(readonly=False, isolation_level='SERIALIZABLE')
            with connection.cursor() as cursor:
                cursor.execute('SET SESSION AUTHORIZATION arbitration210_operator')
                cursor.execute('SELECT mlb036_private.acquire_exact_gate()')
                cursor.execute('RESET SESSION AUTHORIZATION')
                quote = run = None
                if case.startswith('market_') or case == 'first_ingestion_response':
                    quote, run = prepare_mutable_market(
                        cursor, first_response=case == 'first_ingestion_response')
                cursor.execute('SET SESSION AUTHORIZATION arbitration210_operator')
                cursor.execute('SELECT mlb036_private.operator_state()')
                current = cursor.fetchone()[0]
                cursor.execute('SELECT mlb036_private.correct_exact(%s::jsonb,%s::jsonb,%s)',
                    (json.dumps(exact_admission['db_request']), json.dumps(current),
                     exact_admission['preview_sha256']))
                applied = cursor.fetchone()[0]
                assert applied['status'] == 'APPLIED'
                cursor.execute('RESET SESSION AUTHORIZATION')
                cursor.execute('SELECT count(*) FROM mlb036_private.arbitrations')
                assert cursor.fetchone() == (1,)
                cursor.execute('SELECT count(*) FROM mlb036_private.knowledge_receipts')
                assert cursor.fetchone() == (0,)
                if case == 'market_price':
                    statement = 'UPDATE public.odds_market_snapshots SET price=price+1 WHERE odds_market_snapshot_id=%s'
                    args = (quote,)
                elif case == 'market_line':
                    statement = 'UPDATE public.odds_market_snapshots SET line_value=coalesce(line_value,0)+0.5 WHERE odds_market_snapshot_id=%s'
                    args = (quote,)
                elif case == 'market_availability':
                    statement = "UPDATE public.odds_market_snapshots SET created_at=created_at+interval '1 second' WHERE odds_market_snapshot_id=%s"
                    args = (quote,)
                elif case == 'team_metric':
                    statement = 'UPDATE public.team_game_statistics SET runs=runs+1 WHERE team_game_statistics_id=(SELECT min(team_game_statistics_id) FROM public.team_game_statistics WHERE game_id=26)'
                    args = None
                elif case == 'pitching_metric':
                    statement = 'UPDATE public.player_game_pitching_statistics SET hits_allowed=hits_allowed+1 WHERE player_game_pitching_statistics_id=(SELECT min(player_game_pitching_statistics_id) FROM public.player_game_pitching_statistics WHERE game_id=26)'
                    args = None
                elif case == 'result_score':
                    statement = 'UPDATE public.historical_games SET home_score=home_score+1 WHERE game_id=26'
                    args = None
                else:
                    assert case == 'first_ingestion_response' and run is not None
                    statement = 'UPDATE public.odds_ingestion_runs SET response_received_at=clock_timestamp(),status_code=200 WHERE odds_ingestion_run_id=%s'
                    args = (run,)
                # Setup/mutation errors cannot masquerade as deferred refusal.
                cursor.execute(statement, args)
                assert cursor.rowcount == 1
                with pytest.raises(psycopg2.Error) as refused:
                    cursor.execute('SET CONSTRAINTS ALL IMMEDIATE')
                assert refused.value.pgcode == 'P0001'
                assert refused.value.diag.message_primary in {
                    '036 independent operation post-state completeness',
                    '036 independent framed business preservation',
                }
                print('DEFERRED_ATOMICITY_REFUSAL', case, refused.value.diag.message_primary)
    finally:
        assert full_retained_state(prepared_case) == before


@pytest.mark.parametrize('anchor', [12, 571])
@pytest.mark.parametrize('field', ['game_source_id', 'game_id', 'source_name', 'external_game_id', 'created_at', 'delete'])
def test_inside_X_original_source_anchor_every_field_is_sealed(prepared_case, exact_admission, anchor, field):
    before = full_retained_state(prepared_case)
    try:
        with prepared_case.session(isolation='SERIALIZABLE') as connection:
            connection.rollback()
            connection.set_session(readonly=False, isolation_level='SERIALIZABLE')
            with connection.cursor() as cursor:
                cursor.execute('SET SESSION AUTHORIZATION arbitration210_operator')
                cursor.execute('SELECT mlb036_private.acquire_exact_gate()')
                cursor.execute('SELECT mlb036_private.operator_state()')
                current = cursor.fetchone()[0]
                cursor.execute('SELECT mlb036_private.correct_exact(%s::jsonb,%s::jsonb,%s)',
                    (json.dumps(exact_admission['db_request']), json.dumps(current), exact_admission['preview_sha256']))
                assert cursor.fetchone()[0]['status'] == 'APPLIED'
                cursor.execute('RESET SESSION AUTHORIZATION')
                cursor.execute("SELECT attname FROM pg_attribute WHERE attrelid='public.game_sources'::regclass AND attnum>0 AND NOT attisdropped")
                assert {r[0] for r in cursor.fetchall()} == {'game_source_id', 'game_id', 'source_name', 'external_game_id', 'created_at'}
                cursor.execute('SELECT to_jsonb(s) FROM public.game_sources s WHERE game_source_id=%s', (anchor,))
                original = cursor.fetchone()[0]
                if field == 'delete':
                    statement = 'DELETE FROM public.game_sources WHERE game_source_id=%s'
                else:
                    expressions = {'game_source_id': 'game_source_id+100000', 'game_id': '584',
                        'source_name': "'SYNTHETIC_OTHER'", 'external_game_id': "'SYNTHETIC_OTHER'",
                        'created_at': "created_at+interval'1 second'"}
                    statement = 'UPDATE public.game_sources SET ' + field + '=' + expressions[field] + ' WHERE game_source_id=%s'
                cursor.execute('SAVEPOINT inside_X_anchor')
                with pytest.raises(psycopg2.Error) as refused:
                    cursor.execute(statement, (anchor,))
                assert refused.value.pgcode == 'P0001'
                assert refused.value.diag.message_primary == '036 original source anchor sealed'
                cursor.execute('ROLLBACK TO SAVEPOINT inside_X_anchor')
                cursor.execute('SELECT to_jsonb(s) FROM public.game_sources s WHERE game_source_id=%s', (anchor,))
                assert cursor.fetchone()[0] == original
                cursor.execute('SET CONSTRAINTS ALL IMMEDIATE')
    finally:
        assert full_retained_state(prepared_case) == before
