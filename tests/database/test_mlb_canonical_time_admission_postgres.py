"""Pre-X actual protected admission regressions; synthetic, always rolled back.

The integration owner supplies the exact prepared preview/request/evidence capsule.
No fixture is installed, reseeded, corrected persistently, or issued a receipt here.
Privileged synthetic corruptions below are never exposed to application principals.
"""
from copy import deepcopy
from contextlib import contextmanager
from pathlib import Path
import json
import os

import psycopg2
import pytest

from tests.database.test_mlb_canonical_time_postgres import (
    ENABLED, TARGETS, prepared_case,
)

pytestmark = pytest.mark.skipif(
    ENABLED not in TARGETS,
    reason='requires integration-owner prepared isolated pre-X arbitration210 fixture',
)


@pytest.fixture(scope='module')
def exact_admission(prepared_case):
    from sportsmodel.database.mlb_canonical_time_repository import OperatorTarget
    from sportsmodel.database.mlb_operator_guard import digest
    from sportsmodel.operations.mlb_canonical_time_arbitration import validate_request
    root = Path(os.environ['SPORTSMODEL_ARBITRATION_CASE_BYTES'])
    assert root.name == 'CASE_BYTES_' + ENABLED.rsplit('-', 1)[-1].upper()
    assert root.is_dir() and not root.is_symlink()
    preview = json.loads((root / 'PREVIEW.json').read_bytes())
    raw = (root / 'REQUEST.json').read_bytes()
    evidence = (root / 'SYNTHETIC_EVIDENCE.zip').read_bytes()
    identity = prepared_case.rows(
        'SELECT host(inet_server_addr()),inet_server_port(),'
        'pg_postmaster_start_time(),(pg_control_system()).system_identifier::text')[0]
    target = OperatorTarget(host='127.0.0.1', port=prepared_case.port,
        database='sportsmodel_test_arbitration210_36', server_address=identity[0],
        server_port=identity[1], postmaster_started_at=identity[2].isoformat(),
        identity_kind='isolated', system_identifier=identity[3])
    request, db_request = validate_request(raw, evidence, target)
    assert preview['request'] == request and preview['db_request'] == db_request
    assert digest({k: v for k, v in preview.items() if k != 'preview_sha256'}) == preview['preview_sha256']
    assert prepared_case.rows('SELECT count(*) FROM mlb036_private.arbitrations') == [(0,)]
    assert prepared_case.rows('SELECT count(*) FROM mlb036_private.knowledge_receipts') == [(0,)]
    return preview


def retained_state(case):
    return case.rows('SELECT mlb036_private.business_snapshot(),mlb036_private.state(),'
                     '(SELECT count(*) FROM mlb036_private.arbitrations),'
                     '(SELECT count(*) FROM mlb036_private.knowledge_receipts)')


@contextmanager
def adverse_transaction(case, mutation, params=None):
    """Trusted test setup inside existing exclusive gate, never a production path.

    Refresh expected state to isolate admission predicates from earlier preview
    anti-drift refusal. The public operator still requires its unchanged exact
    approved preview and fresh committed probe; these are protected SQL leaf tests.
    """
    before = retained_state(case)
    try:
        with case.session(isolation='SERIALIZABLE') as connection:
            connection.rollback()
            connection.set_session(readonly=False, isolation_level='SERIALIZABLE')
            with connection.cursor() as cursor:
                cursor.execute('SET SESSION AUTHORIZATION arbitration210_operator')
                cursor.execute('SELECT mlb036_private.acquire_exact_gate()')
                cursor.execute('RESET SESSION AUTHORIZATION')
                cursor.execute(mutation, params)
                cursor.execute('SET SESSION AUTHORIZATION arbitration210_operator')
                cursor.execute('SELECT mlb036_private.operator_state()')
                yield cursor, cursor.fetchone()[0]
    finally:
        assert retained_state(case) == before


@pytest.mark.parametrize('game_id,field,value', [
    (26, 'doubleheader_status', 'doubleheader'), (26, 'game_number', 2),
    (584, 'doubleheader_status', 'doubleheader'), (584, 'game_number', 2),
])
def test_conflicting_stored_metadata_refuses_before_correction(
        prepared_case, exact_admission, game_id, field, value):
    before = retained_state(prepared_case)
    assert field in ('doubleheader_status', 'game_number')
    with prepared_case.session(isolation='SERIALIZABLE') as connection:
        connection.rollback()
        connection.set_session(readonly=False, isolation_level='SERIALIZABLE')
        with connection.cursor() as cursor:
            cursor.execute('SET SESSION AUTHORIZATION arbitration210_operator')
            cursor.execute('SELECT mlb036_private.acquire_exact_gate()')
            cursor.execute('RESET SESSION AUTHORIZATION')
            cursor.execute('UPDATE public.games SET ' + field + '=%s WHERE game_id=%s', (value, game_id))
            cursor.execute('SET SESSION AUTHORIZATION arbitration210_operator')
            cursor.execute('SELECT mlb036_private.operator_state()')
            current = cursor.fetchone()[0]
            with pytest.raises(psycopg2.Error, match='exact fixed source/physical/lifetime case required'):
                cursor.execute('SELECT mlb036_private.correct_exact(%s::jsonb,%s::jsonb,%s)',
                    (json.dumps(exact_admission['db_request']), json.dumps(current), exact_admission['preview_sha256']))
    assert retained_state(prepared_case) == before


@pytest.mark.parametrize('label,mutation,reason', [
    ('missing_result', 'DELETE FROM public.historical_games WHERE game_id=26', 'Unique authoritative historical record required'),
    ('result_pk', 'UPDATE public.historical_games SET mlb_game_id=900585 WHERE game_id=26', 'Survivor authoritative result conflicts'),
    ('result_date', "UPDATE public.historical_games SET game_date='2026-07-13' WHERE game_id=26", 'Survivor authoritative result conflicts'),
    ('result_home', "UPDATE public.historical_games SET home_team='Cleveland Guardians' WHERE game_id=26", 'Survivor authoritative result conflicts'),
    ('result_away', "UPDATE public.historical_games SET away_team='Miami Marlins' WHERE game_id=26", 'Survivor authoritative result conflicts'),
    ('result_score', 'UPDATE public.historical_games SET home_score=4 WHERE game_id=26', 'Survivor authoritative result conflicts'),
    ('result_win', 'UPDATE public.historical_games SET home_win=false WHERE game_id=26', 'Survivor authoritative result conflicts'),
    ('missing_team', 'DELETE FROM public.team_game_statistics WHERE game_id=26 AND is_home', 'Complete oriented team history required'),
    ('team_orientation', 'UPDATE public.team_game_statistics SET is_home=false WHERE game_id=26 AND is_home', 'Complete oriented team history required'),
    ('team_score', 'UPDATE public.team_game_statistics SET runs=runs+1 WHERE game_id=26 AND is_home', 'Complete oriented team history required'),
    ('team_allowed', 'UPDATE public.team_game_statistics SET runs_allowed=runs_allowed+1 WHERE game_id=26 AND is_home', 'Complete oriented team history required'),
    ('team_source', "UPDATE public.team_game_statistics SET source_name='synthetic_other' WHERE game_id=26 AND is_home", 'Complete oriented team history required'),
    ('missing_starter', 'UPDATE public.player_game_pitching_statistics SET is_starter=false WHERE game_id=26 AND is_starter', 'Complete canonical pitching history required'),
    ('pitching_source', "UPDATE public.player_game_pitching_statistics SET source_name='synthetic_other' WHERE game_id=26 AND appearance_order=6", 'Complete canonical pitching history required'),
    ('pitching_future', "UPDATE public.player_game_pitching_statistics SET created_at=clock_timestamp()+interval '1 day' WHERE game_id=26 AND appearance_order=6", 'Complete canonical pitching history required'),
    ('team_future', "UPDATE public.team_game_statistics SET created_at=clock_timestamp()+interval '1 day' WHERE game_id=26", 'Future history availability'),
    ('pitching_gap', 'UPDATE public.player_game_pitching_statistics SET appearance_order=7 WHERE game_id=26 AND appearance_order=6', 'Incomplete pitching appearance order'),
    ('missing_player_source', "DELETE FROM public.baseball_player_sources WHERE source_name='mlb_stats' AND baseball_player_id IN (SELECT baseball_player_id FROM public.player_game_pitching_statistics WHERE game_id=26 AND appearance_order=6)", 'Complete canonical pitching history required'),
    ('wrong_player_source', "UPDATE public.baseball_player_sources SET external_player_id='invalid_'||baseball_player_id::text WHERE source_name='mlb_stats' AND baseball_player_id IN (SELECT baseball_player_id FROM public.player_game_pitching_statistics WHERE game_id=26 AND appearance_order=6)", 'Complete canonical pitching history required'),
    ('result_away_score', 'UPDATE public.historical_games SET away_score=2 WHERE game_id=26', 'Survivor authoritative result conflicts'),
    ('missing_away_team', 'DELETE FROM public.team_game_statistics WHERE game_id=26 AND NOT is_home', 'Complete oriented team history required'),
    ('away_team_orientation', 'UPDATE public.team_game_statistics SET is_home=true WHERE game_id=26 AND NOT is_home', 'Complete oriented team history required'),
    ('away_team_score', 'UPDATE public.team_game_statistics SET runs=runs+1 WHERE game_id=26 AND NOT is_home', 'Complete oriented team history required'),
    ('away_team_allowed', 'UPDATE public.team_game_statistics SET runs_allowed=runs_allowed+1 WHERE game_id=26 AND NOT is_home', 'Complete oriented team history required'),
    ('away_team_source', "UPDATE public.team_game_statistics SET source_name='synthetic_other' WHERE game_id=26 AND NOT is_home", 'Complete oriented team history required'),
    ('pitching_other_team', 'UPDATE public.player_game_pitching_statistics SET team_id=(SELECT min(team_id) FROM public.teams WHERE team_id NOT IN(SELECT home_team_id FROM public.games WHERE game_id=26 UNION SELECT away_team_id FROM public.games WHERE game_id=26)) WHERE player_game_pitching_statistics_id=(SELECT min(player_game_pitching_statistics_id) FROM public.player_game_pitching_statistics WHERE game_id=26 AND appearance_order=6)', 'Complete canonical pitching history required'),
    ('same_team_starters', 'UPDATE public.player_game_pitching_statistics SET is_starter=(team_id=(SELECT home_team_id FROM public.games WHERE game_id=26) AND appearance_order IN(1,2)) WHERE game_id=26', 'Complete canonical pitching history required'),
    ('pitching_min_order', 'UPDATE public.player_game_pitching_statistics SET appearance_order=appearance_order+10 WHERE game_id=26', 'Incomplete pitching appearance order'),
], ids=lambda value: value if len(value) < 30 else None)
def test_survivor_each_unchanged035_completeness_leaf_refuses(
        prepared_case, exact_admission, label, mutation, reason):
    with adverse_transaction(prepared_case, mutation) as (cursor, current):
        with pytest.raises(psycopg2.Error, match=reason):
            cursor.execute('SELECT mlb036_private.correct_exact(%s::jsonb,%s::jsonb,%s)',
                (json.dumps(exact_admission['db_request']), json.dumps(current), exact_admission['preview_sha256']))


@pytest.mark.parametrize('team_metric,pitcher_metric', [
    ('pitching_outs', 'pitching_outs'), ('runs_allowed', 'runs_allowed'),
    ('hits_allowed', 'hits_allowed'), ('home_runs_allowed', 'home_runs_allowed'),
    ('walks_allowed', 'walks_allowed'), ('strikeouts_recorded', 'strikeouts'),
])
def test_survivor_each_unchanged035_metric_disagreement_refuses(
        prepared_case, exact_admission, team_metric, pitcher_metric):
    assert pitcher_metric in ('pitching_outs', 'runs_allowed', 'hits_allowed',
                              'home_runs_allowed', 'walks_allowed', 'strikeouts')
    mutation = 'UPDATE public.player_game_pitching_statistics SET ' + pitcher_metric + '=' + pitcher_metric + '+1 WHERE game_id=26 AND appearance_order=6'
    reason = 'Complete canonical pitching history required' if team_metric == 'pitching_outs' else 'Pitching/team metric disagreement'
    with adverse_transaction(prepared_case, mutation) as (cursor, current):
        with pytest.raises(psycopg2.Error, match=reason):
            cursor.execute('SELECT mlb036_private.correct_exact(%s::jsonb,%s::jsonb,%s)',
                (json.dumps(exact_admission['db_request']), json.dumps(current), exact_admission['preview_sha256']))


@pytest.mark.parametrize('label,mutation,reason', [
    ('missing_anchor571', 'DELETE FROM public.game_sources WHERE game_source_id=571', 'exact fixed source/physical/lifetime case required'),
    ('missing_odds12', 'DELETE FROM public.game_sources WHERE game_source_id=12', 'exact fixed source/physical/lifetime case required'),
    ('changed_anchor', "UPDATE public.game_sources SET external_game_id='900585' WHERE game_source_id=571", 'exact fixed source/physical/lifetime case required'),
    ('changed_odds', "UPDATE public.game_sources SET external_game_id='synthetic-other-event' WHERE game_source_id=12", 'exact fixed source/physical/lifetime case required'),
    ('home_provider_identity', "UPDATE public.baseball_team_sources SET external_team_id='999146' WHERE source_name='mlb_stats' AND team_id=(SELECT home_team_id FROM public.games WHERE game_id=26)", 'Canonical MLB source participants required'),
    ('away_provider_identity', "UPDATE public.baseball_team_sources SET external_team_id='999114' WHERE source_name='mlb_stats' AND team_id=(SELECT away_team_id FROM public.games WHERE game_id=26)", 'Canonical MLB source participants required'),
    ('subject_odds_source', "INSERT INTO public.game_sources(game_id,source_name,external_game_id) VALUES(584,'odds_api','synthetic-subject-odds')", 'Identity-only subject has provenance'),
    ('subject_mlb_source', "INSERT INTO public.game_sources(game_id,source_name,external_game_id) VALUES(584,'mlb_stats','900999')", 'Subject history/decision dependency'),
    ('subject_unknown_source', "INSERT INTO public.game_sources(game_id,source_name,external_game_id) VALUES(584,'synthetic_unknown','synthetic-subject-unknown')", 'Subject history/decision dependency'),
    ('subject_legacy_mlb', 'UPDATE public.games SET mlb_game_id=900999 WHERE game_id=584', 'Legacy MLB oriented identity required'),
    ('subject_legacy_odds', "UPDATE public.games SET odds_api_event_id='synthetic-subject-legacy' WHERE game_id=584", 'Legacy MLB oriented identity required'),
    ('extra_candidate', "INSERT INTO public.games(game_id,game_date,home_team_id,away_team_id) SELECT 900999,'2026-07-12T18:00:00Z',home_team_id,away_team_id FROM public.games WHERE game_id=26", 'Unreviewed competing real-event identity'),
], ids=lambda value: value if len(value) < 30 else None)
def test_exact_identity_source_and_candidate_admission_leaves(
        prepared_case, exact_admission, label, mutation, reason):
    with adverse_transaction(prepared_case, mutation) as (cursor, current):
        with pytest.raises(psycopg2.Error, match=reason):
            cursor.execute('SELECT mlb036_private.correct_exact(%s::jsonb,%s::jsonb,%s)',
                (json.dumps(exact_admission['db_request']), json.dumps(current), exact_admission['preview_sha256']))


@pytest.mark.parametrize('label,changes', [
    ('plus60', {'old_start':'2026-07-12T17:40:00Z','new_start':'2026-07-12T17:41:00Z'}),
    ('wrong_old', {'old_start':'2026-07-12T17:42:00Z'}),
    ('wrong_new', {'new_start':'2026-07-12T17:39:00Z'}),
    ('wrong_pk', {'game_pk':900585}), ('native_pk_in_isolated', {'game_pk':823842}),
    ('wrong_subject', {'subject':585}), ('wrong_survivor', {'survivor':27}),
    ('reversed_pair', {'subject':26,'survivor':584}),
    ('subject_boolean', {'subject':True}), ('subject_string', {'subject':'584'}),
    ('wrong_profile', {'profile':'0'*64}), ('wrong_request_hash', {'request_sha256':'not-a-hash'}),
    ('wrong_evidence_hash', {'evidence_sha256':'not-a-hash'}),
    ('old_submicro', {'old_start':'2026-07-12T17:41:00.000000001Z'}),
    ('new_submicro', {'new_start':'2026-07-12T17:40:00.000000001Z'}),
    ('old_naive', {'old_start':'2026-07-12T17:41:00'}),
    ('new_naive', {'new_start':'2026-07-12T17:40:00'}),
], ids=lambda value:value if isinstance(value,str) else None)
def test_exact_request_scope_and_typed_timestamp_sql_admission_refuses(
        prepared_case,exact_admission,label,changes):
    request=deepcopy(exact_admission['db_request']);request.update(changes)
    with adverse_transaction(prepared_case,'SELECT 1') as (cursor,current):
        # SQL expressions do not promise left-to-right OR evaluation. A boolean
        # cannot be cast to an identity integer; that engine refusal is exact and
        # occurs before any business mutation, not a reason to weaken the guard.
        message='invalid input syntax for type integer' if label=='subject_boolean' else 'exact request/approval/state differs'
        code='22P02' if label=='subject_boolean' else 'P0001'
        with pytest.raises(psycopg2.Error,match=message) as refused:
            cursor.execute('SELECT mlb036_private.correct_exact(%s::jsonb,%s::jsonb,%s)',
                (json.dumps(request),json.dumps(current),exact_admission['preview_sha256']))
        assert refused.value.pgcode==code


@pytest.mark.parametrize('subject_metadata', ['legacy_null', 'single_game1'])
def test_valid_stored_metadata_preserves_exact_admission_and_deferred_checks(
        prepared_case, exact_admission, subject_metadata):
    before = retained_state(prepared_case)
    with prepared_case.session(isolation='SERIALIZABLE') as connection:
        connection.rollback()
        connection.set_session(readonly=False, isolation_level='SERIALIZABLE')
        with connection.cursor() as cursor:
            cursor.execute('SET SESSION AUTHORIZATION arbitration210_operator')
            cursor.execute('SELECT mlb036_private.acquire_exact_gate()')
            if subject_metadata == 'single_game1':
                cursor.execute('RESET SESSION AUTHORIZATION')
                cursor.execute("UPDATE public.games SET doubleheader_status='single',game_number=1 WHERE game_id=584")
                cursor.execute('SET SESSION AUTHORIZATION arbitration210_operator')
            cursor.execute('SELECT mlb036_private.operator_state()')
            current = cursor.fetchone()[0]
            cursor.execute('SELECT mlb036_private.correct_exact(%s::jsonb,%s::jsonb,%s)',
                (json.dumps(exact_admission['db_request']), json.dumps(current), exact_admission['preview_sha256']))
            assert cursor.fetchone()[0]['status'] == 'APPLIED'
            cursor.execute('SET CONSTRAINTS ALL IMMEDIATE')
    assert retained_state(prepared_case) == before


@pytest.mark.parametrize('side', ['home', 'away', 'both'])
def test_fixed_case_requires_all_twelve_known_pitching_appearances(
        prepared_case, exact_admission, side):
    """A04 fixed-case inventory, in addition to unchanged035 per-row completeness.

    Removing the final zero-metric nonstarter keeps aggregate sums, two starters
    and appearance contiguity valid. Those alone cannot replace the fixed inventory.
    This does not introduce a general pitching-count rule for other MLB games.
    """
    before = retained_state(prepared_case)
    assert prepared_case.rows('SELECT count(*) FROM public.player_game_pitching_statistics WHERE game_id=26') == [(12,)]
    with prepared_case.session(isolation='SERIALIZABLE') as connection:
        connection.rollback()
        connection.set_session(readonly=False, isolation_level='SERIALIZABLE')
        with connection.cursor() as cursor:
            cursor.execute('SET SESSION AUTHORIZATION arbitration210_operator')
            cursor.execute('SELECT mlb036_private.acquire_exact_gate()')
            cursor.execute('RESET SESSION AUTHORIZATION')
            if side == 'both':
                cursor.execute('DELETE FROM public.player_game_pitching_statistics WHERE game_id=26 AND appearance_order=6')
                assert cursor.rowcount == 2
            else:
                assert side in ('home', 'away')
                cursor.execute('DELETE FROM public.player_game_pitching_statistics WHERE game_id=26 '
                    'AND appearance_order=6 AND team_id=(SELECT ' + side + '_team_id FROM public.games WHERE game_id=26)')
                assert cursor.rowcount == 1
            cursor.execute('SET SESSION AUTHORIZATION arbitration210_operator')
            cursor.execute('SELECT mlb036_private.operator_state()')
            current = cursor.fetchone()[0]
            try:
                cursor.execute('SELECT mlb036_private.correct_exact(%s::jsonb,%s::jsonb,%s)',
                    (json.dumps(exact_admission['db_request']), json.dumps(current), exact_admission['preview_sha256']))
                cursor.fetchone()
                cursor.execute('SET CONSTRAINTS ALL IMMEDIATE')
            except psycopg2.Error as error:
                assert 'complete fixed survivor pitching inventory required' in str(error)
            else:
                pytest.fail('REAL_IMPLEMENTATION_DEFECT: admitted fixed case missing known pitching appearances')
    assert retained_state(prepared_case) == before


def test_duplicate_pitching_appearance_refuses_at_existing_schema_constraint(prepared_case):
    before = retained_state(prepared_case)
    with prepared_case.session(isolation='SERIALIZABLE') as connection:
        connection.rollback()
        connection.set_session(readonly=False, isolation_level='SERIALIZABLE')
        with connection.cursor() as cursor:
            with pytest.raises(psycopg2.Error) as refused:
                cursor.execute('UPDATE public.player_game_pitching_statistics SET appearance_order=5 '
                    'WHERE game_id=26 AND appearance_order=6 AND team_id=(SELECT home_team_id FROM public.games WHERE game_id=26)')
            assert refused.value.pgcode == '23505'
            assert refused.value.diag.constraint_name == 'uq_player_game_pitching_appearance_order'
    assert retained_state(prepared_case) == before
