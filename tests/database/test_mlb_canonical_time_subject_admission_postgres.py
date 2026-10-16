"""Additional pre-X subject admission leaves; synthetic and rollback-only.

These are protected SQL predicate tests, not new operator approval or complete
T10/T11/T12 certification. No trigger is disabled and no fixture is persisted.
"""
from contextlib import contextmanager
import json

import psycopg2
from psycopg2 import sql
import pytest

from tests.database.test_mlb_canonical_time_postgres import ENABLED, TARGETS, prepared_case
from tests.database.test_mlb_canonical_time_admission_postgres import (
    adverse_transaction, exact_admission,
)
from tests.database.test_mlb_canonical_time_seal_postgres import _snapshot

pytestmark = pytest.mark.skipif(
    ENABLED not in TARGETS,
    reason='requires integration-owner prepared isolated pre-X arbitration210 fixture',
)

TABLES = {
    'historical_games': 'historical_game_id',
    'team_game_statistics': 'team_game_statistics_id',
    'player_game_pitching_statistics': 'player_game_pitching_statistics_id',
    'odds_market_snapshots': 'odds_market_snapshot_id',
    'odds_provider_event_observations': 'odds_provider_event_observation_id',
}
EXTRA_TABLES = (
    'market_analysis', 'odds_provider_event_canonical_corrections',
    'moneyline_prediction_runs', 'moneyline_game_predictions',
    'moneyline_prediction_market_evaluations', 'moneyline_paper_candidate_settlements',
    'moneyline_daily_workflow_runs',
)


def full_retained_state(case):
    """Full protected rows plus all decision rows, not aggregate counts alone."""
    result = {'protected': _snapshot(case)}
    for table in EXTRA_TABLES:
        statement = sql.SQL(
            "SELECT coalesce(jsonb_agg(to_jsonb(t) ORDER BY to_jsonb(t)::text),'[]'::jsonb) "
            'FROM public.{} t').format(sql.Identifier(table))
        result[table] = case.rows(statement)[0][0]
    return result


def clone_row(cursor, table, changes, *, source_id=None):
    """Use actual catalog columns; omit only the declared generated primary key."""
    assert table in TABLES
    primary_key = TABLES[table]
    cursor.execute(
        'SELECT a.attname FROM pg_attribute a '
        'WHERE a.attrelid=%s::regclass AND a.attnum>0 AND NOT a.attisdropped '
        "AND a.attgenerated='' ORDER BY a.attnum", ('public.' + table,))
    columns = [row[0] for row in cursor.fetchall() if row[0] != primary_key]
    assert primary_key not in changes and set(changes) <= set(columns)
    expressions = [sql.Placeholder() if name in changes else sql.Identifier(name)
                   for name in columns]
    predicate = sql.SQL('{}=%s').format(sql.Identifier(primary_key)) if source_id is not None else sql.SQL('game_id=26')
    statement = sql.SQL('INSERT INTO public.{table}({columns}) SELECT {values} '
        'FROM public.{table} WHERE {predicate} ORDER BY {pk} LIMIT 1 RETURNING {pk}').format(
            table=sql.Identifier(table), columns=sql.SQL(',').join(map(sql.Identifier, columns)),
            values=sql.SQL(',').join(expressions), predicate=predicate, pk=sql.Identifier(primary_key))
    values = [changes[name] for name in columns if name in changes]
    if source_id is not None:
        values.append(source_id)
    cursor.execute(statement, values)
    assert cursor.rowcount == 1
    return cursor.fetchone()[0]


@contextmanager
def subject_leaf(case, admission, reason, *, dependency=None):
    before = full_retained_state(case)
    try:
        with adverse_transaction(case, 'SELECT 1') as (cursor, _):
            cursor.execute('RESET SESSION AUTHORIZATION')
            yield cursor
            if dependency is not None:
                cursor.execute('SELECT public.mlb_identity_forbidden_dependencies(584)')
                assert cursor.fetchone()[0].get(dependency, 0) >= 1
            cursor.execute('SET CONSTRAINTS ALL IMMEDIATE')
            cursor.execute('SET CONSTRAINTS ALL DEFERRED')
            cursor.execute('SET SESSION AUTHORIZATION arbitration210_operator')
            cursor.execute('SELECT mlb036_private.operator_state()')
            current = cursor.fetchone()[0]
            with pytest.raises(psycopg2.Error, match=reason) as refused:
                cursor.execute('SELECT mlb036_private.correct_exact(%s::jsonb,%s::jsonb,%s)',
                    (json.dumps(admission['db_request']), json.dumps(current), admission['preview_sha256']))
            assert refused.value.pgcode == 'P0001'
    finally:
        assert full_retained_state(case) == before


@pytest.mark.parametrize('table', [
    'historical_games', 'team_game_statistics', 'player_game_pitching_statistics',
])
def test_subject_authoritative_history_each_refuses(prepared_case, exact_admission, table):
    with subject_leaf(prepared_case, exact_admission, 'Subject history/decision dependency',
                      dependency=table) as cursor:
        changes = {'game_id': 584}
        if table == 'historical_games':
            changes['mlb_game_id'] = 990584
        clone_row(cursor, table, changes)


PROVENANCE_COLUMNS = (
    'odds_provider_event_observation_id', 'sportsbook_provider_identity_id',
    'bookmaker_title_at_observation', 'bookmaker_updated_at', 'market_updated_at', 'observed_at',
)


def raw_subject_quote(cursor):
    return clone_row(cursor, 'odds_market_snapshots',
        {'game_id': 584, **{name: None for name in PROVENANCE_COLUMNS}})


def test_subject_observationless_raw_market_refuses(prepared_case, exact_admission):
    with subject_leaf(prepared_case, exact_admission, 'Identity-only subject has provenance') as cursor:
        raw_subject_quote(cursor)


def test_subject_legacy_market_refuses(prepared_case, exact_admission):
    with subject_leaf(prepared_case, exact_admission, 'Identity-only subject has provenance') as cursor:
        cursor.execute("INSERT INTO public.odds_snapshots(game_id,sportsbook_id,market_type,"
            'home_price,away_price,snapshot_time) '
            "SELECT 584,sportsbook_id,'h2h',-110,110,snapshot_time AT TIME ZONE 'UTC' "
            'FROM public.odds_market_snapshots WHERE game_id=26 ORDER BY odds_market_snapshot_id LIMIT 1')
        assert cursor.rowcount == 1


def test_subject_indirect_market_analysis_dependency_refuses(prepared_case, exact_admission):
    with subject_leaf(prepared_case, exact_admission, 'Subject history/decision dependency',
                      dependency='market_analysis') as cursor:
        quote = raw_subject_quote(cursor)
        cursor.execute('INSERT INTO public.market_analysis(odds_market_snapshot_id,implied_probability) '
                       'VALUES(%s,0.5)', (quote,))
        assert cursor.rowcount == 1


def linked_observation(cursor, mapped_game):
    event = 'SYNTHETIC_ONLY_SUBJECT_ADMISSION'
    cursor.execute("SELECT odds_provider_event_observation_id FROM public.odds_market_snapshots "
        'WHERE game_id=26 AND odds_provider_event_observation_id IS NOT NULL '
        'ORDER BY odds_market_snapshot_id LIMIT 1')
    original_observation = cursor.fetchone()[0]
    cursor.execute('INSERT INTO public.game_sources(game_id,source_name,external_game_id) '
                   "VALUES(%s,'odds_api',%s)", (mapped_game, event))
    observation = clone_row(cursor, 'odds_provider_event_observations',
        {'external_event_id': event}, source_id=original_observation)
    cursor.execute('SELECT odds_market_snapshot_id FROM public.odds_market_snapshots '
                   'WHERE game_id=26 AND odds_provider_event_observation_id=%s '
                   'ORDER BY odds_market_snapshot_id LIMIT 1', (original_observation,))
    original_quote = cursor.fetchone()[0]
    clone_row(cursor, 'odds_market_snapshots',
              {'game_id': 584, 'odds_provider_event_observation_id': observation},
              source_id=original_quote)
    return observation


def test_subject_retained_observation_refuses(prepared_case, exact_admission):
    with subject_leaf(prepared_case, exact_admission, 'Identity-only subject has provenance') as cursor:
        observation = linked_observation(cursor, 584)
        cursor.execute('SELECT o.external_event_id,s.game_id FROM public.odds_provider_event_observations o '
            'JOIN public.game_sources s ON s.source_name=o.source_name AND s.external_game_id=o.external_event_id '
            'WHERE o.odds_provider_event_observation_id=%s', (observation,))
        assert cursor.fetchall() == [('SYNTHETIC_ONLY_SUBJECT_ADMISSION', 584)]


def test_subject_retained033_correction_refuses(prepared_case, exact_admission):
    with subject_leaf(prepared_case, exact_admission, 'Subject history/decision dependency',
                      dependency='033_corrections') as cursor:
        observation = linked_observation(cursor, 26)
        cursor.execute('INSERT INTO public.odds_provider_event_canonical_corrections('
            'odds_provider_event_observation_id,original_game_id,corrected_game_id,'
            'correction_reason,evidence_reference) VALUES(%s,584,26,%s,%s)',
            (observation, 'Synthetic rollback-only retained033 provenance', 'Synthetic fixture, no provider calls'))
        assert cursor.rowcount == 1
