"""Actual N17 stage drift components; reviewed by the integration owner.

No database actions have been performed by this module's author. This supplements
existing completion, immutable-membership and terminal-race regressions; it is not
a claim that every N17 state class has been certified.

Before reservation there is no immutable run-bound future-target slate yet. Those
cases test stale fixed correction knowledge, not an invented pre-bound slate.
After reservation ordinary target changes must refuse prediction admission, even
if their visible values return, because the monotonic fence has advanced.

Excluded rather than bypassed: restoring/decrementing topology or fences; changing
sealed26/584 timestamps or anchors; forged private receipts/audits; historical NULL
backfill; newY after drift. Synthetic new targets are never provider identities.
"""
from contextlib import contextmanager
from datetime import datetime, timedelta
import json

import psycopg2
from psycopg2 import sql
import pytest

from tests.database.test_mlb_canonical_time_postgres import (
    ENABLED, TARGETS, prepared_case, committed_proof,
)
from tests.database.test_mlb_canonical_time_subject_admission_postgres import full_retained_state

pytestmark = pytest.mark.skipif(ENABLED not in TARGETS,
    reason='requires integration-owner reviewed, prepared committed-X/Y disposable fixture')

TARGET_IDS = (970100, 970101)
FIXED_CHANGES = (
    ('fixed26_metadata', False), ('fixed26_metadata', True),
    ('fixed584_metadata', False), ('fixed584_metadata', True),
    ('fixed26_fence', False), ('topology', False),
)
TARGET_CHANGES = tuple((kind, restore) for kind in (
    'target_time', 'target_source', 'target_orientation', 'target_metadata', 'target_source_availability',
) for restore in (False, True)) + (('target_fence', False),)


def full_state(case):
    answer = full_retained_state(case)
    for table in ('games', 'game_sources', 'mlb_game_identity_write_fences'):
        answer[table] = case.rows(sql.SQL("SELECT coalesce(jsonb_agg(to_jsonb(r) ORDER BY to_jsonb(r)::text),'[]'::jsonb) "
                                        'FROM public.{} r').format(sql.Identifier(table)))[0][0]
    return answer


def cursor_state(cursor):
    cursor.execute("SELECT jsonb_build_object('state',mlb036_private.state(),"
        "'authority',(SELECT to_jsonb(a) FROM mlb036_private.authority a),"
        "'games',(SELECT jsonb_agg(to_jsonb(g) ORDER BY game_id) FROM public.games g),"
        "'sources',(SELECT jsonb_agg(to_jsonb(s) ORDER BY game_source_id) FROM public.game_sources s),"
        "'fences',(SELECT jsonb_agg(to_jsonb(f) ORDER BY game_id) FROM public.mlb_game_identity_write_fences f),"
        "'runs',(SELECT coalesce(jsonb_agg(to_jsonb(r) ORDER BY moneyline_prediction_run_id),'[]'::jsonb) FROM public.moneyline_prediction_runs r),"
        "'predictions',(SELECT coalesce(jsonb_agg(to_jsonb(p) ORDER BY moneyline_game_prediction_id),'[]'::jsonb) FROM public.moneyline_game_predictions p),"
        "'receipts',(SELECT jsonb_agg(to_jsonb(k) ORDER BY receipt_id) FROM mlb036_private.knowledge_receipts k))")
    return cursor.fetchone()[0]


@contextmanager
def populated_targets(case, proof, count=1):
    assert count in (1, 2)
    before = full_state(case)
    try:
        with case.session() as connection:
            connection.rollback()
            connection.set_session(readonly=False, isolation_level='READ COMMITTED')
            with connection.cursor() as cursor:
                cursor.execute('SELECT home_team_id,away_team_id FROM public.games WHERE game_id=26')
                home, away = cursor.fetchone()
                cursor.execute("SELECT (((clock_timestamp() AT TIME ZONE 'America/Los_Angeles')::date+31) "
                               "+time '12:00') AT TIME ZONE 'America/Los_Angeles'")
                start = cursor.fetchone()[0]
                cursor.execute('SELECT count(*) FROM public.games WHERE game_id=ANY(%s)', (list(TARGET_IDS),))
                assert cursor.fetchone() == (0,)
                for offset in range(count):
                    game_id = TARGET_IDS[offset]
                    cursor.execute('INSERT INTO public.games(game_id,game_date,home_team_id,away_team_id,'
                        "scheduled_innings,doubleheader_status,game_number) VALUES(%s,%s,%s,%s,9,'single',1)",
                        (game_id, start + timedelta(minutes=offset), home, away))
                    cursor.execute('INSERT INTO public.game_sources(game_source_id,game_id,source_name,external_game_id) '
                                   "VALUES(%s,%s,'mlb_stats',%s)", (game_id, game_id, str(game_id + 9_000_000)))
                cursor.execute("SELECT clock_timestamp(),(%s::timestamptz AT TIME ZONE 'America/Los_Angeles')::date", (start,))
                cutoff, target_date = cursor.fetchone()
                receipt, _ = proof
                assert cutoff >= datetime.fromisoformat(receipt['available_at'])
                context = dict(receipt=receipt, cutoff=cutoff, target_date=target_date,
                    start=start, home=home, away=away, game_ids=list(TARGET_IDS[:count]))
                yield cursor, context
                cursor.execute('RESET SESSION AUTHORIZATION')
                cursor.execute('SET CONSTRAINTS ALL IMMEDIATE')
    finally:
        assert full_state(case) == before


def reserve(cursor, context):
    cursor.execute('SET SESSION AUTHORIZATION arbitration210_reader')
    request = dict(target_date=context['target_date'].isoformat(), run_type='preview',
        model_version='SYNTHETIC_NO_MODEL', feature_schema_version='SYNTHETIC',
        model_artifact_sha256='0' * 64, model_training_cutoff=None)
    cursor.execute('SELECT mlb036_private.reserve_run(%s,%s,%s::jsonb)',
        (context['receipt']['receipt_id'], context['cutoff'], json.dumps(request)))
    run_id = cursor.fetchone()[0]
    cursor.execute('RESET SESSION AUTHORIZATION')
    cursor.execute('SELECT to_jsonb(r) FROM public.moneyline_prediction_runs r WHERE moneyline_prediction_run_id=%s', (run_id,))
    original = cursor.fetchone()[0]
    assert {item['game']['game_id'] for item in original['canonical_time_knowledge']['target_state']} == set(context['game_ids'])
    context.update(run_id=run_id, original_run=original)
    return run_id


def prediction(context, game_id):
    offset = context['game_ids'].index(game_id)
    return dict(moneyline_prediction_run_id=context['run_id'], game_id=game_id,
        mlb_game_id=game_id + 9_000_000,
        game_start_time=(context['start'] + timedelta(minutes=offset)).isoformat(),
        prediction_time=context['cutoff'].isoformat(), home_team_id=context['home'], away_team_id=context['away'],
        home_starting_pitcher_id=None, away_starting_pitcher_id=None,
        home_starting_pitcher_mlb_id=None, away_starting_pitcher_mlb_id=None,
        home_starter_features_available=False, away_starter_features_available=False,
        starter_coverage='none', missing_raw_value_count=0, home_win_probability=0.6,
        away_win_probability=0.4, predicted_team_id=context['home'], predicted_probability=0.6)


def apply_change(cursor, kind, restore):
    game_id = TARGET_IDS[0]
    assert (kind, restore) in FIXED_CHANGES + TARGET_CHANGES
    if kind == 'topology':
        cursor.execute('UPDATE public.mlb_identity_topology_fence SET epoch=epoch+1 WHERE singleton')
        assert cursor.rowcount == 1
        return
    changed_game = 26 if kind.startswith('fixed26_') else 584 if kind.startswith('fixed584_') else game_id
    cursor.execute('SELECT to_jsonb(g),f.epoch FROM public.games g '
        'LEFT JOIN public.mlb_game_identity_write_fences f USING(game_id) WHERE game_id=%s', (changed_game,))
    original_game, original_fence = cursor.fetchone()
    original_fence = 0 if original_fence is None else original_fence
    original_source = None
    if kind in ('target_source', 'target_source_availability'):
        cursor.execute('SELECT to_jsonb(s) FROM public.game_sources s WHERE game_source_id=%s', (game_id,))
        original_source = cursor.fetchone()[0]
    if kind in ('fixed26_fence', 'target_fence'):
        cursor.execute('UPDATE public.mlb_game_identity_write_fences SET epoch=epoch+1 WHERE game_id=%s', (changed_game,))
    elif kind.endswith('_metadata'):
        cursor.execute('UPDATE public.games SET scheduled_innings=coalesce(scheduled_innings,9)+1 WHERE game_id=%s', (changed_game,))
        assert cursor.rowcount == 1
        if restore:
            cursor.execute('UPDATE public.games SET scheduled_innings=%s WHERE game_id=%s',
                           (original_game['scheduled_innings'], changed_game))
    elif kind == 'target_time':
        cursor.execute("UPDATE public.games SET game_date=game_date+interval'60 seconds' WHERE game_id=%s", (game_id,))
        assert cursor.rowcount == 1
        if restore:
            cursor.execute('UPDATE public.games SET game_date=%s WHERE game_id=%s', (context_time(original_game), game_id))
    elif kind == 'target_orientation':
        cursor.execute('UPDATE public.games SET home_team_id=away_team_id,away_team_id=home_team_id WHERE game_id=%s', (game_id,))
        assert cursor.rowcount == 1
        if restore:
            cursor.execute('UPDATE public.games SET home_team_id=%s,away_team_id=%s WHERE game_id=%s',
                           (original_game['home_team_id'], original_game['away_team_id'], game_id))
    elif kind == 'target_source':
        cursor.execute("UPDATE public.game_sources SET external_game_id=external_game_id||'_SYNTHETIC_CHANGED' WHERE game_source_id=%s", (game_id,))
        assert cursor.rowcount == 1
        if restore:
            cursor.execute('UPDATE public.game_sources SET external_game_id=%s WHERE game_source_id=%s',
                           (original_source['external_game_id'], game_id))
    else:
        assert kind == 'target_source_availability'
        cursor.execute("UPDATE public.game_sources SET created_at=created_at+interval'1 second' WHERE game_source_id=%s", (game_id,))
        assert cursor.rowcount == 1
        if restore:
            cursor.execute('UPDATE public.game_sources SET created_at=%s WHERE game_source_id=%s',
                           (original_source['created_at'], game_id))
    assert cursor.rowcount == 1
    cursor.execute('SELECT to_jsonb(g),f.epoch FROM public.games g '
        'LEFT JOIN public.mlb_game_identity_write_fences f USING(game_id) WHERE game_id=%s', (changed_game,))
    changed_row, advanced_fence = cursor.fetchone()
    assert advanced_fence > original_fence
    if restore:
        assert changed_row == original_game, 'Visible physical fields must be genuinely restored'
        if original_source is not None:
            cursor.execute('SELECT to_jsonb(s) FROM public.game_sources s WHERE game_source_id=%s', (game_id,))
            assert cursor.fetchone()[0] == original_source


def context_time(game):
    return datetime.fromisoformat(game['game_date'])


@pytest.mark.parametrize('stage', ['before_reservation', 'before_prediction'])
@pytest.mark.parametrize('kind,restore', FIXED_CHANGES)
def test_fixed_correction_state_drift_and_restore_refuse_at_each_early_stage(
        prepared_case, committed_proof, stage, kind, restore):
    with populated_targets(prepared_case, committed_proof) as (cursor, context):
        if stage == 'before_prediction':
            reserve(cursor, context)
        apply_change(cursor, kind, restore)
        expected = cursor_state(cursor)
        cursor.execute('SET SESSION AUTHORIZATION arbitration210_reader')
        cursor.execute('SAVEPOINT early_stage_refusal')
        with pytest.raises(psycopg2.Error) as refused:
            if stage == 'before_reservation':
                reserve(cursor, context)
            else:
                cursor.execute('SELECT mlb036_private.insert_prediction(%s,%s,%s::jsonb)',
                    (context['receipt']['receipt_id'], context['cutoff'], json.dumps(prediction(context, TARGET_IDS[0]))))
        assert refused.value.pgcode == 'P0001'
        assert refused.value.diag.message_primary == '036 unavailable/stale/changed knowledge'
        cursor.execute('ROLLBACK TO SAVEPOINT early_stage_refusal')
        cursor.execute('RESET SESSION AUTHORIZATION')
        assert cursor_state(cursor) == expected


@pytest.mark.parametrize('kind,restore', TARGET_CHANGES)
def test_run_bound_future_target_drift_or_visible_restore_refuses_prediction(
        prepared_case, committed_proof, kind, restore):
    with populated_targets(prepared_case, committed_proof) as (cursor, context):
        reserve(cursor, context)
        apply_change(cursor, kind, restore)
        expected = cursor_state(cursor)
        cursor.execute('SET SESSION AUTHORIZATION arbitration210_reader')
        cursor.execute('SAVEPOINT target_stage_refusal')
        with pytest.raises(psycopg2.Error) as refused:
            cursor.execute('SELECT mlb036_private.insert_prediction(%s,%s,%s::jsonb)',
                (context['receipt']['receipt_id'], context['cutoff'], json.dumps(prediction(context, TARGET_IDS[0]))))
        assert refused.value.pgcode == 'P0001'
        assert refused.value.diag.message_primary == '036 prediction admission target state drift'
        cursor.execute('ROLLBACK TO SAVEPOINT target_stage_refusal')
        cursor.execute('RESET SESSION AUTHORIZATION')
        assert cursor_state(cursor) == expected


@pytest.mark.parametrize('accounting', ['own_only', 'external_fence', 'rolled_back_own_insert'])
def test_two_distinct_bound_predictions_normalize_only_own_fences_and_complete(
        prepared_case, committed_proof, accounting):
    with populated_targets(prepared_case, committed_proof, count=2) as (cursor, context):
        run_id = reserve(cursor, context)
        original = context['original_run']['canonical_time_knowledge']
        cursor.execute('SELECT game_id,epoch FROM public.mlb_game_identity_write_fences WHERE game_id=ANY(%s)',
                       (context['game_ids'],))
        initial_fences = dict(cursor.fetchall())
        if accounting == 'rolled_back_own_insert':
            cursor.execute('SAVEPOINT aborted_own_prediction')
            cursor.execute('SET SESSION AUTHORIZATION arbitration210_reader')
            cursor.execute('SELECT mlb036_private.insert_prediction(%s,%s,%s::jsonb)',
                (context['receipt']['receipt_id'], context['cutoff'], json.dumps(prediction(context, TARGET_IDS[0]))))
            assert cursor.fetchone()[0] > 0
            cursor.execute('ROLLBACK TO SAVEPOINT aborted_own_prediction')
            cursor.execute('RESET SESSION AUTHORIZATION')
            cursor.execute('SELECT count(*) FROM public.moneyline_game_predictions WHERE moneyline_prediction_run_id=%s', (run_id,))
            assert cursor.fetchone() == (0,)
            cursor.execute('SELECT game_id,epoch FROM public.mlb_game_identity_write_fences WHERE game_id=ANY(%s)', (context['game_ids'],))
            assert dict(cursor.fetchall()) == initial_fences
        for game_id in context['game_ids']:
            cursor.execute('SET SESSION AUTHORIZATION arbitration210_reader')
            cursor.execute('SELECT mlb036_private.insert_prediction(%s,%s,%s::jsonb)',
                (context['receipt']['receipt_id'], context['cutoff'], json.dumps(prediction(context, game_id))))
            assert cursor.fetchone()[0] > 0
            cursor.execute('RESET SESSION AUTHORIZATION')
            cursor.execute('SELECT mlb036_private.run_companion(r,%s,%s,%s) '
                'FROM mlb036_private.knowledge_receipts r WHERE receipt_id=%s',
                (context['cutoff'], context['target_date'], run_id, context['receipt']['receipt_id']))
            assert cursor.fetchone()[0] == original
        cursor.execute('SELECT game_id,epoch FROM public.mlb_game_identity_write_fences WHERE game_id=ANY(%s)',
                       (context['game_ids'],))
        assert dict(cursor.fetchall()) == {game_id: epoch + 1 for game_id, epoch in initial_fences.items()}
        cursor.execute('SELECT to_jsonb(p) FROM public.moneyline_game_predictions p '
            'WHERE moneyline_prediction_run_id=%s ORDER BY game_id', (run_id,))
        original_predictions = cursor.fetchall()
        assert len(original_predictions) == 2
        if accounting == 'external_fence':
            cursor.execute('UPDATE public.mlb_game_identity_write_fences SET epoch=epoch+1 WHERE game_id=%s', (TARGET_IDS[0],))
        expected = cursor_state(cursor)
        cursor.execute('SET SESSION AUTHORIZATION arbitration210_reader')
        statement = "SELECT mlb036_private.finish_run(%s,%s,%s,%s,'completed',%s::jsonb,NULL)"
        arguments = (context['receipt']['receipt_id'], context['cutoff'], context['receipt']['receipt_body_sha256'], run_id,
                     json.dumps(dict(games_received=2, predictions_created=2, games_skipped=0)))
        if accounting == 'external_fence':
            cursor.execute('SAVEPOINT refuse_external_fence')
            with pytest.raises(psycopg2.Error) as refused:
                cursor.execute(statement, arguments)
            assert refused.value.pgcode == 'P0001'
            assert refused.value.diag.message_primary == '036 exact server-derived run companion/target state required; admission drift'
            cursor.execute('ROLLBACK TO SAVEPOINT refuse_external_fence')
        else:
            cursor.execute(statement, arguments)
        cursor.execute('RESET SESSION AUTHORIZATION')
        if accounting == 'external_fence':
            assert cursor_state(cursor) == expected
        cursor.execute('SET CONSTRAINTS ALL IMMEDIATE')
        cursor.execute('SELECT status,predictions_created,canonical_time_knowledge FROM public.moneyline_prediction_runs '
                       'WHERE moneyline_prediction_run_id=%s', (run_id,))
        assert cursor.fetchone() == (('running', 0, original) if accounting == 'external_fence' else ('completed', 2, original))
        cursor.execute('SELECT to_jsonb(p) FROM public.moneyline_game_predictions p '
            'WHERE moneyline_prediction_run_id=%s ORDER BY game_id', (run_id,))
        assert cursor.fetchall() == original_predictions


COMPLETION_RESTORE_CHANGES = (
    ('target_source', True), ('target_orientation', True),
    ('target_metadata', False), ('target_metadata', True),
    ('target_source_availability', False), ('target_source_availability', True),
    ('fixed26_metadata', False), ('fixed26_metadata', True),
    ('fixed584_metadata', False), ('fixed584_metadata', True),
)


@pytest.mark.parametrize('kind,restore', COMPLETION_RESTORE_CHANGES)
def test_completion_rechecks_remaining_projection_and_restored_target_states(prepared_case, committed_proof, kind, restore):
    with populated_targets(prepared_case, committed_proof) as (cursor, context):
        reserve(cursor, context)
        cursor.execute('SET SESSION AUTHORIZATION arbitration210_reader')
        cursor.execute('SELECT mlb036_private.insert_prediction(%s,%s,%s::jsonb)',
            (context['receipt']['receipt_id'], context['cutoff'], json.dumps(prediction(context, TARGET_IDS[0]))))
        assert cursor.fetchone()[0] > 0
        cursor.execute('RESET SESSION AUTHORIZATION')
        apply_change(cursor, kind, restore)
        expected = cursor_state(cursor)
        cursor.execute('SET SESSION AUTHORIZATION arbitration210_reader')
        cursor.execute('SAVEPOINT refuse_completion_projection')
        with pytest.raises(psycopg2.Error) as refused:
            cursor.execute("SELECT mlb036_private.finish_run(%s,%s,%s,%s,'completed',%s::jsonb,NULL)",
                (context['receipt']['receipt_id'], context['cutoff'], context['receipt']['receipt_body_sha256'], context['run_id'],
                 json.dumps(dict(games_received=1, predictions_created=1, games_skipped=0))))
        assert refused.value.pgcode == 'P0001'
        assert refused.value.diag.message_primary == ('036 unavailable/stale/changed knowledge' if kind.startswith('fixed')
            else '036 exact server-derived run companion/target state required; admission drift')
        cursor.execute('ROLLBACK TO SAVEPOINT refuse_completion_projection')
        cursor.execute('RESET SESSION AUTHORIZATION')
        assert cursor_state(cursor) == expected

