"""Rollback-only legal035 survivor584 admission followed by later candidate ingress.
No provider authenticity claim, time edit, commit or immutable-guard bypass.
The later competing026 state is deliberately stale and must refuse036.
"""
from copy import deepcopy
from hashlib import sha256
import json

import psycopg2
from psycopg2 import sql
import pytest

from tests.database.test_mlb_canonical_time_postgres import ENABLED, TARGETS, prepared_case
from tests.database.test_mlb_canonical_time_admission_postgres import exact_admission
from tests.database.test_mlb_canonical_time_dependency_lifetime_postgres import (
    rollback_leaf, insert034, event034,
)

pytestmark = pytest.mark.skipif(ENABLED not in TARGETS,
    reason='requires integration-owner reviewed, prepared isolated pre-X fixture')

STAT_KEYS = {
    'historical_games': 'historical_game_id',
    'team_game_statistics': 'team_game_statistics_id',
    'player_game_pitching_statistics': 'player_game_pitching_statistics_id',
}


def clone_statistics(cursor, table, source_game, changes):
    assert table in STAT_KEYS and source_game in (26, 584, 970777)
    cursor.execute('SELECT attname FROM pg_attribute WHERE attrelid=%s::regclass '
        "AND attnum>0 AND NOT attisdropped AND attgenerated='' ORDER BY attnum", ('public.' + table,))
    names = [row[0] for row in cursor.fetchall() if row[0] != STAT_KEYS[table]]
    assert set(changes) <= set(names)
    expressions = [sql.Placeholder() if name in changes else sql.Identifier(name) for name in names]
    values = [changes[name] for name in names if name in changes]
    cursor.execute(sql.SQL('INSERT INTO public.{table}({columns}) SELECT {values} FROM public.{table} WHERE game_id=%s').format(
        table=sql.Identifier(table), columns=sql.SQL(',').join(map(sql.Identifier, names)),
        values=sql.SQL(',').join(expressions)), (*values, source_game))
    assert cursor.rowcount == {'historical_games': 1, 'team_game_statistics': 2,
                              'player_game_pitching_statistics': 12}[table]


def synthetic035_case(cursor, admission, *, subject, survivor, game_pk, approval):
    assert (subject, survivor, game_pk) in ((990777, 584, 990584), (26, 584, 990584))
    case = deepcopy(admission['db_request']['retirement_case'])
    cursor.execute('SELECT game_date FROM public.games WHERE game_id=%s', (subject,))
    subject_start = cursor.fetchone()[0].isoformat()
    cursor.execute('SELECT game_date FROM public.games WHERE game_id=%s', (survivor,))
    start = cursor.fetchone()[0].isoformat()
    proof = case['proof']
    proof.update(gamePk=game_pk, gameDate=start, subject_start=subject_start)
    game = dict(gamePk=game_pk, officialDate=proof['officialDate'], gameDate=start,
        gameType='R', doubleHeader='N', gameNumber=1, ifNecessary='N',
        status=dict(abstractGameState='Final', detailedState='Final', startTimeTBD=False),
        teams={side: dict(team=dict(id=proof[side + '_mlb_id'], name=proof[side + '_name']),
                         score=proof[side + '_score']) for side in ('home', 'away')})
    payload = json.dumps({'dates': [{'date': proof['officialDate'], 'games': [game]}]},
                         sort_keys=True, separators=(',', ':')).encode()
    proof['raw_payload_sha256'] = sha256(payload).hexdigest()
    case.update(subject_game_id=subject, survivor_game_id=survivor, game_pk=game_pk,
        evidence_reference='SYNTHETIC_ONLY separately declared historical retirement phase',
        evidence_sha256=sha256(payload).hexdigest(), approved_preview_sha256=approval)
    return case, payload


def activate035(cursor, case):
    cursor.execute('SELECT public.mlb_retirement_pair_fingerprint(%s,%s),public.mlb_retirement_fingerprint(%s)',
        (case['subject_game_id'], case['survivor_game_id'], case['implementation_sha256']))
    pair, state = cursor.fetchone()
    request = dict(case=case, expected_pair_sha256=pair, expected_state_sha256=state)
    cursor.execute('SELECT public.mlb_retirement_activate(%s::jsonb)', (json.dumps(request),))
    receipt = cursor.fetchone()[0]
    cursor.execute('SET CONSTRAINTS ALL IMMEDIATE')
    cursor.execute('SET CONSTRAINTS ALL DEFERRED')
    return receipt


def validate035(cursor, subject):
    cursor.execute('SELECT public.mlb_retirement_validate(r,false) '
                   'FROM public.mlb_legacy_identity_retirements r WHERE subject_game_id=%s', (subject,))
    assert cursor.rowcount == 1
    cursor.fetchone()


def exact_refusal(cursor, statement, args, message):
    cursor.execute('SAVEPOINT legal_phase_refusal')
    with pytest.raises(psycopg2.Error) as refused:
        cursor.execute(statement, args)
    assert refused.value.pgcode == 'P0001'
    assert refused.value.diag.message_primary == message
    cursor.execute('ROLLBACK TO SAVEPOINT legal_phase_refusal')


def test035_584_survivor_legal_admission_then_later_competitor_blocks036(prepared_case, exact_admission):
    with rollback_leaf(prepared_case, exact_admission,
                      message='036 exact fixed source/physical/lifetime case required') as cursor:
        cursor.execute('SELECT to_jsonb(g) FROM public.games g WHERE game_id=26')
        original26 = cursor.fetchone()[0]
        cursor.execute('UPDATE public.games SET home_team_id=away_team_id,away_team_id=home_team_id WHERE game_id=26')
        assert cursor.rowcount == 1
        clone_statistics(cursor, 'historical_games', 26, {'game_id': 584, 'mlb_game_id': 990584})
        clone_statistics(cursor, 'team_game_statistics', 26, {'game_id': 584})
        clone_statistics(cursor, 'player_game_pitching_statistics', 26, {'game_id': 584})
        cursor.execute("INSERT INTO public.game_sources(game_source_id,game_id,source_name,external_game_id) VALUES(990584,584,'mlb_stats','990584')")
        cursor.execute('INSERT INTO public.games(game_id,game_date,home_team_id,away_team_id,doubleheader_status,game_number) '
            "SELECT 990777,game_date,home_team_id,away_team_id,'single',1 FROM public.games WHERE game_id=584")
        assert cursor.rowcount == 1
        case, payload = synthetic035_case(cursor, exact_admission,
            subject=990777, survivor=584, game_pk=990584, approval='d' * 64)
        assert case['proof']['raw_payload_sha256'] == sha256(payload).hexdigest()
        activate035(cursor, case)
        validate035(cursor, 990777)
        cursor.execute('UPDATE public.games SET home_team_id=%s,away_team_id=%s WHERE game_id=26',
                       (original26['home_team_id'], original26['away_team_id']))
        assert cursor.rowcount == 1
        cursor.execute('SELECT to_jsonb(g) FROM public.games g WHERE game_id=26')
        assert cursor.fetchone()[0] == original26
        cursor.execute('SET CONSTRAINTS ALL IMMEDIATE')
        cursor.execute('SET CONSTRAINTS ALL DEFERRED')
        # Ordinary new candidate ingress is legal, but does not imply the prior
        # retirement is still semantically unique. Preserve this separate refusal.
        exact_refusal(cursor, 'SELECT public.mlb_retirement_validate(r,false) '
            'FROM public.mlb_legacy_identity_retirements r WHERE subject_game_id=990777', (),
            'Unreviewed competing real-event identity')
        cursor.execute("SELECT subject_game_id,survivor_game_id FROM public.mlb_active_retired_identities WHERE origin='035'")
        assert cursor.fetchall() == [(990777, 584)]



