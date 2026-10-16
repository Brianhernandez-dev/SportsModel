"""Actual post-audit seal probes, executable only by the integration owner.

Every write attempt uses a bounded positively isolated session and unconditional
rollback. No migration, correction, receipt issuance, retirement, commit, trigger
disable or ledger fabrication is performed. Full retained rows are compared after
every attempt; counts alone are not preservation evidence. An ordinary synthetic
source-remap leaf additionally probes inbound subject ingress after legal X.
"""
from contextlib import contextmanager

import psycopg2
import pytest

from tests.database.test_mlb_canonical_time_postgres import (
    DATABASE, ENABLED, TARGETS, committed_proof, prepared_case,
)


pytestmark = pytest.mark.skipif(
    ENABLED not in TARGETS,
    reason='requires integration-owner enabled, positively isolated committed-X/Y arbitration210 PG16',
)

GAME_ACTIONS = {
    'delete': 'DELETE FROM public.games WHERE game_id=%s',
    'physical_id': 'UPDATE public.games SET game_id=game_id+900000 WHERE game_id=%s',
    'retime_plus60': "UPDATE public.games SET game_date=game_date+interval'60 seconds' WHERE game_id=%s",
    'retime_minus60': "UPDATE public.games SET game_date=game_date-interval'60 seconds' WHERE game_id=%s",
    'orientation': 'UPDATE public.games SET home_team_id=away_team_id,away_team_id=home_team_id WHERE game_id=%s',
    'legacy_mlb': 'UPDATE public.games SET mlb_game_id=coalesce(mlb_game_id,900584)+1 WHERE game_id=%s',
    'legacy_odds': "UPDATE public.games SET odds_api_event_id='SYNTHETIC_ONLY_POST_AUDIT_REMAP' WHERE game_id=%s",
}
SOURCE_ACTIONS = {
    'delete': 'DELETE FROM public.game_sources WHERE game_source_id=%s',
    'physical_id': 'UPDATE public.game_sources SET game_source_id=game_source_id+900000 WHERE game_source_id=%s',
    'canonical_remap': 'UPDATE public.game_sources SET game_id=584 WHERE game_source_id=%s',
    'provider_remap': "UPDATE public.game_sources SET source_name='synthetic_seal_test' WHERE game_source_id=%s",
    'external_remap': "UPDATE public.game_sources SET external_game_id=external_game_id||'_SYNTHETIC_REMAP' WHERE game_source_id=%s",
    'availability': "UPDATE public.game_sources SET created_at=coalesce(created_at,TIMESTAMP '2000-01-01')+interval'1 second' WHERE game_source_id=%s",
}
PHYSICAL_MESSAGE = '036 audit-linked physical identity sealed'
SOURCE_MESSAGE = '036 original source anchor sealed'
SUBJECT_MESSAGE = '036 subject identity sealed'


SNAPSHOT_SQL = """SELECT jsonb_build_object(
    'business',mlb036_private.business_snapshot(),
    'proof_state',mlb036_private.state(),
    'physical_rows',(SELECT coalesce(jsonb_agg(to_jsonb(g) ORDER BY g.game_id),'[]'::jsonb)
        FROM public.games g WHERE game_id=ANY(%s)),
    'source_rows',(SELECT coalesce(jsonb_agg(to_jsonb(s) ORDER BY s.game_source_id),'[]'::jsonb)
        FROM public.game_sources s WHERE game_id=ANY(%s) OR game_source_id IN(12,571)),
    'fences',(SELECT coalesce(jsonb_agg(to_jsonb(f) ORDER BY f.game_id),'[]'::jsonb)
        FROM public.mlb_game_identity_write_fences f WHERE game_id=ANY(%s)),
    'topology',(SELECT to_jsonb(t) FROM public.mlb_identity_topology_fence t WHERE singleton),
    'audits',(SELECT coalesce(jsonb_agg(to_jsonb(a) ORDER BY a.audit_id),'[]'::jsonb)
        FROM mlb036_private.arbitrations a),
    'events',(SELECT coalesce(jsonb_agg(to_jsonb(e) ORDER BY e.event_id),'[]'::jsonb)
        FROM mlb036_private.arbitration_events e),
    'receipts',(SELECT coalesce(jsonb_agg(to_jsonb(r) ORDER BY r.receipt_id),'[]'::jsonb)
        FROM mlb036_private.knowledge_receipts r),
    'authority',(SELECT to_jsonb(a) FROM mlb036_private.authority a WHERE singleton))"""


def _snapshot(case, *, extra_ids=()):
    ids = [26, 584, *extra_ids]
    rows = case.rows(SNAPSHOT_SQL, (ids, ids, ids))
    assert len(rows) == 1 and type(rows[0][0]) is dict
    return rows[0][0]


def _cursor_snapshot(cursor, *, extra_ids=()):
    ids = [26, 584, *extra_ids]
    cursor.execute(SNAPSHOT_SQL, (ids, ids, ids))
    row = cursor.fetchone()
    assert row is not None and type(row[0]) is dict
    return row[0]


@pytest.fixture(scope='module')
def sealed_case(prepared_case, committed_proof):
    """Require actual legal-X rows and no034/035 activation before seal probes."""
    case = prepared_case
    assert case.port == TARGETS[ENABLED] and case.port != 5432
    retained = _snapshot(case)
    games = {row['game_id']: row for row in retained['physical_rows']}
    assert set(games) == {26, 584}
    assert games[26]['game_date'] == games[584]['game_date']
    assert (games[26]['home_team_id'], games[26]['away_team_id']) == (
        games[584]['home_team_id'], games[584]['away_team_id'])
    anchors = {row['game_source_id']: row for row in retained['source_rows']}
    assert set(anchors) == {12, 571}
    assert anchors[12]['game_id'] == anchors[571]['game_id'] == 26
    assert anchors[12]['source_name'] == 'odds_api' and anchors[571]['source_name'] == 'mlb_stats'
    assert retained['audits'], 'Post-audit seals require actual centrally committed X'
    audit = retained['audits'][0]
    assert (audit['duplicate_physical_id'], audit['survivor_physical_id'], audit['signed_delta_seconds']) == (584, 26, -60)
    assert audit['new_start'] == games[26]['game_date']
    assert retained['events'] and all(row['audit_reference'] == audit['audit_id'] for row in retained['events'])
    receipt, _ = committed_proof
    assert receipt['referenced_audit_ids'] == [audit['audit_id']]
    assert any(row['receipt_id'] == receipt['receipt_id'] and row == receipt for row in retained['receipts'])
    # Actual absence of either fixed row in lifetime034/035 is inspected row-wise.
    assert case.rows('SELECT to_jsonb(d) FROM public.game_identity_dispositions d '
                     'WHERE subject_game_id IN(26,584) OR survivor_game_id IN(26,584)') == []
    assert case.rows('SELECT to_jsonb(r) FROM public.mlb_legacy_identity_retirements r '
                     'WHERE subject_game_id IN(26,584) OR survivor_game_id IN(26,584)') == []
    for principal in ('reader', 'operator'):
        assert case.rows("SELECT has_schema_privilege(%s,'public','USAGE')", (case.roles[principal],)) == [(False,)]
    return case


@contextmanager
def _rollback_write_session(case, principal):
    """Literal whitelist/storage verification comes from sealed_case first."""
    assert ENABLED in TARGETS and case.port == TARGETS[ENABLED] and case.port != 5432
    user = 'postgres' if principal == 'admin' else case.roles[principal]
    connection = psycopg2.connect(host='127.0.0.1', port=case.port, dbname=DATABASE,
        user=user, password=case._password, connect_timeout=5,
        options='-c lock_timeout=1500ms -c statement_timeout=15000ms -c timezone=UTC')
    try:
        connection.set_session(readonly=False, isolation_level='READ COMMITTED', autocommit=False)
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_database(),current_setting('server_version_num'),"
                           "current_setting('transaction_read_only'),current_setting('transaction_isolation')")
            database, version, readonly, isolation = cursor.fetchone()
            assert database == DATABASE and int(version)//10000 == 16
            assert readonly == 'off' and isolation == 'read committed'
        yield connection
    finally:
        try:
            connection.rollback()
        finally:
            connection.close()


def _denied_preserving_full_rows(case, principal, statement, args, *, code, message):
    before = _snapshot(case)
    try:
        with _rollback_write_session(case, principal) as connection, connection.cursor() as cursor:
            cursor.execute('SAVEPOINT post_audit_attempt')
            with pytest.raises(psycopg2.Error) as refused:
                cursor.execute(statement, args)
                cursor.execute('SET CONSTRAINTS ALL IMMEDIATE')
            assert refused.value.pgcode == code
            assert message in refused.value.diag.message_primary
            cursor.execute('ROLLBACK TO SAVEPOINT post_audit_attempt')
            if principal == 'admin':
                assert _cursor_snapshot(cursor) == before
    finally:
        assert _snapshot(case) == before, 'Full physical/provenance/audit/receipt/fence rows changed after denial'


@pytest.mark.parametrize('game_id', [26, 584])
@pytest.mark.parametrize('action', list(GAME_ACTIONS))
def test_T51_trusted_admin_physical_delete_remap_retime_refuses_with_full_preservation(sealed_case, game_id, action):
    _denied_preserving_full_rows(sealed_case, 'admin', GAME_ACTIONS[action], (game_id,),
                                 code='P0001', message=PHYSICAL_MESSAGE)


@pytest.mark.parametrize('source_id', [12, 571])
@pytest.mark.parametrize('action', list(SOURCE_ACTIONS))
def test_T51_trusted_admin_original_source_anchor_mutation_refuses_with_full_preservation(sealed_case, source_id, action):
    _denied_preserving_full_rows(sealed_case, 'admin', SOURCE_ACTIONS[action], (source_id,),
                                 code='P0001', message=SOURCE_MESSAGE)


@pytest.mark.parametrize('principal', ['reader', 'operator'])
@pytest.mark.parametrize('game_id', [26, 584])
@pytest.mark.parametrize('action', list(GAME_ACTIONS))
def test_T51_runtime_operator_cannot_directly_mutate_audit_linked_game(sealed_case, principal, game_id, action):
    _denied_preserving_full_rows(sealed_case, principal, GAME_ACTIONS[action], (game_id,),
                                 code='42501', message='permission denied for schema public')


@pytest.mark.parametrize('principal', ['reader', 'operator'])
@pytest.mark.parametrize('source_id', [12, 571])
@pytest.mark.parametrize('action', list(SOURCE_ACTIONS))
def test_T51_runtime_operator_cannot_directly_mutate_original_source_anchor(sealed_case, principal, source_id, action):
    _denied_preserving_full_rows(sealed_case, principal, SOURCE_ACTIONS[action], (source_id,),
                                 code='42501', message='permission denied for schema public')


def test_T51_new_source_insert_into_subject_is_sealed_after_actual_audit(sealed_case):
    _denied_preserving_full_rows(sealed_case, 'admin',
        "INSERT INTO public.game_sources(game_source_id,game_id,source_name,external_game_id) "
        "VALUES(9000584,584,'synthetic_seal_test','SYNTHETIC_ONLY_SUBJECT')", None,
        code='P0001', message=SUBJECT_MESSAGE)


def test_T51_existing_unrelated_source_cannot_remap_into_subject_after_actual_audit(sealed_case):
    """UPDATE ingress must preserve the same no-new-subject-source invariant.

    Unrelated synthetic game/source exist only in this rollback-only transaction.
    If ordinary seed guards refuse first, their actual error is retained and no
    guard is disabled or fabricated to force the adversarial state.
    """
    case = sealed_case
    before = _snapshot(case)
    assert case.rows('SELECT to_jsonb(g) FROM public.games g WHERE game_id=900600') == []
    assert case.rows('SELECT to_jsonb(s) FROM public.game_sources s WHERE game_source_id=900600') == []
    try:
        with _rollback_write_session(case, 'admin') as connection, connection.cursor() as cursor:
            cursor.execute("INSERT INTO public.games(game_id,game_date,home_team_id,away_team_id,doubleheader_status,game_number) "
                "SELECT 900600,clock_timestamp()+interval'2 hours',home_team_id,away_team_id,'single',1 FROM public.games WHERE game_id=26")
            cursor.execute("INSERT INTO public.game_sources(game_source_id,game_id,source_name,external_game_id) "
                "VALUES(900600,900600,'synthetic_seal_test','SYNTHETIC_ONLY_900600')")
            seeded = _cursor_snapshot(cursor, extra_ids=(900600,))
            seed_sources = [row for row in seeded['source_rows'] if row['game_source_id'] == 900600]
            assert len(seed_sources) == 1 and seed_sources[0]['game_id'] == 900600
            cursor.execute('SAVEPOINT inbound_subject_remap')
            with pytest.raises(psycopg2.Error) as refused:
                cursor.execute('UPDATE public.game_sources SET game_id=584 WHERE game_source_id=900600')
                cursor.execute('SET CONSTRAINTS ALL IMMEDIATE')
            assert refused.value.pgcode == 'P0001'
            assert SUBJECT_MESSAGE in refused.value.diag.message_primary
            cursor.execute('ROLLBACK TO SAVEPOINT inbound_subject_remap')
            assert _cursor_snapshot(cursor, extra_ids=(900600,)) == seeded
    finally:
        assert _snapshot(case) == before
        assert case.rows('SELECT to_jsonb(g) FROM public.games g WHERE game_id=900600') == []
        assert case.rows('SELECT to_jsonb(s) FROM public.game_sources s WHERE game_source_id=900600') == []
