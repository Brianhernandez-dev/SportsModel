"""Explicit isolated PostgreSQL16 integration; never ambient application targets."""
from datetime import datetime, timezone, timedelta, date
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import json
import os
import subprocess
import zipfile
import threading
import time

SCENARIO_EVIDENCE = []

import psycopg2
import pytest

pytestmark = pytest.mark.skipif(
    os.getenv('SPORTSMODEL_IDENTITY_DISPOSABLE_CONTAINER') != 'sportsmodel-identity-110-20261010-a',
    reason='requires explicitly verified new identity-110 disposable PostgreSQL16')

ROOT = Path(__file__).resolve().parents[2]
NAME = 'sportsmodel-identity-110-20261010-a'
DATABASE = 'sportsmodel_test_110a20261010'
PORT = 55446
COMMIT = 'bc57003c6434b309b74367ecf6304f4202a519a9'
HASH = 'a'*64


@pytest.fixture
def db():
    result = subprocess.run(['docker','inspect',NAME],capture_output=True,check=True)
    item = json.loads(result.stdout)[0]
    assert item['Name']=='/'+NAME and item['Config']['Labels']['sportsmodel.verification']=='identity-110'
    assert item['NetworkSettings']['Ports']['5432/tcp']==[dict(HostIp='127.0.0.1',HostPort=str(PORT))]
    assert len(item['Mounts'])==1 and item['Mounts'][0]['Name']==NAME+'-data'
    secret = next(value.split('=',1)[1] for value in item['Config']['Env'] if value.startswith('POSTGRES_PASSWORD='))
    original = psycopg2.connect
    def connection_factory():
        connection = original(host='127.0.0.1',port=PORT,dbname=DATABASE,user='postgres',password=secret,
                              options='-c lock_timeout=1500ms -c statement_timeout=15000ms',connect_timeout=5)
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_database(),current_setting('server_version_num'),current_setting('data_directory')")
            database,version,storage=cursor.fetchone()
            assert database==DATABASE and int(version)//10000==16 and storage=='/var/lib/postgresql/data'
        connection.rollback()
        return connection
    connection=connection_factory()
    try:
        with connection.cursor() as cursor:
            # Destructive rebuild is restricted to this positively identified
            # new container/database; never a production path or connection.
            cursor.execute('DROP SCHEMA public CASCADE; CREATE SCHEMA public')
            cursor.execute((ROOT/'tests/fixtures/database/sportsmodel_foundation_schema.sql').read_text(encoding='utf-8-sig'))
            cursor.execute('CREATE TABLE schema_migrations(version integer primary key,filename text not null unique,checksum char(64) not null)')
            paths=sorted((ROOT/'database/migrations').glob('*.sql'))
            assert [int(path.name[:3]) for path in paths]==list(range(1,35))
            for path in paths:
                if path.name.startswith('007_'):
                    cursor.execute("INSERT INTO teams(team_name) VALUES('Synthetic Legacy Home'),('Synthetic Legacy Away'); INSERT INTO games(game_date,home_team_id,away_team_id) SELECT '2025-01-01',h.team_id,a.team_id FROM teams h,teams a WHERE h.team_name='Synthetic Legacy Home' AND a.team_name='Synthetic Legacy Away'; INSERT INTO sportsbooks(name) VALUES('Synthetic Legacy Book'); INSERT INTO odds_market_snapshots(game_id,sportsbook_id,market_type,selection_name,price,snapshot_time) SELECT game_id,sportsbook_id,'h2h','Synthetic Legacy Home',-110,'2025-01-01' FROM games,sportsbooks")
                sql=path.read_text(encoding='utf-8-sig')
                cursor.execute(sql)
                cursor.execute('INSERT INTO schema_migrations VALUES(%s,%s,%s)',(int(path.name[:3]),path.name,sha256(sql.encode()).hexdigest()))
            cursor.execute("DO $$ BEGIN IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='identity_runtime_test') THEN CREATE ROLE identity_runtime_test NOLOGIN; END IF; END $$")
            cursor.execute('GRANT USAGE ON SCHEMA public TO identity_runtime_test; GRANT SELECT ON ALL TABLES IN SCHEMA public TO identity_runtime_test; GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA public TO identity_runtime_test')
            cursor.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename NOT IN ('game_identity_dispositions','game_identity_disposition_events','mlb_game_identity_write_fences','schema_migrations')")
            for row in cursor.fetchall():
                cursor.execute('GRANT INSERT,UPDATE,DELETE,TRUNCATE ON '+row[0]+' TO identity_runtime_test')
        connection.commit()
    finally:
        connection.close()
    return connection_factory


def query(db, sql, parameters=None):
    connection=db()
    try:
        with connection.cursor() as cursor:
            cursor.execute(sql,parameters)
            rows=cursor.fetchall() if cursor.description else None
        connection.commit()
        return rows
    finally:
        connection.close()


def seed(db,*,reviewed_ids=False):
    h,a=[row[0] for row in query(db,"INSERT INTO teams(team_name) VALUES('Chicago White Sox'),('Cleveland Guardians') RETURNING team_id")]
    query(db,"INSERT INTO baseball_team_sources(team_id,source_name,external_team_id) VALUES(%s,'mlb_stats','145'),(%s,'mlb_stats','114')",(h,a))
    if reviewed_ids:
        s,c=[row[0] for row in query(db,"INSERT INTO games(game_id,game_date,home_team_id,away_team_id) VALUES(11408,'2026-10-08T21:00:00Z',%s,%s),(11409,'2026-10-09T00:00:00Z',%s,%s) RETURNING game_id",(h,a,h,a))]
    else:
        s,c=[row[0] for row in query(db,"INSERT INTO games(game_date,home_team_id,away_team_id) VALUES('2026-10-08T21:00:00Z',%s,%s),('2026-10-09T00:00:00Z',%s,%s) RETURNING game_id",(h,a,h,a))]
    query(db,"INSERT INTO game_sources(game_id,source_name,external_game_id) VALUES(%s,'odds_api','synthetic-old'),(%s,'odds_api','synthetic-new'),(%s,'mlb_stats','900001')",(s,c,c))
    book=query(db,"INSERT INTO sportsbooks(name) VALUES('Synthetic Test Book') RETURNING sportsbook_id")[0][0]
    provider=query(db,"INSERT INTO sportsbook_provider_identities(provider_name,provider_bookmaker_key,sportsbook_id) VALUES('odds_api','synthetic-book',%s) RETURNING sportsbook_provider_identity_id",(book,))[0][0]
    run=query(db,"INSERT INTO odds_ingestion_runs(source_name,sport,status,snapshot_role,target_date,started_at,request_started_at,response_received_at,status_code,request_path,request_regions,request_markets,request_odds_format) VALUES('odds_api','baseball_mlb','running','opening','2026-10-08','2026-10-08T01:00:00Z','2026-10-08T01:00:00Z','2026-10-08T01:00:01Z',200,'synthetic','us','h2h','american') RETURNING odds_ingestion_run_id")[0][0]
    for gid,event,when in ((s,'synthetic-old','2026-10-08T21:00:00Z'),(c,'synthetic-new','2026-10-09T00:00:00Z')):
        obs=query(db,"INSERT INTO odds_provider_event_observations(odds_ingestion_run_id,source_name,provider_sport_key,external_event_id,provider_commence_time,provider_home_team_name,provider_away_team_name,observed_at) VALUES(%s,'odds_api','baseball_mlb',%s,%s,'Chicago White Sox','Cleveland Guardians','2026-10-08T01:00:01Z') RETURNING odds_provider_event_observation_id",(run,event,when))[0][0]
        query(db,"INSERT INTO odds_market_snapshots(game_id,sportsbook_id,market_type,selection_name,line_value,price,snapshot_time,source_name,odds_ingestion_run_id,odds_provider_event_observation_id,sportsbook_provider_identity_id,bookmaker_title_at_observation,observed_at) VALUES(%s,%s,'h2h','Chicago White Sox',NULL,-110,'2026-10-08T01:00:01Z','odds_api',%s,%s,%s,'Synthetic Test Book','2026-10-08T01:00:01Z')",(gid,book,run,obs,provider))
    return s,c,h,a


def activate_sql(db, pair, *, evidence=HASH, previous=None, action='ACTIVATE', sequence=1, case=None,
                 connection=None, commit=True):
    s,c,_,_=pair
    owned = connection is None
    connection=db() if owned else connection
    try:
        if owned:
            connection.set_session(isolation_level='SERIALIZABLE')
        with connection.cursor() as cursor:
            cursor.execute('SELECT mlb_identity_gate(true)')
            if case is None:
                cursor.execute("""INSERT INTO game_identity_dispositions(domain,subject_game_id,survivor_game_id,disposition_type,policy_version,
                    reason,evidence_reference,evidence_sha256,operator_identity,tool_identity,implementation_commit,implementation_sha256,initial_manifest_sha256)
                    VALUES('MLB',%s,%s,'STALE_MARKET_ONLY_DUPLICATE','1.0.0','synthetic evidence','synthetic fixture',%s,'synthetic operator','synthetic tool',%s,%s,%s) RETURNING disposition_id""",(s,c,evidence,COMMIT,HASH,evidence))
                case=cursor.fetchone()[0]
            cursor.execute("""INSERT INTO game_identity_disposition_events(disposition_id,sequence,previous_event_id,action,reason,evidence_reference,
                evidence_sha256,operator_identity,tool_identity,implementation_commit,implementation_sha256,approved_manifest_sha256,
                pre_state_sha256,post_state_sha256,receipt) VALUES(%s,%s,%s,%s,'synthetic evidence','synthetic fixture',%s,'synthetic operator','synthetic tool',%s,%s,%s,%s,%s,'{}') RETURNING event_id,receipt""",(case,sequence,previous,action,evidence,COMMIT,HASH,evidence,HASH,HASH))
            event,receipt=cursor.fetchone()
        if commit:
            connection.commit()
        return case,event,receipt
    finally:
        if owned:
            connection.close()


@pytest.mark.parametrize('operation', ['UPDATE','DELETE','TRUNCATE'])
@pytest.mark.parametrize('table', ['game_identity_dispositions','game_identity_disposition_events'])
def test_ledger_mutation_refused(db,operation,table):
    activate_sql(db,seed(db))
    sql='UPDATE '+table+" SET reason='changed'" if operation=='UPDATE' else operation+' '+('FROM ' if operation=='DELETE' else '')+table
    with pytest.raises(psycopg2.Error):query(db,sql)
    with pytest.raises(psycopg2.Error):query(db,'SET ROLE identity_runtime_test; '+sql)


def test_case_requires_initial_activate_at_commit(db):
    pair=seed(db);s,c,_,_=pair
    with pytest.raises(psycopg2.Error):
        query(db,"INSERT INTO game_identity_dispositions(domain,subject_game_id,survivor_game_id,disposition_type,policy_version,reason,evidence_reference,evidence_sha256,operator_identity,tool_identity,implementation_commit,implementation_sha256,initial_manifest_sha256) VALUES('MLB',%s,%s,'STALE_MARKET_ONLY_DUPLICATE','1.0.0','synthetic','synthetic',%s,'synthetic','synthetic',%s,%s,%s)",(s,c,HASH,COMMIT,HASH,HASH))
    assert query(db,'SELECT count(*) FROM game_identity_dispositions')==[(0,)]


def test_activation_preserves_raw_and_033(db):
    pair=seed(db)
    tables=['games','game_sources','odds_provider_event_observations','odds_market_snapshots',
            'odds_market_snapshots_effective','odds_ingestion_runs','moneyline_game_predictions',
            'moneyline_prediction_market_evaluations','moneyline_paper_candidate_settlements']
    before={table:query(db,'SELECT to_jsonb(t)::text FROM '+table+' t ORDER BY to_jsonb(t)::text') for table in tables}
    case,event,receipt=activate_sql(db,pair)
    assert query(db,'SELECT subject_game_id,survivor_game_id FROM mlb_active_stale_identity_dispositions')==[(pair[0],pair[1])]
    assert before=={table:query(db,'SELECT to_jsonb(t)::text FROM '+table+' t ORDER BY to_jsonb(t)::text') for table in tables}
    assert query(db,'SELECT mlb_identity_ledger_fingerprint()')[0][0]==receipt['ledger_fingerprint']
    assert query(db,'SELECT mlb_identity_pair_fingerprint(%s,%s)',pair[:2])[0][0]==receipt['pair_fingerprint']
    SCENARIO_EVIDENCE.append(dict(scenario='raw_033_betting_preservation',before=before,
                                 after={table:query(db,'SELECT to_jsonb(t)::text FROM '+table+' t ORDER BY to_jsonb(t)::text') for table in tables},receipt=receipt))


@pytest.mark.parametrize('sql', [
    "INSERT INTO game_sources(game_id,source_name,external_game_id) VALUES(%s,'mlb_stats','900002')",
    "INSERT INTO historical_games(game_id,mlb_game_id,game_date,home_team,away_team,home_score,away_score,home_win) VALUES(%s,900002,'2026-10-08','Chicago White Sox','Cleveland Guardians',2,1,TRUE)",
    "UPDATE odds_market_snapshots SET price=-120 WHERE game_id=%s",
    "DELETE FROM odds_market_snapshots WHERE game_id=%s",
    "UPDATE games SET game_date='2026-10-09T00:00:00Z' WHERE game_id=%s",
])
def test_active_stale_writes_refuse(db,sql):
    pair=seed(db);activate_sql(db,pair)
    with pytest.raises(psycopg2.Error):query(db,'SET ROLE identity_runtime_test; '+sql,(pair[0],))


def test_safe_revoke_and_fresh_reactivate(db):
    pair=seed(db);case,event,_=activate_sql(db,pair)
    _,event2,_=activate_sql(db,pair,case=case,previous=event,sequence=2,action='REVOKE',evidence='b'*64)
    assert query(db,'SELECT count(*) FROM mlb_active_stale_identity_dispositions')==[(0,)]
    with pytest.raises(psycopg2.Error):activate_sql(db,pair,case=case,previous=event2,sequence=3,evidence='b'*64)
    activate_sql(db,pair,case=case,previous=event2,sequence=3,evidence='c'*64)
    assert query(db,'SELECT count(*) FROM mlb_active_stale_identity_dispositions')==[(1,)]


def test_revoke_refuses_survivor_history(db):
    pair=seed(db);case,event,_=activate_sql(db,pair)
    query(db,"INSERT INTO historical_games(game_id,mlb_game_id,game_date,home_team,away_team,home_score,away_score,home_win) VALUES(%s,900001,'2026-10-08','Chicago White Sox','Cleveland Guardians',2,1,TRUE)",(pair[1],))
    with pytest.raises(psycopg2.Error):activate_sql(db,pair,case=case,previous=event,sequence=2,action='REVOKE',evidence='b'*64)


def test_matching_active_vs_raw_and_new_candidate(db):
    from sportsmodel.ingest.game_matching import get_or_create_canonical_game, CanonicalGameIdentityConflictError
    pair=seed(db);activate_sql(db,pair)
    connection=db()
    try:
        with connection.cursor() as cursor:
            kwargs=dict(source_name='odds_api',external_game_id='synthetic-old',game_datetime=datetime(2026,10,9,tzinfo=timezone.utc),home_team_id=pair[2],away_team_id=pair[3])
            with pytest.raises(CanonicalGameIdentityConflictError):get_or_create_canonical_game(cursor,**kwargs)
            assert get_or_create_canonical_game(cursor,**kwargs,resolution_mode='RAW_ACQUISITION_CONTINUITY',provider_sport_key='baseball_mlb')==pair[0]
            kwargs['external_game_id']='synthetic-other'
            assert get_or_create_canonical_game(cursor,**kwargs,existing_only=True,persist_mapping=False)==pair[1]
    finally:
        connection.rollback();connection.close()


def test_knowledge_guard_not_retroactive(db):
    from sportsmodel.database.mlb_identity_disposition_repository import capture_identity_knowledge,install_identity_knowledge,IdentityDispositionError
    pair=seed(db);activate_sql(db,pair)
    with pytest.raises(psycopg2.Error):query(db,'SELECT mlb_identity_history_guard()')
    knowledge=capture_identity_knowledge(connection_factory=db)
    connection=db()
    try:
        with connection.cursor() as cursor:
            with pytest.raises(IdentityDispositionError):install_identity_knowledge(cursor,knowledge,cutoff_time=datetime(2026,10,8,tzinfo=timezone.utc))
            install_identity_knowledge(cursor,knowledge,cutoff_time=datetime.now(timezone.utc))
    finally:
        connection.rollback();connection.close()


def test_fences_monotonic_no_promotion(db):
    pair=seed(db)
    before=query(db,'SELECT mlb_identity_touch_fence(%s)',(pair[0],))[0][0]
    assert query(db,'SELECT mlb_identity_touch_fence(%s)',(pair[0],))[0][0]==before+1
    with pytest.raises(psycopg2.Error):query(db,'UPDATE mlb_game_identity_write_fences SET epoch=1')
    with pytest.raises(psycopg2.Error):query(db,'TRUNCATE mlb_game_identity_write_fences')
    with pytest.raises(psycopg2.Error):query(db,'SELECT mlb_identity_gate(false); SELECT mlb_identity_gate(true)')


def test_unrelated_shared_table_write_semantics(db):
    # Generic unrelated participants, not NFL-specific fixtures or assumptions.
    h,a=[r[0] for r in query(db,"INSERT INTO teams(team_name) VALUES('Unrelated Home'),('Unrelated Away') RETURNING team_id")]
    gid=query(db,"SET ROLE identity_runtime_test; INSERT INTO games(game_date,home_team_id,away_team_id) VALUES('2027-01-01',%s,%s) RETURNING game_id",(h,a))[0][0]
    assert query(db,'SELECT home_team_id,away_team_id FROM games WHERE game_id=%s',(gid,))==[(h,a)]
    assert query(db,'SELECT count(*) FROM mlb_game_identity_write_fences WHERE game_id=%s',(gid,))==[(0,)]


def evidence_request(db,pair,*,anchor=False,nonce='initial',action='ACTIVATE'):
    from sportsmodel.database.mlb_operator_guard import OperatorTarget,canonical_json
    s,c,h,a=pair
    sources=query(db,'SELECT game_source_id,game_id,source_name,external_game_id FROM game_sources WHERE game_id=ANY(%s) ORDER BY game_source_id',([s,c],))
    obs=[r[0] for r in query(db,"SELECT odds_provider_event_observation_id FROM odds_provider_event_observations WHERE external_event_id IN ('synthetic-old','synthetic-new') ORDER BY 1")]
    snapshots=[r[0] for r in query(db,'SELECT odds_market_snapshot_id FROM odds_market_snapshots WHERE game_id=ANY(%s) ORDER BY 1',([s,c],))]
    game=dict(gamePk=900001,gameType='D',ifNecessary='N',gameDate='2026-10-09T00:00:00Z',
              officialDate='2026-10-08',doubleHeader='N',gameNumber=1,scheduledInnings=9,
              status=dict(abstractGameState='Final',detailedState='Final',startTimeTBD=False),
              teams=dict(home=dict(team=dict(id=145,name='Chicago White Sox')),
                         away=dict(team=dict(id=114,name='Cleveland Guardians'))))
    payload=canonical_json(dict(dates=[dict(date='2026-10-08',games=[game])])).encode()
    stream=BytesIO()
    with zipfile.ZipFile(stream,'w') as archive:
        archive.writestr('mlb_schedule.json',payload)
        archive.writestr('synthetic_approval.json',canonical_json(dict(nonce=nonce,synthetic_only=True)))
    evidence=stream.getvalue()
    request=dict(format='MLB_IDENTITY_DISPOSITION_EXECUTABLE_V1',version=1,domain='MLB',action=action,
                 subject_game_id=s,survivor_game_id=c,game_pk=900001,target_date='2026-10-08',
                 expected_start='2026-10-09T00:00:00Z',home_team_id=h,away_team_id=a,
                 reason='Synthetic bounded fixture',policy_version='1.0.0',evidence_reference='Synthetic isolated evidence',
                 evidence_sha256=sha256(evidence).hexdigest(),mlb_payload_entry='mlb_schedule.json',
                 mlb_payload_sha256=sha256(payload).hexdigest(),operator_identity='synthetic-test-operator',
                 tool_identity='synthetic-test-tool',implementation_commit=COMMIT,
                 expected_sources=[dict(zip(('game_source_id','game_id','source_name','external_game_id'),r)) for r in sources],
                 expected_observation_ids=obs,expected_snapshot_ids=snapshots,allow_survivor_anchor=anchor)
    identity=query(db,"SELECT host(inet_server_addr()),inet_server_port(),pg_postmaster_start_time(),(pg_control_system()).system_identifier::text")[0]
    target=OperatorTarget(host='127.0.0.1',port=PORT,database=DATABASE,server_address=identity[0],server_port=identity[1],
                          postmaster_started_at=identity[2].isoformat(),identity_kind='isolated',system_identifier=identity[3])
    return canonical_json(request).encode(),evidence,target


def test_operator_zero_write_execute_exact_replay(db):
    from sportsmodel.operations.mlb_identity_disposition import preview_disposition,execute_disposition
    pair=seed(db);raw,evidence,target=evidence_request(db,pair)
    before=query(db,'SELECT game_id,epoch FROM mlb_game_identity_write_fences ORDER BY 1')
    preview=preview_disposition(request_bytes=raw,evidence_bytes=evidence,target=target,connection_factory=db)
    assert before==query(db,'SELECT game_id,epoch FROM mlb_game_identity_write_fences ORDER BY 1')
    assert query(db,'SELECT count(*) FROM game_identity_disposition_events')==[(0,)]
    kwargs=dict(request_bytes=raw,evidence_bytes=evidence,target=target,connection_factory=db,
                preview=preview,approved_preview_sha256=preview['preview_sha256'],acknowledge_writes=True)
    receipt=execute_disposition(**kwargs)
    replay=execute_disposition(**kwargs)
    assert receipt['event_id']==replay['event_id'] and replay['replay']
    assert query(db,'SELECT count(*) FROM game_identity_disposition_events')==[(1,)]
    SCENARIO_EVIDENCE.append(dict(scenario='operator_preview_execute_replay',preview=preview,receipt=receipt,replay=replay))


def test_operator_optional_anchor_requires_separate_authority(db):
    from sportsmodel.operations.mlb_identity_disposition import preview_disposition,execute_disposition
    from sportsmodel.database.mlb_operator_guard import OperatorRefusal
    pair=seed(db)
    query(db,"DELETE FROM game_sources WHERE game_id=%s AND source_name='mlb_stats'",(pair[1],))
    raw,evidence,target=evidence_request(db,pair,anchor=True)
    preview=preview_disposition(request_bytes=raw,evidence_bytes=evidence,target=target,connection_factory=db)
    kwargs=dict(request_bytes=raw,evidence_bytes=evidence,target=target,connection_factory=db,
                preview=preview,approved_preview_sha256=preview['preview_sha256'],acknowledge_writes=True)
    with pytest.raises(OperatorRefusal,match='anchor'):execute_disposition(**kwargs)
    execute_disposition(**kwargs,acknowledge_survivor_anchor=True)
    assert query(db,"SELECT game_id FROM game_sources WHERE source_name='mlb_stats' AND external_game_id='900001'")==[(pair[1],)]


def test_changed_fence_invalidates_preview(db):
    from sportsmodel.operations.mlb_identity_disposition import preview_disposition,execute_disposition
    from sportsmodel.database.mlb_operator_guard import OperatorRefusal
    pair=seed(db);raw,evidence,target=evidence_request(db,pair)
    preview=preview_disposition(request_bytes=raw,evidence_bytes=evidence,target=target,connection_factory=db)
    query(db,'SELECT mlb_identity_touch_fence(%s)',(pair[0],))
    with pytest.raises(OperatorRefusal,match='state changed'):execute_disposition(request_bytes=raw,evidence_bytes=evidence,
        target=target,connection_factory=db,preview=preview,approved_preview_sha256=preview['preview_sha256'],acknowledge_writes=True)
    assert query(db,'SELECT count(*) FROM game_identity_dispositions')==[(0,)]


@pytest.mark.parametrize('change',['predecessor','sequence','action','self','fixed_survivor'])
def test_structural_state_integrity(db,change):
    pair=seed(db)
    if change=='self':
        with pytest.raises(psycopg2.Error):activate_sql(db,(pair[0],pair[0],pair[2],pair[3]))
        return
    case,event,_=activate_sql(db,pair)
    if change=='fixed_survivor':
        with pytest.raises(psycopg2.Error):query(db,'UPDATE game_identity_dispositions SET survivor_game_id=subject_game_id')
        return
    options=dict(case=case,previous=event,sequence=2,action='REVOKE',evidence='b'*64)
    if change=='predecessor':options['previous']=event+10
    if change=='sequence':options['sequence']=3
    if change=='action':options['action']='ACTIVATE'
    with pytest.raises(psycopg2.Error):activate_sql(db,pair,**options)


def test_old_repeatable_read_snapshot_writer_refuses(db):
    pair=seed(db);writer=db();writer.set_session(isolation_level='REPEATABLE READ')
    try:
        with writer.cursor() as cursor:
            cursor.execute('SELECT mlb_identity_ledger_fingerprint()');old=cursor.fetchone()[0]
            activate_sql(db,pair)
            with pytest.raises(psycopg2.errors.SerializationFailure):
                cursor.execute("INSERT INTO historical_games(game_id,mlb_game_id,game_date,home_team,away_team,home_score,away_score,home_win) VALUES(%s,900002,'2026-10-08','Chicago White Sox','Cleveland Guardians',2,1,TRUE)",(pair[0],))
        SCENARIO_EVIDENCE.append(dict(scenario='old_snapshot_writer',old_ledger=old,refused='SerializationFailure',no_retry=True))
    finally:
        writer.rollback();writer.close()


def _wait_for_gate_waiter(db):
    end=time.monotonic()+1.0
    while time.monotonic()<end:
        if query(db,"SELECT count(*) FROM pg_locks WHERE locktype='advisory' AND classid=1397574724 AND objid=34 AND NOT granted")[0][0]:return
        time.sleep(.01)
    raise AssertionError('Concurrent waiter was not observed')


def test_dependency_writer_vs_activation_gate(db):
    pair=seed(db);writer=db();errors=[]
    try:
        with writer.cursor() as cursor:
            cursor.execute('SELECT mlb_identity_gate(false)')
            cursor.execute("INSERT INTO historical_games(game_id,mlb_game_id,game_date,home_team,away_team,home_score,away_score,home_win) VALUES(%s,900002,'2026-10-08','Chicago White Sox','Cleveland Guardians',2,1,TRUE)",(pair[0],))
        def other():
            try:activate_sql(db,pair)
            except psycopg2.Error as error:errors.append(type(error).__name__)
        thread=threading.Thread(target=other);thread.start();_wait_for_gate_waiter(db);writer.commit();thread.join(3)
        assert not thread.is_alive() and errors
        assert query(db,'SELECT count(*) FROM game_identity_dispositions')==[(0,)]
        assert query(db,'SELECT count(*) FROM historical_games WHERE game_id=%s',(pair[0],))==[(1,)]
        SCENARIO_EVIDENCE.append(dict(scenario='dependency_writer_wins',activation_errors=errors,partial_ledger=False))
    finally:
        writer.rollback();writer.close()


def test_activation_vs_unrelated_writer_bounded_coupling(db):
    pair=seed(db);activation=db();activation.set_session(isolation_level='SERIALIZABLE');result=[]
    try:
        activate_sql(db,pair,connection=activation,commit=False)
        def other():
            started=time.monotonic()
            query(db,"INSERT INTO teams(team_name) VALUES('Unrelated Delayed Team')")
            result.append(time.monotonic()-started)
        thread=threading.Thread(target=other);thread.start();_wait_for_gate_waiter(db);activation.commit();thread.join(3)
        assert not thread.is_alive() and len(result)==1 and result[0]<2.0
        assert query(db,"SELECT count(*) FROM teams WHERE team_name='Unrelated Delayed Team'")==[(1,)]
        SCENARIO_EVIDENCE.append(dict(scenario='unrelated_shared_table_coupling',observed_waiter=True,elapsed_seconds=result[0],semantic_change=False))
    finally:
        activation.rollback();activation.close()


@pytest.mark.parametrize('step',['anchor','case','event','return'])
def test_operator_faults_rollback_all(db,step):
    from sportsmodel.operations.mlb_identity_disposition import preview_disposition,execute_disposition
    pair=seed(db);query(db,"DELETE FROM game_sources WHERE game_id=%s AND source_name='mlb_stats'",(pair[1],))
    raw,evidence,target=evidence_request(db,pair,anchor=True)
    preview=preview_disposition(request_bytes=raw,evidence_bytes=evidence,target=target,connection_factory=db)
    class Cursor:
        def __init__(self,inner):self.inner=inner;self.event=False
        def __enter__(self):return self
        def __exit__(self,*args):self.inner.close()
        def __getattr__(self,name):return getattr(self.inner,name)
        def execute(self,sql,params=None):
            marker={'anchor':'INSERT INTO game_sources','case':'INSERT INTO game_identity_dispositions','event':'INSERT INTO game_identity_disposition_events'}.get(step)
            if marker and marker in sql:raise RuntimeError('Synthetic mutation-step fault')
            self.event='INSERT INTO game_identity_disposition_events' in sql
            return self.inner.execute(sql,params)
        def fetchone(self):
            if step=='return' and self.event:raise RuntimeError('Synthetic post-event fault')
            return self.inner.fetchone()
    class Connection:
        def __init__(self):self.inner=db()
        def __getattr__(self,name):return getattr(self.inner,name)
        def cursor(self):return Cursor(self.inner.cursor())
    with pytest.raises(RuntimeError):execute_disposition(request_bytes=raw,evidence_bytes=evidence,target=target,
        connection_factory=Connection,preview=preview,approved_preview_sha256=preview['preview_sha256'],
        acknowledge_writes=True,acknowledge_survivor_anchor=True)
    assert query(db,'SELECT count(*) FROM game_identity_dispositions')==[(0,)]
    assert query(db,'SELECT count(*) FROM game_identity_disposition_events')==[(0,)]
    assert query(db,"SELECT count(*) FROM game_sources WHERE game_id=%s AND source_name='mlb_stats'",(pair[1],))==[(0,)]


@pytest.mark.parametrize('change',['trigger','function','view','view_body','migration'])
def test_catalog_capabilities_fail_closed(db,change):
    from sportsmodel.database.mlb_identity_disposition_repository import require_schema034,IdentityDispositionError
    require_schema034(db)
    if change=='trigger':query(db,'ALTER TABLE game_sources DISABLE TRIGGER mlb_identity_write_guard')
    elif change=='function':query(db,"CREATE OR REPLACE FUNCTION mlb_identity_is_stale(gid integer) RETURNS boolean LANGUAGE sql AS 'SELECT false'")
    elif change=='view':query(db,'DROP VIEW mlb_active_stale_identity_dispositions CASCADE')
    elif change=='view_body':query(db,"CREATE OR REPLACE VIEW mlb_active_stale_identity_dispositions AS SELECT d.*,e.event_id,e.sequence,e.created_at AS state_recorded_at,e.approved_manifest_sha256 FROM game_identity_dispositions d JOIN game_identity_disposition_events e USING(disposition_id) WHERE false")
    else:query(db,'DELETE FROM schema_migrations WHERE version=34')
    with pytest.raises((IdentityDispositionError,psycopg2.Error)):require_schema034(db)


def test_lost_commit_acknowledgement_has_read_only_receipt(db):
    from sportsmodel.operations.mlb_identity_disposition import preview_disposition,execute_disposition,inspect_receipt
    from sportsmodel.database.mlb_operator_guard import OperatorRefusal
    pair=seed(db);raw,evidence,target=evidence_request(db,pair)
    preview=preview_disposition(request_bytes=raw,evidence_bytes=evidence,target=target,connection_factory=db)
    class LostAck:
        def __init__(self):self.inner=db();self.commits=0
        def __getattr__(self,name):return getattr(self.inner,name)
        def commit(self):
            self.commits+=1;self.inner.commit()
            raise psycopg2.OperationalError('Synthetic lost commit acknowledgement')
    connection=LostAck()
    with pytest.raises(OperatorRefusal,match='UNKNOWN'):execute_disposition(request_bytes=raw,evidence_bytes=evidence,target=target,
        connection_factory=lambda:connection,preview=preview,approved_preview_sha256=preview['preview_sha256'],acknowledge_writes=True)
    assert connection.commits==1
    result=inspect_receipt(approved_manifest_sha256=preview['preview_sha256'],target=target,connection_factory=db)
    assert result['status']=='COMMITTED_RECEIPT_FOUND' and result['current_postconditions_match'] and not result['retry_authorized']
    SCENARIO_EVIDENCE.append(dict(scenario='lost_commit_ack',result=result,automatic_retries=0))


def test_reconciliation_disposition_only_split_exception(db):
    from sportsmodel.operations.mlb_reconcile import preview_reconciliation
    from sportsmodel.database.mlb_operator_guard import canonical_json,OperatorRefusal
    pair=seed(db);raw,evidence,target=evidence_request(db,pair)
    request=json.loads(raw)
    with zipfile.ZipFile(BytesIO(evidence)) as archive:payload=archive.read('mlb_schedule.json')
    sources=[dict(source_name=r['source_name'],external_game_id=r['external_game_id']) for r in request['expected_sources'] if r['game_id']==pair[1]]
    allow=canonical_json(dict(version=1,domain='MLB',target_date='2026-10-08',payload_sha256=sha256(payload).hexdigest(),
        games=[dict(game_pk=900001,home_team='Chicago White Sox',away_team='Cleveland Guardians',expected_start='2026-10-09T00:00:00Z',
                    existing_game_id=pair[1],current_sources=sources,resulting_sources=sources)])).encode()
    with pytest.raises(OperatorRefusal,match='Split'):preview_reconciliation(payload_bytes=payload,allowlist_bytes=allow,target=target,connection_factory=db)
    activate_sql(db,pair)
    preview=preview_reconciliation(payload_bytes=payload,allowlist_bytes=allow,target=target,connection_factory=db)
    assert len(preview['plans'])==1 and preview['plans'][0]['game_id']==pair[1]
    query(db,"INSERT INTO games(game_date,home_team_id,away_team_id) VALUES('2026-10-08T22:00:00Z',%s,%s)",pair[2:])
    with pytest.raises(OperatorRefusal,match='Split'):preview_reconciliation(payload_bytes=payload,allowlist_bytes=allow,target=target,connection_factory=db)
    SCENARIO_EVIDENCE.append(dict(scenario='strict_reconciliation_after_disposition',preview=preview,unaudited_split_refused=True))


def test_survivor_snapshot_cannot_be_stale_actionable_evidence(db):
    pair=seed(db);activate_sql(db,pair);s,c,h,a=pair
    run=query(db,"INSERT INTO moneyline_prediction_runs(target_date,model_version,feature_schema_version,model_artifact_sha256,run_type) VALUES('2026-10-08','synthetic-not-a-model','synthetic',%s,'preview') RETURNING moneyline_prediction_run_id",(HASH,))[0][0]
    def prediction(gid):
        return query(db,"INSERT INTO moneyline_game_predictions(moneyline_prediction_run_id,game_id,mlb_game_id,game_start_time,prediction_time,home_team_id,away_team_id,home_starter_features_available,away_starter_features_available,starter_coverage,missing_raw_value_count,home_win_probability,away_win_probability,predicted_team_id,predicted_probability) VALUES(%s,%s,900001,'2026-10-09T00:00:00Z','2026-10-08T12:00:00Z',%s,%s,false,false,'none',0,0.6,0.4,%s,0.6) RETURNING moneyline_game_prediction_id",(run,gid,h,a,h))[0][0]
    with pytest.raises(psycopg2.Error,match='active stale'):prediction(s)
    pred=prediction(c)
    market,odds,book=query(db,'SELECT odds_market_snapshot_id,odds_ingestion_run_id,sportsbook_id FROM odds_market_snapshots WHERE game_id=%s',(s,))[0]
    sql="""INSERT INTO moneyline_prediction_market_evaluations(moneyline_game_prediction_id,odds_ingestion_run_id,odds_market_snapshot_id,sportsbook_id,snapshot_time,selection_name,price,model_probability,market_no_vig_probability,sportsbook_count,implied_probability,model_market_edge,model_price_edge,model_expected_value,starter_coverage,home_starter_features_available,away_starter_features_available,policy_version,qualifies_as_paper_candidate,disqualification_reasons,starter_match_status)
    VALUES(%s,%s,%s,%s,'2026-10-08T12:01:00Z','Chicago White Sox',-110,0.6,0.5,1,0.5,0.1,0.1,0.2,'none',false,false,'synthetic',false,ARRAY['synthetic']::text[],'matched')"""
    with pytest.raises(psycopg2.Error,match='active stale'):query(db,'SET ROLE identity_runtime_test; '+sql,(pred,odds,market,book))
    assert query(db,'SELECT count(*) FROM moneyline_prediction_market_evaluations')==[(0,)]


def test_h1_survivor_remains_incomplete_after_disposition(db):
    from sportsmodel.database.mlb_identity_disposition_repository import capture_identity_knowledge
    from sportsmodel.operations.mlb_history_check import check_feature_history
    from zoneinfo import ZoneInfo
    pair=seed(db);activate_sql(db,pair)
    day=(datetime.now(timezone.utc).astimezone(ZoneInfo('America/Los_Angeles'))+timedelta(days=1)).date()
    when=datetime(day.year,day.month,day.day,17,tzinfo=ZoneInfo('America/Los_Angeles'))
    target_game=query(db,'INSERT INTO games(game_date,home_team_id,away_team_id) VALUES(%s,%s,%s) RETURNING game_id',(when,pair[2],pair[3]))[0][0]
    query(db,"INSERT INTO game_sources(game_id,source_name,external_game_id) VALUES(%s,'mlb_stats','900003')",(target_game,))
    players=[r[0] for r in query(db,"INSERT INTO baseball_players(full_name) VALUES('Synthetic Starter One'),('Synthetic Starter Two') RETURNING baseball_player_id")]
    query(db,"INSERT INTO baseball_player_sources(baseball_player_id,source_name,external_player_id) VALUES(%s,'mlb_stats','100'),(%s,'mlb_stats','200')",tuple(players))
    knowledge=capture_identity_knowledge(connection_factory=db)
    _,_,target=evidence_request(db,pair)
    cutoff=query(db,'SELECT clock_timestamp()')[0][0]
    result=check_feature_history(target_date=day,target_game_ids=(target_game,),starting_pitcher_ids=tuple(players),
        cutoff_time=cutoff,target=target,connection_factory=db,identity_knowledge=knowledge)
    assert result['status']=='FAIL' and pair[0] not in result['required_canonical_game_ids'] and pair[1] in result['required_canonical_game_ids']
    SCENARIO_EVIDENCE.append(dict(scenario='h1_incomplete_survivor',report=result,knowledge=knowledge.body()))


def test_existing_stale_raw_event_can_append_without_transfer(db):
    pair=seed(db);activate_sql(db,pair)
    old=query(db,'SELECT to_jsonb(t)::text FROM odds_market_snapshots t WHERE game_id=%s ORDER BY 1',(pair[0],))
    run=query(db,"INSERT INTO odds_ingestion_runs(source_name,sport,status,snapshot_role,started_at,request_started_at,response_received_at,status_code,request_path,request_regions,request_markets,request_odds_format) VALUES('odds_api','baseball_mlb','running','manual','2026-10-08T03:00:00Z','2026-10-08T03:00:00Z','2026-10-08T03:00:01Z',200,'synthetic','us','h2h','american') RETURNING odds_ingestion_run_id")[0][0]
    obs=query(db,"INSERT INTO odds_provider_event_observations(odds_ingestion_run_id,source_name,provider_sport_key,external_event_id,provider_commence_time,provider_home_team_name,provider_away_team_name,observed_at) VALUES(%s,'odds_api','baseball_mlb','synthetic-old','2026-10-09T00:00:00Z','Chicago White Sox','Cleveland Guardians','2026-10-08T03:00:01Z') RETURNING odds_provider_event_observation_id",(run,))[0][0]
    book,provider=query(db,'SELECT sportsbook_id,sportsbook_provider_identity_id FROM sportsbook_provider_identities')[0]
    query(db,"INSERT INTO odds_market_snapshots(game_id,sportsbook_id,market_type,selection_name,price,snapshot_time,source_name,odds_ingestion_run_id,odds_provider_event_observation_id,sportsbook_provider_identity_id,bookmaker_title_at_observation,observed_at) VALUES(%s,%s,'h2h','Chicago White Sox',-120,'2026-10-08T03:00:01Z','odds_api',%s,%s,%s,'Synthetic Test Book','2026-10-08T03:00:01Z')",(pair[0],book,run,obs,provider))
    assert query(db,'SELECT game_id,raw_acquisition_game_id,effective_game_id FROM odds_market_snapshots_effective WHERE odds_provider_event_observation_id=%s',(obs,))==[(pair[0],pair[0],pair[0])]
    assert query(db,'SELECT game_date FROM games WHERE game_id=%s',(pair[0],))[0][0]==datetime(2026,10,8,21,tzinfo=timezone.utc)
    assert old[0] in query(db,'SELECT to_jsonb(t)::text FROM odds_market_snapshots t WHERE game_id=%s ORDER BY 1',(pair[0],))


def test_fence_overflow_refuses(db):
    pair=seed(db)
    query(db,'ALTER TABLE mlb_game_identity_write_fences DISABLE TRIGGER mlb_fence_row; UPDATE mlb_game_identity_write_fences SET epoch=9223372036854775807; ALTER TABLE mlb_game_identity_write_fences ENABLE TRIGGER mlb_fence_row')
    with pytest.raises(psycopg2.Error,match='overflow'):query(db,'SELECT mlb_identity_touch_fence(%s)',(pair[0],))
    assert query(db,'SELECT epoch FROM mlb_game_identity_write_fences WHERE game_id=%s',(pair[0],))==[(9223372036854775807,)]


@pytest.mark.parametrize('second',['reverse','chain'])
def test_concurrent_cycle_chain_proposals_cannot_both_activate(db,second):
    pair=seed(db);s,c,h,a=pair
    if second=='reverse':other=(c,s,h,a)
    else:
        third=query(db,"INSERT INTO games(game_date,home_team_id,away_team_id) VALUES('2026-10-09T01:00:00Z',%s,%s) RETURNING game_id",(h,a))[0][0]
        query(db,"INSERT INTO game_sources(game_id,source_name,external_game_id) VALUES(%s,'mlb_stats','900004')",(third,))
        other=(c,third,h,a)
    barrier=threading.Barrier(2);results=[]
    def attempt(proposal,evidence):
        barrier.wait()
        try:activate_sql(db,proposal,evidence=evidence);results.append('committed')
        except psycopg2.Error:results.append('refused')
    threads=[threading.Thread(target=attempt,args=(pair,HASH)),threading.Thread(target=attempt,args=(other,'b'*64))]
    for thread in threads:thread.start()
    for thread in threads:thread.join(3)
    assert all(not thread.is_alive() for thread in threads)
    assert sorted(results)==['committed','refused']
    assert query(db,'SELECT count(*) FROM mlb_active_stale_identity_dispositions')==[(1,)]
    SCENARIO_EVIDENCE.append(dict(scenario='concurrent_'+second,results=results,
        note='Market-only/unique-MLB-anchor preconditions remain enabled; not weakened to manufacture a graph.'))


def test_stale_recovery_target_and_settlement_refuse(db):
    from sportsmodel.database.mlb_recovery_repository import load_mlb_identity
    pair=seed(db);activate_sql(db,pair)
    with pytest.raises(psycopg2.Error,match='active stale'):
        query(db,"INSERT INTO moneyline_paper_candidate_settlements(moneyline_prediction_market_evaluation_id,game_id,home_score,away_score,outcome,profit_units) VALUES(999,%s,2,1,'win',1)",(pair[0],))
    connection=db()
    try:
        with connection.cursor() as cursor:
            identity=load_mlb_identity(cursor,900001)
            assert identity['game_id']==pair[1]
            with pytest.raises(ValueError,match='exactly one raw mapping'):load_mlb_identity(cursor,900999)
            with pytest.raises(psycopg2.Error):cursor.execute('SELECT mlb_identity_assert_active(%s)',(pair[0],))
    finally:
        connection.rollback();connection.close()


def test_prediction_knowledge_metadata_does_not_backfill_old_runs(db):
    pair=seed(db)
    run=query(db,"INSERT INTO moneyline_prediction_runs(target_date,model_version,feature_schema_version,model_artifact_sha256,run_type) VALUES('2026-10-08','synthetic','synthetic',%s,'preview') RETURNING moneyline_prediction_run_id",(HASH,))[0][0]
    activate_sql(db,pair)
    assert query(db,'SELECT identity_disposition_knowledge FROM moneyline_prediction_runs WHERE moneyline_prediction_run_id=%s',(run,))==[(None,)]
    with pytest.raises(psycopg2.Error):query(db,"UPDATE moneyline_prediction_runs SET identity_disposition_knowledge='{}' WHERE moneyline_prediction_run_id=%s",(run,))


def test_later_revoke_invalidates_committed_knowledge(db):
    from sportsmodel.database.mlb_identity_disposition_repository import capture_identity_knowledge,install_identity_knowledge
    pair=seed(db);case,event,_=activate_sql(db,pair)
    knowledge=capture_identity_knowledge(connection_factory=db)
    activate_sql(db,pair,case=case,previous=event,sequence=2,action='REVOKE',evidence='b'*64)
    connection=db()
    try:
        with connection.cursor() as cursor:
            with pytest.raises(psycopg2.Error,match='changed committed'):
                install_identity_knowledge(cursor,knowledge,cutoff_time=datetime.now(timezone.utc))
    finally:
        connection.rollback();connection.close()


def test_prohibited_stale_history_is_not_hidden_by_filter(db):
    from sportsmodel.database.mlb_identity_disposition_repository import capture_identity_knowledge,install_identity_knowledge
    pair=seed(db);activate_sql(db,pair)
    # Controlled corrupt-state fixture; guards restored before the audit. Do not
    # relax real activation/write preconditions to manufacture this state.
    query(db,"ALTER TABLE historical_games DISABLE TRIGGER mlb_identity_write_guard; INSERT INTO historical_games(game_id,mlb_game_id,game_date,home_team,away_team,home_score,away_score,home_win) VALUES(%s,900002,'2026-10-08','Chicago White Sox','Cleveland Guardians',2,1,TRUE); ALTER TABLE historical_games ENABLE TRIGGER mlb_identity_write_guard",(pair[0],))
    knowledge=capture_identity_knowledge(connection_factory=db)
    connection=db()
    try:
        with connection.cursor() as cursor:
            with pytest.raises(psycopg2.Error,match='invariant violated'):
                install_identity_knowledge(cursor,knowledge,cutoff_time=datetime.now(timezone.utc))
    finally:
        connection.rollback();connection.close()


def test_stale_team_and_pitching_rows_refuse_before_constraints(db):
    pair=seed(db);activate_sql(db,pair)
    for table in ('team_game_statistics','player_game_pitching_statistics'):
        with pytest.raises(psycopg2.Error,match='active stale'):
            query(db,'SET ROLE identity_runtime_test; INSERT INTO '+table+'(game_id) VALUES(%s)',(pair[0],))


def test_concurrent_activation_does_not_publish_partial_reconciliation(db):
    from sportsmodel.operations.mlb_reconcile import preview_reconciliation
    from sportsmodel.database.mlb_operator_guard import canonical_json,OperatorRefusal
    pair=seed(db);raw,evidence,target=evidence_request(db,pair)
    request=json.loads(raw)
    with zipfile.ZipFile(BytesIO(evidence)) as archive:payload=archive.read('mlb_schedule.json')
    sources=[dict(source_name=r['source_name'],external_game_id=r['external_game_id']) for r in request['expected_sources'] if r['game_id']==pair[1]]
    allow=canonical_json(dict(version=1,domain='MLB',target_date='2026-10-08',payload_sha256=sha256(payload).hexdigest(),games=[dict(game_pk=900001,home_team='Chicago White Sox',away_team='Cleveland Guardians',expected_start='2026-10-09T00:00:00Z',existing_game_id=pair[1],current_sources=sources,resulting_sources=sources)])).encode()
    activation=db();activation.set_session(isolation_level='SERIALIZABLE')
    try:
        activate_sql(db,pair,connection=activation,commit=False)
        with pytest.raises(OperatorRefusal,match='Split'):
            preview_reconciliation(payload_bytes=payload,allowlist_bytes=allow,target=target,connection_factory=db)
        activation.commit()
        result=preview_reconciliation(payload_bytes=payload,allowlist_bytes=allow,target=target,connection_factory=db)
        assert result['plans'][0]['game_id']==pair[1]
        SCENARIO_EVIDENCE.append(dict(scenario='concurrent_activation_reconciliation',partial_state_refused=True,committed_state_preview=result['preview_sha256']))
    finally:
        activation.rollback();activation.close()


def test_caller_backdated_ledger_timestamp_refused(db):
    pair=seed(db);s,c,_,_=pair
    with pytest.raises(psycopg2.Error,match='Caller timestamps'):
        query(db,"INSERT INTO game_identity_dispositions(domain,subject_game_id,survivor_game_id,disposition_type,policy_version,reason,evidence_reference,evidence_sha256,operator_identity,tool_identity,implementation_commit,implementation_sha256,initial_manifest_sha256,created_at) VALUES('MLB',%s,%s,'STALE_MARKET_ONLY_DUPLICATE','1.0.0','synthetic','synthetic',%s,'synthetic','synthetic',%s,%s,%s,'2026-10-08')",(s,c,HASH,COMMIT,HASH,HASH))


def test_boxscore_target_refuses_before_provider(db,monkeypatch):
    from sportsmodel.ingest import boxscore_ingestion
    pair=seed(db);activate_sql(db,pair)
    monkeypatch.setattr(boxscore_ingestion,'fetch_live_feed',lambda *a:pytest.fail('Provider reached'))
    monkeypatch.setattr(boxscore_ingestion,'fetch_boxscore',lambda *a:pytest.fail('Provider reached'))
    with pytest.raises(ValueError,match='target differs'):
        boxscore_ingestion.ingest_boxscore(game_id=pair[0],game_pk=900001,connection_factory=db)


def test_uncovered_semantic_dependency_refuses_preflight(db):
    from sportsmodel.database.mlb_identity_disposition_repository import require_schema034,IdentityDispositionError
    query(db,'CREATE TABLE synthetic_uncovered_decision(game_id integer)')
    with pytest.raises(IdentityDispositionError,match='Uncovered semantic'):
        require_schema034(db)


def test_exact_reviewed_pair_ids_are_synthetic_only(db):
    pair=seed(db,reviewed_ids=True)
    assert pair[:2]==(11408,11409)
    before=query(db,'SELECT to_jsonb(t)::text FROM odds_market_snapshots t ORDER BY odds_market_snapshot_id')
    activate_sql(db,pair)
    assert query(db,'SELECT subject_game_id,survivor_game_id FROM mlb_active_stale_identity_dispositions')==[(11408,11409)]
    assert query(db,'SELECT to_jsonb(t)::text FROM odds_market_snapshots t ORDER BY odds_market_snapshot_id')==before
    SCENARIO_EVIDENCE.append(dict(scenario='synthetic_11408_11409',pair=[11408,11409],provider_id='900001',raw_equal=True,
        authority='Only disposable synthetic rows; no production request or authorization created'))


@pytest.mark.parametrize('repository',['team','pitcher','bullpen'])
def test_empty_feature_window_cannot_skip_knowledge_guard(db,repository):
    from sportsmodel.database.team_statistics_repository import PostgresTeamStatisticsRepository
    from sportsmodel.database.pitcher_statistics_repository import PostgresPitcherStatisticsRepository
    from sportsmodel.database.bullpen_statistics_repository import PostgresBullpenStatisticsRepository
    seed_pair=seed(db);activate_sql(db,seed_pair)
    cutoff=datetime.now(timezone.utc)
    with pytest.raises(psycopg2.Error,match='Missing/unavailable'):
        if repository=='team':
            PostgresTeamStatisticsRepository(connection_factory=db).get_completed_games_before(team_id=seed_pair[2],cutoff_time=cutoff,limit=200)
        elif repository=='pitcher':
            PostgresPitcherStatisticsRepository(connection_factory=db).get_completed_starts_before(player_id=999,cutoff_time=cutoff,limit=50)
        else:
            PostgresBullpenStatisticsRepository(connection_factory=db).get_completed_relief_appearances_before(team_id=seed_pair[2],cutoff_time=cutoff)
