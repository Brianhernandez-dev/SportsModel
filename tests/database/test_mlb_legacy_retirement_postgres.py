"""Explicit fresh PG16 successor verification. All identities/evidence synthetic."""
from datetime import datetime,date,timezone,timedelta
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import json,os,subprocess,threading,time,zipfile
import psycopg2
import pytest

ROOT=Path(__file__).resolve().parents[2]
NAME='sportsmodel-retirement-170-20261011-35'
PORT=55448
DATABASE='sportsmodel_test_retirement170_35'
pytestmark=pytest.mark.skipif(os.getenv('SPORTSMODEL_RETIREMENT_DISPOSABLE_CONTAINER')!=NAME,
    reason='requires explicitly verified fresh retirement170 isolatedPG16')
SCENARIO_EVIDENCE=[]


@pytest.fixture
def db():
    result=subprocess.run(['docker','inspect',NAME],capture_output=True,check=True)
    item=json.loads(result.stdout)[0]
    assert item['Name']=='/'+NAME and item['Config']['Labels']['sportsmodel.verification']=='retirement-170'
    assert item['NetworkSettings']['Ports']['5432/tcp']==[dict(HostIp='127.0.0.1',HostPort=str(PORT))]
    assert len(item['Mounts'])==1 and item['Mounts'][0]['Name']==NAME+'-data' and item['Mounts'][0]['Destination']=='/var/lib/postgresql/data'
    password=next(v.split('=',1)[1] for v in item['Config']['Env'] if v.startswith('POSTGRES_PASSWORD='))
    def factory():
        c=psycopg2.connect(host='127.0.0.1',port=PORT,dbname=DATABASE,user='postgres',password=password,
            connect_timeout=5,options='-c lock_timeout=1500ms -c statement_timeout=15000ms')
        with c.cursor() as cur:
            cur.execute("SELECT current_database(),current_setting('server_version_num'),current_setting('data_directory')")
            database,version,storage=cur.fetchone()
            assert database==DATABASE and int(version)//10000==16 and storage=='/var/lib/postgresql/data'
        c.rollback();return c
    c=factory()
    try:
        with c.cursor() as cur:
            cur.execute('DROP SCHEMA public CASCADE; CREATE SCHEMA public')
            cur.execute((ROOT/'tests/fixtures/database/sportsmodel_foundation_schema.sql').read_text(encoding='utf-8-sig'))
            cur.execute('CREATE TABLE odds_snapshots(snapshot_id bigserial primary key,game_id integer references games(game_id),sportsbook_id integer references sportsbooks(sportsbook_id),market_type text not null,home_price integer,away_price integer,snapshot_time timestamp not null)')
            cur.execute('CREATE TABLE schema_migrations(version integer primary key,filename text not null unique,checksum char(64) not null)')
            paths=sorted((ROOT/'database/migrations').glob('*.sql'))
            assert [int(p.name[:3]) for p in paths]==list(range(1,36))
            for p in paths:
                if p.name.startswith('007_'):
                    cur.execute("INSERT INTO teams(team_name) VALUES('Synthetic Legacy Home'),('Synthetic Legacy Away'); INSERT INTO games(game_date,home_team_id,away_team_id) SELECT '2025-01-01',h.team_id,a.team_id FROM teams h,teams a WHERE h.team_name='Synthetic Legacy Home' AND a.team_name='Synthetic Legacy Away'; INSERT INTO sportsbooks(name) VALUES('Synthetic Legacy Book'); INSERT INTO odds_market_snapshots(game_id,sportsbook_id,market_type,selection_name,price,snapshot_time) SELECT game_id,sportsbook_id,'h2h','Synthetic Legacy Home',-110,'2025-01-01' FROM games,sportsbooks")
                sql=p.read_text(encoding='utf-8-sig');cur.execute(sql)
                cur.execute('INSERT INTO schema_migrations VALUES(%s,%s,%s)',(int(p.name[:3]),p.name,sha256(sql.encode()).hexdigest()))
        c.commit()
    finally:c.close()
    return factory


def query(db,sql,args=None):
    c=db()
    try:
        with c.cursor() as cur:cur.execute(sql,args);rows=cur.fetchall() if cur.description else None
        c.commit();return rows
    finally:c.close()


def stat(db,table,values):
    columns=query(db,"SELECT column_name,data_type FROM information_schema.columns WHERE table_schema='public' AND table_name=%s AND is_nullable='NO' AND column_default IS NULL ORDER BY ordinal_position",(table,))
    row={name:(False if kind=='boolean' else 0 if kind in('integer','smallint','bigint','numeric') else 'mlb_stats_api') for name,kind in columns}
    row.update(values)
    assert all(k.replace('_','').isalnum() for k in row)
    query(db,'INSERT INTO '+table+'('+','.join(row)+') VALUES('+','.join(['%s']*len(row))+')',tuple(row.values()))


def seed(db,identity_only=False):
    subject,survivor=(584,26) if identity_only else (29,586)
    home,away,home_external,away_external=('Miami Marlins','Cleveland Guardians',146,114) if identity_only else ('Chicago White Sox','Athletics',145,133)
    teams=[]
    for name,external in ((home,home_external),(away,away_external)):
        found=query(db,'SELECT team_id FROM teams WHERE team_name=%s',(name,))
        tid=found[0][0] if found else query(db,'INSERT INTO teams(team_name) VALUES(%s) RETURNING team_id',(name,))[0][0]
        query(db,"INSERT INTO baseball_team_sources(team_id,source_name,external_team_id) VALUES(%s,'mlb_stats',%s)",(tid,str(external)));teams.append(tid)
    h,a=teams;pk=900000+subject
    query(db,"INSERT INTO games(game_id,game_date,home_team_id,away_team_id,doubleheader_status,game_number) VALUES(%s,'2026-07-12T18:11:00Z',%s,%s,NULL,NULL),(%s,'2026-07-12T18:10:00Z',%s,%s,'single',1)",(subject,h,a,survivor,h,a))
    query(db,"INSERT INTO game_sources(game_id,source_name,external_game_id) VALUES(%s,'mlb_stats',%s)",(survivor,str(pk)))
    if not identity_only:
        query(db,"INSERT INTO game_sources(game_id,source_name,external_game_id) VALUES(%s,'odds_api',%s)",(subject,'synthetic-legacy-'+str(subject)))
        book=query(db,"INSERT INTO sportsbooks(name) VALUES('Synthetic Evidence Book') RETURNING sportsbook_id")[0][0]
        run=query(db,"INSERT INTO odds_ingestion_runs(source_name,sport,status,snapshot_role,started_at) VALUES('legacy_backfill','baseball_mlb','completed','legacy','2026-07-11T00:00:00Z') RETURNING odds_ingestion_run_id")[0][0]
        for i in range(96):
            query(db,"INSERT INTO odds_market_snapshots(game_id,sportsbook_id,market_type,selection_name,price,snapshot_time,source_name,odds_ingestion_run_id) VALUES(%s,%s,'h2h',%s,-110,%s,'odds_api',%s)",(subject,book,home,datetime(2026,7,11,tzinfo=timezone.utc)+timedelta(seconds=i),run))
        for i in range(8):query(db,"INSERT INTO odds_snapshots(game_id,sportsbook_id,market_type,home_price,away_price,snapshot_time) VALUES(%s,%s,'h2h',-110,110,%s)",(subject,book,datetime(2026,7,11)+timedelta(seconds=i)))
    query(db,"INSERT INTO historical_games(game_id,mlb_game_id,game_date,home_team,away_team,home_score,away_score,home_win) VALUES(%s,%s,'2026-07-12',%s,%s,3,1,TRUE)",(survivor,pk,home,away))
    for tid,is_home,runs,allowed in ((h,True,3,1),(a,False,1,3)):
        metrics=dict(pitching_outs=27,hits_allowed=5,runs_allowed=allowed,earned_runs_allowed=allowed,home_runs_allowed=0,walks_allowed=0,strikeouts_recorded=1)
        stat(db,'team_game_statistics',dict(game_id=survivor,team_id=tid,is_home=is_home,runs=runs,hits=5,at_bats=30,**metrics))
        player=query(db,"INSERT INTO baseball_players(full_name) VALUES('Synthetic Starter') RETURNING baseball_player_id")[0][0]
        # Positive decimal IDs are wholly synthetic, not real MLB identities.
        query(db,"INSERT INTO baseball_player_sources(baseball_player_id,source_name,external_player_id) VALUES(%s,'mlb_stats',%s)",(player,str(910000000+player)))
        metrics['strikeouts']=metrics.pop('strikeouts_recorded')
        stat(db,'player_game_pitching_statistics',dict(game_id=survivor,team_id=tid,baseball_player_id=player,appearance_order=1,is_starter=True,**metrics))
    return dict(subject=subject,survivor=survivor,h=h,a=a,pk=pk,home=home,away=away,home_external=home_external,away_external=away_external,
        category='IDENTITY_ONLY_DUPLICATE' if identity_only else 'LEGACY_MARKET_DUPLICATE_WITHOUT_OBSERVATION_PROVENANCE')


def request(db,pair,**changes):
    from sportsmodel.operations.mlb_legacy_retirement import FORMAT
    from sportsmodel.operations.mlb_identity_disposition import current_commit
    from sportsmodel.database.mlb_retirement_guard import OperatorTarget,canonical_json
    game=dict(gamePk=pair['pk'],officialDate='2026-07-12',gameDate='2026-07-12T18:10:00Z',gameType='R',doubleHeader='N',gameNumber=1,ifNecessary='N',
        status=dict(abstractGameState='Final',detailedState='Final',startTimeTBD=False),
        teams={side:dict(team=dict(id=pair[side+'_external'],name=pair[side]),score=score) for side,score in (('home',3),('away',1))})
    payload=canonical_json(dict(dates=[dict(date='2026-07-12',games=[game])])).encode()
    output=BytesIO()
    with zipfile.ZipFile(output,'w') as z:z.writestr('synthetic_schedule.json',payload)
    evidence=output.getvalue()
    body=dict(format=FORMAT,version=1,domain='MLB',action='ACTIVATE',category=pair['category'],policy_version='1.0.0',
        subject_game_id=pair['subject'],survivor_game_id=pair['survivor'],game_pk=pair['pk'],target_date='2026-07-12',expected_start='2026-07-12T18:10:00Z',
        subject_start='2026-07-12T18:11:00Z',reason='Synthetic fixture; never production authority',evidence_reference='Synthetic isolated evidence',
        evidence_sha256=sha256(evidence).hexdigest(),mlb_payload_entry='synthetic_schedule.json',mlb_payload_sha256=sha256(payload).hexdigest(),
        operator_identity='synthetic operator',tool_identity='synthetic test',implementation_commit=current_commit(),duplicate_proof_approved=True,publication_attribution_clear=True)
    body.update(changes)
    row=query(db,'SELECT host(inet_server_addr()),inet_server_port(),pg_postmaster_start_time(),(pg_control_system()).system_identifier::text')[0]
    target=OperatorTarget(host='127.0.0.1',port=PORT,database=DATABASE,server_address=row[0],server_port=row[1],postmaster_started_at=row[2].isoformat(),identity_kind='isolated',system_identifier=row[3])
    return canonical_json(body).encode(),evidence,target


def activate(db,pair):
    from sportsmodel.operations.mlb_legacy_retirement import preview_retirement,execute_retirement
    raw,evidence,target=request(db,pair)
    preview=preview_retirement(request_bytes=raw,evidence_bytes=evidence,target=target,connection_factory=db)
    receipt=execute_retirement(request_bytes=raw,evidence_bytes=evidence,preview=preview,approved_preview_sha256=preview['preview_sha256'],target=target,connection_factory=db,acknowledge_writes=True)
    return receipt,(raw,evidence,target,preview)


@pytest.mark.parametrize('identity_only',[False,True])
def test_synthetic_reviewed_pairs_actual_operator(db,identity_only):
    pair=seed(db,identity_only)
    tables=('games','game_sources','historical_games','team_game_statistics','player_game_pitching_statistics','odds_market_snapshots','odds_snapshots')
    before={t:query(db,'SELECT to_jsonb(t)::text FROM '+t+' t ORDER BY to_jsonb(t)::text') for t in tables}
    receipt,bundle=activate(db,pair)
    assert query(db,'SELECT subject_game_id,survivor_game_id FROM mlb_active_retired_identities')==[(pair['subject'],pair['survivor'])]
    assert before=={t:query(db,'SELECT to_jsonb(t)::text FROM '+t+' t ORDER BY to_jsonb(t)::text') for t in tables}
    assert receipt['action']=='ACTIVATE' and receipt['replay'] is False
    SCENARIO_EVIDENCE.append(dict(scenario='reviewed_equivalent',subject=pair['subject'],survivor=pair['survivor'],category=pair['category'],raw_history_equal=True,receipt=receipt))


@pytest.mark.parametrize('change',['proof','publication','identity','orientation','date','doubleheader','missing_history','missing_team','missing_pitching','pitch_metric','player_source','subject_history','subject_stats','observation','extra_source','market_shape'])
def test_affirmative_admission_refuses_each_invalid_state(db,change):
    from sportsmodel.operations.mlb_legacy_retirement import preview_retirement
    pair=seed(db,identity_only=change=='identity')
    changes={}
    if change=='proof':changes['duplicate_proof_approved']=False
    elif change=='publication':changes['publication_attribution_clear']=False
    elif change=='identity':query(db,'DELETE FROM game_sources WHERE game_id=%s',(pair['survivor'],))
    elif change=='orientation':query(db,'UPDATE games SET home_team_id=away_team_id,away_team_id=home_team_id WHERE game_id=%s',(pair['subject'],))
    elif change=='date':query(db,"UPDATE games SET game_date='2026-07-13T18:11:00Z' WHERE game_id=%s",(pair['subject'],))
    elif change=='doubleheader':query(db,"INSERT INTO games(game_id,game_date,home_team_id,away_team_id) VALUES(3000,'2026-07-12T21:00:00Z',%s,%s)",(pair['h'],pair['a']))
    elif change=='missing_history':query(db,'DELETE FROM historical_games WHERE game_id=%s',(pair['survivor'],))
    elif change=='missing_team':query(db,'DELETE FROM team_game_statistics WHERE game_id=%s AND is_home',(pair['survivor'],))
    elif change=='missing_pitching':query(db,'DELETE FROM player_game_pitching_statistics WHERE game_id=%s',(pair['survivor'],))
    elif change=='pitch_metric':query(db,'UPDATE player_game_pitching_statistics SET strikeouts=2 WHERE game_id=%s',(pair['survivor'],))
    elif change=='player_source':query(db,'DELETE FROM baseball_player_sources')
    elif change=='subject_history':query(db,"INSERT INTO historical_games(game_id,mlb_game_id,game_date,home_team,away_team,home_score,away_score,home_win) VALUES(%s,990000,'2026-07-12',%s,%s,3,1,TRUE)",(pair['subject'],pair['home'],pair['away']))
    elif change=='subject_stats':stat(db,'team_game_statistics',dict(game_id=pair['subject'],team_id=pair['h'],is_home=True,runs=3,hits=5,at_bats=30))
    elif change=='observation':
        run=query(db,"INSERT INTO odds_ingestion_runs(source_name,sport,status,snapshot_role,target_date,started_at,request_started_at,response_received_at,status_code,request_path,request_regions,request_markets,request_odds_format) VALUES('odds_api','baseball_mlb','running','opening','2026-07-12','2026-07-11T00:00:00Z','2026-07-11T00:00:00Z','2026-07-11T00:00:01Z',200,'synthetic','us','h2h','american') RETURNING odds_ingestion_run_id")[0][0]
        query(db,"INSERT INTO odds_provider_event_observations(odds_ingestion_run_id,source_name,provider_sport_key,external_event_id,provider_commence_time,provider_home_team_name,provider_away_team_name,observed_at) VALUES(%s,'odds_api','baseball_mlb',%s,'2026-07-12T18:11:00Z',%s,%s,'2026-07-11T00:00:01Z')",(run,'synthetic-legacy-29',pair['home'],pair['away']))
    elif change=='extra_source':query(db,"INSERT INTO game_sources(game_id,source_name,external_game_id) VALUES(%s,'other','synthetic-extra')",(pair['subject'],))
    elif change=='market_shape':query(db,"UPDATE odds_market_snapshots SET selection_name='Unknown' WHERE game_id=%s",(pair['subject'],))
    raw,evidence,target=request(db,pair,**changes)
    with pytest.raises((ValueError,psycopg2.Error)):
        preview_retirement(request_bytes=raw,evidence_bytes=evidence,target=target,connection_factory=db)
    assert query(db,'SELECT count(*) FROM mlb_legacy_identity_retirements')==[(0,)]


@pytest.mark.parametrize('table',['mlb_legacy_identity_retirements','mlb_legacy_identity_retirement_events'])
@pytest.mark.parametrize('operation',['UPDATE','DELETE','TRUNCATE'])
def test_append_only_actual_db(db,table,operation):
    activate(db,seed(db,True))
    sql=('UPDATE '+table+' SET '+('evidence_reference' if table.endswith('retirements') else 'action')+"='changed'" if operation=='UPDATE' else operation+(' FROM ' if operation=='DELETE' else ' ')+table)
    with pytest.raises(psycopg2.Error):query(db,sql)


@pytest.mark.parametrize('sql',[
    "INSERT INTO game_sources(game_id,source_name,external_game_id) VALUES(29,'other','synthetic-new')",
    "UPDATE odds_market_snapshots SET game_id=586 WHERE game_id=29",
    "UPDATE odds_market_snapshots SET price=-120 WHERE game_id=29",
    "DELETE FROM odds_market_snapshots WHERE game_id=29",
    "TRUNCATE odds_snapshots","TRUNCATE odds_market_snapshots CASCADE",
    "UPDATE games SET game_date=game_date+interval '1 minute' WHERE game_id=29",
    "UPDATE game_sources SET external_game_id='changed' WHERE game_id=29",
    "DELETE FROM game_sources WHERE game_id=586",
    "INSERT INTO odds_market_snapshots(game_id,sportsbook_id,market_type,selection_name,price,snapshot_time,source_name) SELECT 29,sportsbook_id,'h2h','Chicago White Sox',-110,'2026-07-13','odds_api' FROM sportsbooks LIMIT 1",
])
def test_legacy_seal_and_direct_sql_bypass(db,sql):
    activate(db,seed(db))
    with pytest.raises(psycopg2.Error):query(db,sql)


def test_exact_replay_and_changed_poststate(db):
    from sportsmodel.operations.mlb_legacy_retirement import execute_retirement,inspect_receipt
    receipt,(raw,evidence,target,preview)=activate(db,seed(db,True))
    replay=execute_retirement(request_bytes=raw,evidence_bytes=evidence,preview=preview,approved_preview_sha256=preview['preview_sha256'],target=target,connection_factory=db,acknowledge_writes=True)
    assert replay['event_id']==receipt['event_id'] and replay['replay']
    assert inspect_receipt(approved_preview_sha256=preview['preview_sha256'],target=target,connection_factory=db)['current_postconditions_match']
    query(db,'UPDATE team_game_statistics SET hits=hits+1 WHERE game_id=26')
    with pytest.raises(psycopg2.Error):execute_retirement(request_bytes=raw,evidence_bytes=evidence,preview=preview,approved_preview_sha256=preview['preview_sha256'],target=target,connection_factory=db,acknowledge_writes=True)


def test_v2_capture_same_snapshot_child_historical_cutoff_and_stale_proof(db):
    from sportsmodel.database.mlb_retirement_repository import capture_identity_knowledge,install_identity_knowledge,IdentityDispositionError
    pair=seed(db,True);knowledge=capture_identity_knowledge(connection_factory=db)
    c=db()
    try:
        with c.cursor() as cur:
            with pytest.raises(IdentityDispositionError):install_identity_knowledge(cur,knowledge,cutoff_time=datetime(2026,7,12,tzinfo=timezone.utc),current_factory=db)
            cur.execute('SELECT clock_timestamp()');cutoff=cur.fetchone()[0]
            install_identity_knowledge(cur,knowledge,cutoff_time=cutoff,current_factory=db)
            cur.execute("SELECT current_setting('sportsmodel.identity_knowledge')::jsonb,current_setting('sportsmodel.retirement_knowledge')::jsonb")
            old,new=cur.fetchone();assert old['ledger_fingerprint']==knowledge.ledger034 and old['available_at']==new['available_at'] and new['version']==2
        c.rollback()
    finally:c.close()
    activate(db,pair)
    c=db()
    try:
        with c.cursor() as cur:
            with pytest.raises(IdentityDispositionError):install_identity_knowledge(cur,knowledge,cutoff_time=datetime.now(timezone.utc),current_factory=db)
    finally:c.rollback();c.close()


@pytest.mark.parametrize('isolation',['REPEATABLE READ','SERIALIZABLE'])
def test_old_snapshot_writer_refuses_actual_topology(db,isolation):
    pair=seed(db,True);c=db();c.set_session(isolation_level=isolation)
    with c.cursor() as cur:cur.execute('SELECT count(*) FROM mlb_legacy_identity_retirements');assert cur.fetchone()==(0,)
    activate(db,pair)
    try:
        with pytest.raises(psycopg2.errors.SerializationFailure):
            with c.cursor() as cur:cur.execute("UPDATE teams SET team_name=team_name WHERE team_id=%s",(pair['h'],))
    finally:c.rollback();c.close()


def test_actual_matching_active_and_raw_sealed(db):
    from sportsmodel.ingest.game_matching import get_or_create_canonical_game,CanonicalGameIdentityConflictError,RAW_ACQUISITION_CONTINUITY
    pair=seed(db);activate(db,pair)
    for mode in ('ACTIVE_EVENT',RAW_ACQUISITION_CONTINUITY):
        c=db()
        try:
            with c.cursor() as cur:
                with pytest.raises(CanonicalGameIdentityConflictError):get_or_create_canonical_game(cur,source_name='odds_api',external_game_id='synthetic-legacy-29',game_datetime=datetime(2026,7,12,18,11,tzinfo=timezone.utc),home_team_id=pair['h'],away_team_id=pair['a'],resolution_mode=mode,provider_sport_key='baseball_mlb')
        finally:c.rollback();c.close()


def test_role_acl_catalog_and_trigger_order(db):
    from sportsmodel.database.mlb_retirement_repository import verify_capabilities
    c=db()
    try:
        with c.cursor() as cur:assert verify_capabilities(cur)
    finally:c.rollback();c.close()
    rows=query(db,"SELECT tgname,(tgtype::integer&1)<>0 AS row_trigger FROM pg_trigger WHERE tgrelid='game_identity_dispositions'::regclass AND NOT tgisinternal ORDER BY tgname")
    assert ('mlb_035_topology_ingress',False) in rows
    names=[r[0] for r in rows if r[1]];assert names.index('mlb_case_insert')<names.index('mlb_z035_cross_guard')
    query(db,"DO $$ BEGIN IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='retirement_runtime_test') THEN CREATE ROLE retirement_runtime_test NOLOGIN; END IF; END $$")
    query(db,'GRANT USAGE ON SCHEMA public TO retirement_runtime_test; GRANT SELECT ON ALL TABLES IN SCHEMA public TO retirement_runtime_test')
    with pytest.raises(psycopg2.errors.InsufficientPrivilege):query(db,"SET ROLE retirement_runtime_test; UPDATE mlb_identity_topology_fence SET epoch=epoch+1")
    with pytest.raises(psycopg2.errors.InsufficientPrivilege):query(db,"SET ROLE retirement_runtime_test; SELECT mlb_retirement_activate('{}')")
    SCENARIO_EVIDENCE.append(dict(scenario='trigger_order_ACL',trigger_order=rows,runtime_topology_and_activation_refused=True))


@pytest.mark.parametrize('change',["ALTER FUNCTION mlb_identity_is_retired(integer) IMMUTABLE",
    "ALTER TABLE games DISABLE TRIGGER mlb_035_write_guard",
    "ALTER VIEW mlb_eligible_active_market_snapshots RENAME physical_game_id TO game_id",
    "GRANT SELECT ON mlb_identity_topology_fence TO PUBLIC",
    "ALTER TABLE mlb_legacy_identity_retirements DROP CONSTRAINT mlb_legacy_identity_retirements_category_check",
    "ALTER FUNCTION mlb_identity_is_retired(integer) STRICT",
    "CREATE TABLE synthetic_uncovered(game_id integer REFERENCES games(game_id))"])
def test_actual_capability_drift_refuses(db,change):
    from sportsmodel.database.mlb_retirement_repository import verify_capabilities,IdentityDispositionError
    query(db,change)
    c=db()
    try:
        with c.cursor() as cur:
            with pytest.raises(IdentityDispositionError):verify_capabilities(cur)
    finally:c.rollback();c.close()


def test_old034_schema_client_and_v1_artifact_refuse(db):
    from sportsmodel.database.mlb_identity_disposition_repository import require_schema034
    from sportsmodel.database.mlb_retirement_repository import install_identity_knowledge,IdentityDispositionError
    with pytest.raises(ValueError):require_schema034(db)
    c=db()
    try:
        with c.cursor() as cur:
            with pytest.raises(IdentityDispositionError):install_identity_knowledge(cur,dict(version=1),cutoff_time=datetime.now(timezone.utc),current_factory=db)
    finally:c.rollback();c.close()


def test_legacy_revoke_request_always_refuses(db):
    from sportsmodel.operations.mlb_legacy_retirement import preview_retirement
    pair=seed(db,True);raw,evidence,target=request(db,pair,action='REVOKE')
    with pytest.raises(ValueError):preview_retirement(request_bytes=raw,evidence_bytes=evidence,target=target,connection_factory=db)


def test_h1_before_ranking_raw_visibility_and_survivor(db):
    from sportsmodel.database.mlb_retirement_repository import raw_identity,capture_identity_knowledge,knowledge_connection_factory
    from sportsmodel.database.team_statistics_repository import PostgresTeamStatisticsRepository
    pair=seed(db,True);activate(db,pair)
    assert query(db,'WITH ranked AS(SELECT game_id,row_number() OVER(ORDER BY game_date DESC,game_id DESC) AS rank FROM games WHERE home_team_id=%s AND NOT mlb_identity_is_retired(game_id)) SELECT game_id FROM ranked WHERE rank=1',(pair['h'],))==[(pair['survivor'],)]
    knowledge=capture_identity_knowledge(connection_factory=db);cutoff=query(db,'SELECT clock_timestamp()')[0][0]
    repository=PostgresTeamStatisticsRepository(connection_factory=knowledge_connection_factory(db,knowledge,cutoff_time=cutoff))
    records=repository.get_completed_games_before(team_id=pair['h'],cutoff_time=cutoff,limit=200)
    assert len(records)==1
    c=db()
    try:
        with c.cursor() as cur:assert raw_identity(cur,pair['subject'])['physical_game']['game_id']==pair['subject']
    finally:c.rollback();c.close()


def test_run_metadata_v2_and_original_v1_untouched(db):
    from sportsmodel.database.mlb_retirement_repository import capture_identity_knowledge,install_identity_knowledge
    from sportsmodel.database.moneyline_prediction_repository import create_moneyline_prediction_run
    knowledge=capture_identity_knowledge(connection_factory=db);cutoff=query(db,'SELECT clock_timestamp()')[0][0]
    c=db()
    try:
        with c.cursor() as cur:install_identity_knowledge(cur,knowledge,cutoff_time=cutoff,current_factory=db)
        rid=create_moneyline_prediction_run(c,target_date=date(2026,10,11),model_version='synthetic',feature_schema_version='synthetic',model_artifact_sha256='a'*64,model_training_cutoff=None)
    finally:c.close()
    assert query(db,'SELECT identity_disposition_knowledge,identity_retirement_knowledge->>\'version\' FROM moneyline_prediction_runs WHERE moneyline_prediction_run_id=%s',(rid,))==[(None,'2')]
    with pytest.raises(psycopg2.Error):query(db,'UPDATE moneyline_prediction_runs SET identity_retirement_knowledge=NULL WHERE moneyline_prediction_run_id=%s',(rid,))


def test_race_and_uncertain_commit_actual_operator(db):
    from sportsmodel.operations.mlb_legacy_retirement import preview_retirement,execute_retirement,inspect_receipt
    pair=seed(db,True);raw,evidence,target=request(db,pair)
    preview=preview_retirement(request_bytes=raw,evidence_bytes=evidence,target=target,connection_factory=db)
    results=[];start=threading.Barrier(2)
    def run():
        start.wait()
        try:results.append(execute_retirement(request_bytes=raw,evidence_bytes=evidence,preview=preview,approved_preview_sha256=preview['preview_sha256'],target=target,connection_factory=db,acknowledge_writes=True))
        except (ValueError,psycopg2.Error) as e:results.append(type(e).__name__)
    threads=[threading.Thread(target=run) for _ in range(2)]
    for t in threads:t.start()
    for t in threads:t.join(15);assert not t.is_alive()
    assert query(db,'SELECT count(*) FROM mlb_legacy_identity_retirement_events')==[(1,)]
    assert any(isinstance(r,dict) for r in results)
    assert inspect_receipt(approved_preview_sha256=preview['preview_sha256'],target=target,connection_factory=db)['retry_authorized'] is False
    SCENARIO_EVIDENCE.append(dict(scenario='concurrent_activation',results=results))


def frozen034_helpers():
    import importlib.util
    spec=importlib.util.spec_from_file_location('frozen034_test_helpers',ROOT/'tests/database/test_mlb_identity_disposition_postgres.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    module.PORT=PORT;module.DATABASE=DATABASE
    module.COMMIT='4cd5e86c79305df2a3d33246ce4f54c5dacd5396'
    return module


def test_original034_type_at035_actual_successor_operator_and_composite(db):
    from sportsmodel.operations import mlb_identity_disposition as operator
    from sportsmodel.database.mlb_retirement_guard import OperatorTarget
    from sportsmodel.database.mlb_retirement_repository import capture_identity_knowledge
    old=frozen034_helpers();pair=old.seed(db,reviewed_ids=True)
    raw,evidence,target=old.evidence_request(db,pair)
    data=json.loads(raw);data.update(format=operator.FORMAT,version=operator.VERSION)
    raw=json.dumps(data).encode();target=OperatorTarget(**dict(target.artifact(),migration_boundary=35))
    before=capture_identity_knowledge(connection_factory=db)
    preview=operator.preview_disposition(request_bytes=raw,evidence_bytes=evidence,target=target,connection_factory=db)
    receipt=operator.execute_disposition(request_bytes=raw,evidence_bytes=evidence,target=target,connection_factory=db,
        preview=preview,approved_preview_sha256=preview['preview_sha256'],acknowledge_writes=True)
    after=capture_identity_knowledge(connection_factory=db)
    assert before.fingerprint!=after.fingerprint and before.ledger034!=after.ledger034 and before.ledger035==after.ledger035
    assert receipt['retirement_fingerprint'] and receipt['ledger_fingerprint']==after.ledger034
    assert query(db,'SELECT mlb_identity_is_stale(11408),mlb_identity_is_retired(11408)')==[(True,True)]
    assert operator.inspect_receipt(approved_manifest_sha256=preview['preview_sha256'],target=target,connection_factory=db)['current_postconditions_match']
    case=query(db,'SELECT disposition_id FROM game_identity_dispositions WHERE subject_game_id=11408')[0][0]
    old.activate_sql(db,pair,action='REVOKE',evidence='b'*64,case=case,previous=receipt['event_id'],sequence=2)
    revoked=capture_identity_knowledge(connection_factory=db)
    assert revoked.fingerprint!=after.fingerprint and revoked.ledger034!=after.ledger034
    assert not operator.inspect_receipt(approved_manifest_sha256=preview['preview_sha256'],target=target,connection_factory=db)['current_postconditions_match']
    SCENARIO_EVIDENCE.append(dict(scenario='034_035_composite',before=before.body(),after=after.body(),revoked=revoked.body(),receipt=receipt))


@pytest.mark.parametrize('identity_only',[False,True])
def test_legacy_shapes_refuse_unchanged034_validator(db,identity_only):
    pair=seed(db,identity_only)
    with pytest.raises(psycopg2.Error):query(db,'SELECT mlb_identity_validate_pair(%s,%s,false)',(pair['subject'],pair['survivor']))
    assert query(db,'SELECT count(*) FROM game_identity_dispositions')==[(0,)]


@pytest.mark.parametrize('repository',['team','pitcher','bullpen'])
def test_empty_feature_windows_require_v2_actual_repositories(db,repository):
    from sportsmodel.database.team_statistics_repository import PostgresTeamStatisticsRepository
    from sportsmodel.database.pitcher_statistics_repository import PostgresPitcherStatisticsRepository
    from sportsmodel.database.bullpen_statistics_repository import PostgresBullpenStatisticsRepository
    cutoff=datetime.now(timezone.utc)
    with pytest.raises(psycopg2.Error,match='Committed v2'):
        if repository=='team':PostgresTeamStatisticsRepository(connection_factory=db).get_completed_games_before(team_id=999,cutoff_time=cutoff,limit=200)
        elif repository=='pitcher':PostgresPitcherStatisticsRepository(connection_factory=db).get_completed_starts_before(player_id=999,cutoff_time=cutoff,limit=50)
        else:PostgresBullpenStatisticsRepository(connection_factory=db).get_completed_relief_appearances_before(team_id=999,cutoff_time=cutoff)


def test_legacy_uncertain_commit_actual_operator_inspect_only(db):
    from sportsmodel.operations.mlb_legacy_retirement import preview_retirement,execute_retirement,inspect_receipt
    from sportsmodel.database.mlb_retirement_guard import OperatorRefusal
    pair=seed(db,True);raw,evidence,target=request(db,pair)
    preview=preview_retirement(request_bytes=raw,evidence_bytes=evidence,target=target,connection_factory=db)
    class LostAck:
        def __init__(self):self.inner=db();self.commits=0
        def __getattr__(self,n):return getattr(self.inner,n)
        def commit(self):
            self.commits+=1;self.inner.commit();raise psycopg2.OperationalError('Synthetic lost acknowledgment')
    connection=LostAck()
    with pytest.raises(OperatorRefusal,match='UNKNOWN'):
        execute_retirement(request_bytes=raw,evidence_bytes=evidence,target=target,connection_factory=lambda:connection,
            preview=preview,approved_preview_sha256=preview['preview_sha256'],acknowledge_writes=True)
    assert connection.commits==1
    result=inspect_receipt(approved_preview_sha256=preview['preview_sha256'],target=target,connection_factory=db)
    assert result['current_postconditions_match'] and result['retry_authorized'] is False
    SCENARIO_EVIDENCE.append(dict(scenario='legacy_lost_ack',result=result,automatic_retries=0))


def test_indirect_snapshot_to_survivor_decision_refuses_before_constraints(db):
    from sportsmodel.database.mlb_retirement_repository import assert_decision_write
    pair=seed(db);activate(db,pair)
    snapshot=query(db,'SELECT odds_market_snapshot_id FROM odds_market_snapshots WHERE game_id=29 LIMIT 1')[0][0]
    c=db()
    try:
        with c.cursor() as cur:
            with pytest.raises(psycopg2.Error,match='Retired'):
                assert_decision_write(cur,game_id=586,odds_market_snapshot_id=snapshot)
    finally:c.rollback();c.close()
    with pytest.raises(psycopg2.Error,match='sealed'):
        query(db,'INSERT INTO market_analysis(odds_market_snapshot_id) VALUES(%s)',(snapshot,))


def test_recovery_and_boxscore_retired_identity_refuse_before_provider(db,monkeypatch):
    from sportsmodel.database.mlb_recovery_repository import load_mlb_identity
    from sportsmodel.ingest import boxscore_ingestion
    pair=seed(db,True);activate(db,pair)
    c=db()
    try:
        with c.cursor() as cur:
            assert load_mlb_identity(cur,pair['pk'])['game_id']==pair['survivor']
            with pytest.raises(psycopg2.Error):cur.execute('SELECT mlb_retirement_assert_active(584)')
    finally:c.rollback();c.close()
    monkeypatch.setattr(boxscore_ingestion,'fetch_live_feed',lambda *a:pytest.fail('Provider reached'))
    monkeypatch.setattr(boxscore_ingestion,'fetch_boxscore',lambda *a:pytest.fail('Provider reached'))
    with pytest.raises(ValueError):boxscore_ingestion.ingest_boxscore(game_pk=pair['pk'],game_id=pair['subject'],connection_factory=db)


def test_combined_active_market_policy_preserves_raw_and_excludes_subject(db):
    pair=seed(db);raw=query(db,'SELECT odds_market_snapshot_id,game_id,price FROM odds_market_snapshots WHERE game_id=29 ORDER BY 1')
    assert len(query(db,'SELECT odds_market_snapshot_id FROM mlb_retirement_effective_markets() WHERE effective_game_id=29'))==96
    activate(db,pair)
    assert query(db,'SELECT odds_market_snapshot_id FROM mlb_retirement_effective_markets() WHERE raw_acquisition_game_id=29 OR effective_game_id=29')==[]
    assert query(db,'SELECT odds_market_snapshot_id,game_id,price FROM odds_market_snapshots WHERE game_id=29 ORDER BY 1')==raw


@pytest.mark.parametrize('subject,survivor',[(26,584),(3000,584),(584,3000)])
def test_legacy_cross_ledger_role_conflicts_refuse(db,subject,survivor):
    pair=seed(db,True);activate(db,pair)
    with pytest.raises(psycopg2.Error):query(db,"SELECT mlb_retirement_cross_pair(%s,%s,%s,'034')",(subject,survivor,pair['pk']))


def test_unrelated_non_mlb_write_semantics_unchanged(db):
    h,a=[r[0] for r in query(db,"INSERT INTO teams(team_name) VALUES('Synthetic Other Home'),('Synthetic Other Away') RETURNING team_id")]
    gid=query(db,"INSERT INTO games(game_date,home_team_id,away_team_id) VALUES('2026-10-11',%s,%s) RETURNING game_id",(h,a))[0][0]
    before=query(db,'SELECT epoch FROM mlb_identity_topology_fence')
    query(db,'UPDATE games SET scheduled_innings=9 WHERE game_id=%s',(gid,))
    assert query(db,'SELECT home_team_id,away_team_id FROM games WHERE game_id=%s',(gid,))==[(h,a)]
    assert query(db,'SELECT epoch FROM mlb_identity_topology_fence')==before
    assert query(db,'SELECT count(*) FROM mlb_game_identity_write_fences WHERE game_id=%s',(gid,))==[(0,)]
