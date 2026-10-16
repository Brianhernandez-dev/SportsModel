"""Actual dependency/lifetime leaves; integration owner reviewed synthetic fixtures.

Original scratch proposal was not executed by its author. Prediction leaves REQUIRE
a genuine pre036 synthetic NULL-companion run preserved through actual upgrade;
they refuse fixture absence rather than inserting a forbidden036 run or skipping.

The035 lifetime control uses a separately declared synthetic proof of the current
17:41 canonical state. It is not the retained036 17:40 payload and does not assert
provider authenticity. Its purpose is conflicting prior admission, not correction
authorization. Original request/evidence bytes remain untouched.

Not claimed: valid034/035 subject26 while preserving26 authoritative history;
valid035 survivor584 while26 remains an unretired same-date competing canonical
game; revoked035 state (035 has ACTIVATE only); historical026 lifetime rows
seeded through a phased upgrade. Those need separately reviewed fixture history.
"""
from contextlib import contextmanager
from copy import deepcopy
from hashlib import sha256
import json

import psycopg2
from psycopg2 import sql
import pytest

from tests.database.test_mlb_canonical_time_postgres import ENABLED, TARGETS, prepared_case
from tests.database.test_mlb_canonical_time_admission_postgres import adverse_transaction, exact_admission
from tests.database.test_mlb_canonical_time_subject_admission_postgres import clone_row, full_retained_state

pytestmark = pytest.mark.skipif(ENABLED not in TARGETS,
    reason='requires integration-owner reviewed, prepared pre-X disposable fixture')


def full_state(case):
    result = full_retained_state(case)
    # Include newly introduced partner rows/ledgers and their full raw provenance,
    # not only the fixed26/584 snapshot and global fingerprint summaries.
    for table in ('games', 'game_sources', 'mlb_game_identity_write_fences',
                  'game_identity_dispositions', 'game_identity_disposition_events',
                  'mlb_legacy_identity_retirements', 'mlb_legacy_identity_retirement_events',
                  'odds_market_snapshots', 'odds_provider_event_observations'):
        result[table] = case.rows(sql.SQL("SELECT coalesce(jsonb_agg(to_jsonb(r) ORDER BY to_jsonb(r)::text),'[]'::jsonb) "
                                        'FROM public.{} r').format(sql.Identifier(table)))[0][0]
    return result


@contextmanager
def rollback_leaf(case, admission, *, message, dependency=None):
    before = full_state(case)
    try:
        with adverse_transaction(case, 'SELECT 1') as (cursor, _):
            cursor.execute('RESET SESSION AUTHORIZATION')
            yield cursor
            if dependency is not None:
                cursor.execute('SELECT public.mlb_identity_forbidden_dependencies(584)')
                assert cursor.fetchone()[0].get(dependency, 0) > 0
            # Setup must itself satisfy every actual deferred invariant.
            cursor.execute('SET CONSTRAINTS ALL IMMEDIATE')
            cursor.execute('SET CONSTRAINTS ALL DEFERRED')
            cursor.execute('SET SESSION AUTHORIZATION arbitration210_operator')
            cursor.execute('SELECT mlb036_private.operator_state()')
            current = cursor.fetchone()[0]
            with pytest.raises(psycopg2.Error) as refused:
                cursor.execute('SELECT mlb036_private.correct_exact(%s::jsonb,%s::jsonb,%s)',
                    (json.dumps(admission['db_request']), json.dumps(current), admission['preview_sha256']))
            assert refused.value.pgcode == 'P0001'
            assert refused.value.diag.message_primary == message
    finally:
        assert full_state(case) == before


def insert_source(cursor, game, provider, external):
    # Fixed capsule source IDs12/571 were explicit fixture INSERTs; don't assume
    # its independent bigserial is already beyond those retained IDs.
    cursor.execute('INSERT INTO public.game_sources(game_source_id,game_id,source_name,external_game_id) '
        'SELECT coalesce(max(game_source_id),0)+1,%s,%s,%s FROM public.game_sources',
        (game, provider, external))
    assert cursor.rowcount == 1


def retained_observation(cursor, *, raw_game, mapped_game, event):
    assert raw_game in (26, 584, 990777) and mapped_game in (26, 584, 990777)
    assert event.startswith('SYNTHETIC_ONLY_')
    cursor.execute('SELECT odds_market_snapshot_id,odds_provider_event_observation_id '
        'FROM public.odds_market_snapshots WHERE game_id=26 AND odds_provider_event_observation_id IS NOT NULL '
        'ORDER BY odds_market_snapshot_id LIMIT 1')
    original_quote, original_observation = cursor.fetchone()
    insert_source(cursor, mapped_game, 'odds_api', event)
    observation = clone_row(cursor, 'odds_provider_event_observations',
        {'external_event_id': event}, source_id=original_observation)
    quote = clone_row(cursor, 'odds_market_snapshots',
        {'game_id': raw_game, 'odds_provider_event_observation_id': observation}, source_id=original_quote)
    return observation, quote


def insert033(cursor, observation, original, corrected):
    cursor.execute('INSERT INTO public.odds_provider_event_canonical_corrections('
        'odds_provider_event_observation_id,original_game_id,corrected_game_id,correction_reason,evidence_reference) '
        'VALUES(%s,%s,%s,%s,%s)', (observation, original, corrected,
        'Synthetic rollback-only dependency control', 'Synthetic fixture, no provider request'))
    assert cursor.rowcount == 1


def legacy_run(cursor):
    cursor.execute('SELECT moneyline_prediction_run_id FROM public.moneyline_prediction_runs '
        "WHERE model_version='SYNTHETIC_PRE036_LEGACY_NULL' AND canonical_time_knowledge IS NULL "
        'AND identity_disposition_knowledge IS NULL AND identity_retirement_knowledge IS NULL')
    rows = cursor.fetchall()
    assert len(rows) == 1, 'Requires one genuine pre036 run preserved through actual upgrade; do not fabricate/bypass036'
    return rows[0][0]


def insert_prediction(cursor, game_id):
    assert game_id in (26, 584)
    run_id = legacy_run(cursor)
    cursor.execute('SELECT game_date,home_team_id,away_team_id FROM public.games WHERE game_id=%s', (game_id,))
    start, home, away = cursor.fetchone()
    starters = {}
    cursor.execute("SELECT p.team_id,p.baseball_player_id,s.external_player_id::bigint FROM public.player_game_pitching_statistics p JOIN public.baseball_player_sources s USING(baseball_player_id) WHERE p.game_id=26 AND p.is_starter AND s.source_name='mlb_stats'")
    for team, player, external in cursor.fetchall():
        assert team not in starters
        starters[team] = (player, external)
    assert set(starters) == {home, away}
    cursor.execute('INSERT INTO public.moneyline_game_predictions('
        'moneyline_prediction_run_id,game_id,game_start_time,prediction_time,home_team_id,away_team_id,'
        'home_starting_pitcher_id,away_starting_pitcher_id,home_starting_pitcher_mlb_id,away_starting_pitcher_mlb_id,'
        'home_starter_features_available,away_starter_features_available,starter_coverage,missing_raw_value_count,'
        'home_win_probability,away_win_probability,predicted_team_id,predicted_probability) '
        "VALUES(%s,%s,%s,%s-interval'1 day',%s,%s,%s,%s,%s,%s,true,true,'both',0,0.6,0.4,%s,0.6) "
        'RETURNING moneyline_game_prediction_id', (run_id, game_id, start, start, home, away,
            starters[home][0], starters[away][0], starters[home][1], starters[away][1], home))
    return cursor.fetchone()[0]


def insert_evaluation(cursor, prediction, quote):
    cursor.execute('SELECT odds_ingestion_run_id,sportsbook_id,snapshot_time,selection_name,price '
                   'FROM public.odds_market_snapshots WHERE odds_market_snapshot_id=%s', (quote,))
    run, book, snapshot, selection, price = cursor.fetchone()
    cursor.execute('SELECT home_starting_pitcher_mlb_id,away_starting_pitcher_mlb_id '
                   'FROM public.moneyline_game_predictions WHERE moneyline_game_prediction_id=%s', (prediction,))
    home_starter, away_starter = cursor.fetchone()
    assert home_starter and away_starter
    cursor.execute('INSERT INTO public.moneyline_prediction_market_evaluations('
        'moneyline_game_prediction_id,odds_ingestion_run_id,odds_market_snapshot_id,sportsbook_id,'
        'snapshot_time,selection_name,price,model_probability,market_no_vig_probability,sportsbook_count,'
        'implied_probability,model_market_edge,model_price_edge,model_expected_value,starter_coverage,'
        'home_starter_features_available,away_starter_features_available,policy_version,qualifies_as_paper_candidate,'
        'starter_match_status,current_home_starting_pitcher_mlb_id,current_away_starting_pitcher_mlb_id) '
        "VALUES(%s,%s,%s,%s,%s,%s,%s,0.6,0.5,1,0.5,0.1,0.1,0.1,'both',true,true,"
        "'SYNTHETIC_ONLY_DEPENDENCY',true,'matched',%s,%s) RETURNING moneyline_prediction_market_evaluation_id",
        (prediction, run, quote, book, snapshot, selection, price, home_starter, away_starter))
    return cursor.fetchone()[0]


@pytest.mark.parametrize('kind', [
    'prediction', 'evaluation', 'settlement', 'indirect_evaluation_via033', 'indirect_settlement_via033',
])
def test_genuine_legacy_prediction_and_decision_dependencies_refuse(
        prepared_case, exact_admission, kind):
    indirect = kind.startswith('indirect_')
    key = 'market_evaluations' if indirect else ('moneyline_game_predictions' if kind == 'prediction'
        else 'moneyline_paper_candidate_settlements' if kind == 'settlement' else 'market_evaluations')
    with rollback_leaf(prepared_case, exact_admission,
                      message='Subject history/decision dependency', dependency=key) as cursor:
        prediction = insert_prediction(cursor, 26 if indirect else 584)
        if kind != 'prediction':
            observation, quote = retained_observation(cursor, raw_game=584,
                mapped_game=26 if indirect else 584, event='SYNTHETIC_ONLY_DECISION_PROVENANCE')
            if indirect:
                # Raw584 -> effective26 makes the canonical prediction/market
                # association coherent, rather than inventing mismatched links.
                insert033(cursor, observation, 584, 26)
            evaluation = insert_evaluation(cursor, prediction, quote)
            if 'settlement' in kind:
                cursor.execute('INSERT INTO public.moneyline_paper_candidate_settlements('
                    'moneyline_prediction_market_evaluation_id,game_id,home_score,away_score,outcome,profit_units) '
                    "VALUES(%s,%s,3,1,'win',0.9)", (evaluation, 26 if indirect else 584))
                assert cursor.rowcount == 1


def test_opposite_retained033_corrected584_then_authoritative_anchor_arrives_refuses(
        prepared_case, exact_admission):
    with rollback_leaf(prepared_case, exact_admission,
                      message='Subject history/decision dependency', dependency='033_corrections') as cursor:
        cursor.execute('SELECT to_jsonb(s) FROM public.game_sources s WHERE game_source_id=571')
        original_anchor = cursor.fetchone()[0]
        # A historical033 correction needs one nearby authoritative candidate.
        # The later arrival/restoration of26's anchor is legal ordinary ingress;
        # do not fabricate033 rows while its validator sees two candidates.
        cursor.execute('DELETE FROM public.game_sources WHERE game_source_id=571')
        assert cursor.rowcount == 1
        insert_source(cursor, 584, 'mlb_stats', '990584')
        observation, _ = retained_observation(cursor, raw_game=26, mapped_game=584,
                                              event='SYNTHETIC_ONLY_OPPOSITE033')
        insert033(cursor, observation, 26, 584)
        cursor.execute('SET CONSTRAINTS ALL IMMEDIATE')
        cursor.execute('SET CONSTRAINTS ALL DEFERRED')
        cursor.execute('INSERT INTO public.game_sources SELECT '
            '(jsonb_populate_record(NULL::public.game_sources,%s::jsonb)).*', (json.dumps(original_anchor),))
        assert cursor.rowcount == 1
        cursor.execute('SELECT to_jsonb(s) FROM public.game_sources s WHERE game_source_id=571')
        assert cursor.fetchone()[0] == original_anchor


def insert034(cursor, admission, subject, survivor):
    implementation = admission['db_request']['retirement_case']
    cursor.execute('INSERT INTO public.game_identity_dispositions('
        'domain,subject_game_id,survivor_game_id,disposition_type,policy_version,reason,evidence_reference,'
        'evidence_sha256,operator_identity,tool_identity,implementation_commit,implementation_sha256,initial_manifest_sha256) '
        "VALUES('MLB',%s,%s,'STALE_MARKET_ONLY_DUPLICATE','1.0.0','Synthetic lifetime control','Synthetic fixture',"
        "%s,'synthetic operator','synthetic test',%s,%s,%s) RETURNING disposition_id",
        (subject, survivor, 'a' * 64, implementation['implementation_commit'], implementation['implementation_sha256'], 'a' * 64))
    case_id = cursor.fetchone()[0]
    event_id = event034(cursor, admission, case_id, 1, None, 'ACTIVATE', 'a' * 64)
    return case_id, event_id


def event034(cursor, admission, case_id, sequence, previous, action, evidence):
    implementation = admission['db_request']['retirement_case']
    cursor.execute('SELECT public.mlb_identity_ledger_fingerprint()')
    before = cursor.fetchone()[0]
    cursor.execute('INSERT INTO public.game_identity_disposition_events('
        'disposition_id,sequence,previous_event_id,action,reason,evidence_reference,evidence_sha256,'
        'operator_identity,tool_identity,implementation_commit,implementation_sha256,approved_manifest_sha256,'
        'pre_state_sha256,post_state_sha256,receipt) '
        "VALUES(%s,%s,%s,%s,'Synthetic lifetime control','Synthetic fixture',%s,'synthetic operator',"
        "'synthetic test',%s,%s,%s,%s,%s,'{}'::jsonb) RETURNING event_id",
        (case_id, sequence, previous, action, evidence, implementation['implementation_commit'],
         implementation['implementation_sha256'], evidence, before, '0' * 64))
    return cursor.fetchone()[0]


@pytest.mark.parametrize('role', ['584_subject_active', '584_survivor_active', '584_survivor_revoked'])
def test_valid034_lifetime_roles_refuse036_even_when_revoked(prepared_case, exact_admission, role):
    with rollback_leaf(prepared_case, exact_admission,
                      message='036 exact fixed source/physical/lifetime case required') as cursor:
        if role == '584_subject_active':
            subject, survivor = 584, 26
        else:
            subject, survivor = 990777, 584
            cursor.execute('INSERT INTO public.games(game_id,game_date,home_team_id,away_team_id) '
                'SELECT 990777,game_date,home_team_id,away_team_id FROM public.games WHERE game_id=584')
            assert cursor.rowcount == 1
            insert_source(cursor, 584, 'mlb_stats', '990584')
        retained_observation(cursor, raw_game=subject, mapped_game=subject,
                             event='SYNTHETIC_ONLY_LIFETIME034')
        case_id, event_id = insert034(cursor, exact_admission, subject, survivor)
        if role.endswith('_revoked'):
            event034(cursor, exact_admission, case_id, 2, event_id, 'REVOKE', 'b' * 64)
            cursor.execute('SELECT count(*) FROM public.mlb_active_stale_identity_dispositions WHERE disposition_id=%s', (case_id,))
            assert cursor.fetchone() == (0,)
        else:
            cursor.execute('SELECT subject_game_id,survivor_game_id FROM public.mlb_active_stale_identity_dispositions WHERE disposition_id=%s', (case_id,))
            assert cursor.fetchall() == [(subject, survivor)]
        cursor.execute('SELECT count(*) FROM public.game_identity_dispositions WHERE disposition_id=%s', (case_id,))
        assert cursor.fetchone() == (1,)


def test_valid_separately_declared035_prior_case_blocks036_correction(prepared_case, exact_admission):
    with rollback_leaf(prepared_case, exact_admission,
                      message='036 exact fixed source/physical/lifetime case required') as cursor:
        retirement = deepcopy(exact_admission['db_request']['retirement_case'])
        cursor.execute('SELECT game_date FROM public.games WHERE game_id=26')
        old_start = cursor.fetchone()[0].isoformat()
        synthetic_proof = deepcopy(retirement['proof'])
        synthetic_proof['gameDate'] = old_start
        prior_game = dict(gamePk=synthetic_proof['gamePk'], officialDate=synthetic_proof['officialDate'],
            gameDate=old_start, gameType=synthetic_proof['gameType'], doubleHeader='N', gameNumber=1,
            ifNecessary='N', status=dict(abstractGameState='Final', detailedState='Final', startTimeTBD=False),
            teams={side: dict(team=dict(id=synthetic_proof[side + '_mlb_id'], name=synthetic_proof[side + '_name']),
                             score=synthetic_proof[side + '_score']) for side in ('home', 'away')})
        payload = json.dumps({'dates': [{'date': synthetic_proof['officialDate'], 'games': [prior_game]}]},
                             sort_keys=True, separators=(',', ':')).encode()
        synthetic_proof['raw_payload_sha256'] = sha256(payload).hexdigest()
        retirement.update(proof=synthetic_proof, evidence_reference='Synthetic independently declared prior035 state',
            evidence_sha256=sha256(payload).hexdigest(), approved_preview_sha256='c' * 64)
        cursor.execute('SELECT public.mlb_retirement_pair_fingerprint(584,26),public.mlb_retirement_fingerprint(%s)',
                       (retirement['implementation_sha256'],))
        pair, state = cursor.fetchone()
        request = dict(case=retirement, expected_pair_sha256=pair, expected_state_sha256=state)
        cursor.execute('SELECT public.mlb_retirement_activate(%s::jsonb)', (json.dumps(request),))
        cursor.fetchone()
        cursor.execute("SELECT subject_game_id,survivor_game_id FROM public.mlb_active_retired_identities WHERE origin='035'")
        assert cursor.fetchall() == [(584, 26)]


def test_optional_legacy_dependency_tables_are_actually_absent_in_foundation_fixture(prepared_case):
    # Explicit catalog evidence, not synthetic CREATE TABLE or a skipped leaf.
    assert prepared_case.rows("SELECT to_regclass('public.model_predictions'),to_regclass('public.game_results')") == [(None, None)]

