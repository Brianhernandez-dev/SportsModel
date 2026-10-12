"""T01–T28 closure evidence: positively isolated PG16 only, all data synthetic."""
from datetime import datetime,date,timezone,timedelta
from dataclasses import replace
from hashlib import sha256
import json,threading,time,os
import psycopg2
import pytest
from tests.database.test_mlb_legacy_retirement_postgres import (
    db,seed,request,activate,query,stat,frozen034_helpers,ROOT,pytestmark,
)

SCENARIO_EVIDENCE=[]


def prepared(db,pair):
    from sportsmodel.operations.mlb_legacy_retirement import preview_retirement
    raw,evidence,target=request(db,pair)
    preview=preview_retirement(request_bytes=raw,evidence_bytes=evidence,target=target,connection_factory=db)
    case=dict(preview['case'],approved_preview_sha256=preview['preview_sha256'])
    return dict(case=case,expected_pair_sha256=preview['pair_fingerprint'],expected_state_sha256=preview['state']['fingerprint']),preview


def state(db):
    return query(db,"SELECT epoch,(SELECT count(*) FROM mlb_legacy_identity_retirements),(SELECT count(*) FROM mlb_legacy_identity_retirement_events) FROM mlb_identity_topology_fence")[0]


def wait_for_advisory(db,pid):
    deadline=time.monotonic()+5
    while time.monotonic()<deadline:
        rows=query(db,"""SELECT a.pid,a.wait_event_type,a.wait_event,l.classid::bigint,l.objid::bigint,l.mode,l.granted,clock_timestamp()
            FROM pg_stat_activity a JOIN pg_locks l ON l.pid=a.pid WHERE a.pid=%s AND l.locktype='advisory' AND NOT l.granted""",(pid,))
        if rows:
            assert rows[0][1:3]==('Lock','advisory') and rows[0][3:5]==(1397574724,34)
            return rows
        time.sleep(.01)  # Poll observed DB state; not a mocked/connector delay.
    pytest.fail('No actual advisory wait observed')


@pytest.mark.parametrize('isolation',['REPEATABLE READ','SERIALIZABLE'])
def test_measured_wait_old_snapshot_refuses(db,isolation):
    pair=seed(db,True);activation,preview=prepared(db,pair)
    a=db();a.set_session(isolation_level=isolation)
    with a.cursor() as cur:
        cur.execute("SELECT epoch,pg_current_snapshot()::text,current_setting('transaction_isolation'),clock_timestamp() FROM mlb_identity_topology_fence")
        before=cur.fetchone()
    b=db();b.set_session(isolation_level='SERIALIZABLE')
    with b.cursor() as cur:
        cur.execute('SELECT mlb_retirement_activate(%s::jsonb)',(json.dumps(activation),));receipt=cur.fetchone()[0]
    results=[]
    def old_reader():
        started=time.perf_counter()
        try:
            with a.cursor() as cur:cur.execute('SELECT mlb_retirement_topology_fresh()')
            results.append(dict(outcome='UNSAFE_SUCCESS'))
        except psycopg2.Error as error:
            results.append(dict(sqlstate=error.pgcode,refusal_point='mlb_retirement_topology_fresh FOR SHARE',elapsed_ms=(time.perf_counter()-started)*1000))
    worker=threading.Thread(target=old_reader);worker.start()
    locks=wait_for_advisory(db,a.info.backend_pid)
    with b.cursor() as cur:
        cur.execute('SELECT pg_sleep(.15),clock_timestamp()');released_at=cur.fetchone()[1]
    b.commit();b.close();worker.join(10)
    try:
        assert not worker.is_alive() and results[0].get('sqlstate')=='40001' and results[0]['elapsed_ms']>=100
        after=state(db);assert after==(before[0]+2,1,1)
        SCENARIO_EVIDENCE.append(dict(scenario='measured_wait',isolation=isolation,session_a_pid=a.info.backend_pid,
            before=before,blocked_locks=locks,release_db_time=released_at,after=after,result=results[0],receipt=receipt))
    finally:a.rollback();a.close()


@pytest.mark.parametrize('isolation',['REPEATABLE READ','SERIALIZABLE'])
def test_measured_wait_inverse_current_read_before_activation(db,isolation):
    pair=seed(db,True);activation,preview=prepared(db,pair)
    a=db();a.set_session(isolation_level=isolation)
    with a.cursor() as cur:cur.execute('SELECT mlb_retirement_topology_fresh(),mlb_retirement_assert_active(584)');assert cur.fetchone()[1]
    b=db();b.set_session(isolation_level='SERIALIZABLE');out=[]
    def activate_waiting():
        tick=time.perf_counter()
        try:
            with b.cursor() as cur:cur.execute('SELECT mlb_retirement_activate(%s::jsonb)',(json.dumps(activation),));receipt=cur.fetchone()[0]
            b.commit();out.append(dict(receipt=receipt,elapsed_ms=(time.perf_counter()-tick)*1000))
        except psycopg2.Error as e:out.append(dict(sqlstate=e.pgcode))
    t=threading.Thread(target=activate_waiting);t.start();locks=wait_for_advisory(db,b.info.backend_pid)
    with a.cursor() as cur:cur.execute('SELECT pg_sleep(.15)')
    a.commit();a.close();t.join(10)
    try:
        assert not t.is_alive() and out[0].get('receipt') and out[0]['elapsed_ms']>=100 and state(db)==(3,1,1)
        SCENARIO_EVIDENCE.append(dict(scenario='measured_wait_inverse',isolation=isolation,blocked_locks=locks,result=out[0]))
    finally:b.rollback();b.close()


def restricted_roles(db):
    query(db,"""DO $$ BEGIN
      IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='retirement171_runtime') THEN CREATE ROLE retirement171_runtime NOLOGIN; END IF;
      IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='retirement171_executor') THEN CREATE ROLE retirement171_executor NOLOGIN; END IF;
    END $$;
    GRANT USAGE ON SCHEMA public TO retirement171_runtime,retirement171_executor;
    GRANT SELECT ON ALL TABLES IN SCHEMA public TO retirement171_runtime,retirement171_executor;
    GRANT INSERT,UPDATE,DELETE ON games,game_sources,historical_games,team_game_statistics,player_game_pitching_statistics,moneyline_prediction_runs,
      moneyline_game_predictions,moneyline_prediction_market_evaluations,moneyline_paper_candidate_settlements,
      odds_snapshots,odds_market_snapshots,odds_provider_event_observations,odds_ingestion_runs,market_analysis TO retirement171_runtime;
    GRANT EXECUTE ON FUNCTION mlb_retirement_activate(jsonb) TO retirement171_executor;""")
    sequences=query(db,"""SELECT DISTINCT s.relname FROM pg_class s JOIN pg_depend d ON d.objid=s.oid JOIN pg_class t ON t.oid=d.refobjid
      WHERE s.relnamespace='public'::regnamespace AND s.relkind='S' AND d.deptype IN('a','i') AND t.relname=ANY(%s)""",
      (['games','game_sources','historical_games','team_game_statistics','player_game_pitching_statistics','moneyline_prediction_runs','moneyline_game_predictions',
        'moneyline_prediction_market_evaluations','moneyline_paper_candidate_settlements','odds_snapshots','odds_market_snapshots',
        'odds_provider_event_observations','odds_ingestion_runs','market_analysis'],))
    for name, in sequences:
        assert name.replace('_','').isalnum()
        query(db,'GRANT USAGE,SELECT ON SEQUENCE '+name+' TO retirement171_runtime')


def role_query(db,role,sql,args=()):
    assert role in ('retirement171_runtime','retirement171_executor')
    c=db()
    try:
        with c.cursor() as cur:
            cur.execute('SET ROLE '+role)
            cur.execute("SELECT current_user,r.rolsuper FROM pg_roles r WHERE rolname=current_user")
            assert cur.fetchone()==(role,False)
            cur.execute(sql,args);rows=cur.fetchall() if cur.description else None
        c.commit();return rows
    finally:c.close()


def test_representative_runtime_and_executor_actual_privileges(db):
    pair=seed(db,True);activation,preview=prepared(db,pair);restricted_roles(db)
    role_query(db,'retirement171_runtime','UPDATE games SET scheduled_innings=scheduled_innings WHERE game_id=26')
    # This operational write changes no pair values, but changes its fence: use a
    # new reviewed synthetic preview, never silently retry a stale approval.
    activation,preview=prepared(db,pair)
    for table in ('mlb_legacy_identity_retirements','mlb_legacy_identity_retirement_events','mlb_identity_topology_fence'):
        with pytest.raises(psycopg2.errors.InsufficientPrivilege):role_query(db,'retirement171_runtime','DELETE FROM '+table)
    with pytest.raises(psycopg2.errors.InsufficientPrivilege):role_query(db,'retirement171_runtime','SELECT mlb_retirement_activate(%s)',(json.dumps(activation),))
    with pytest.raises(psycopg2.errors.InsufficientPrivilege):role_query(db,'retirement171_runtime','ALTER TABLE games DISABLE TRIGGER mlb_035_write_guard')
    with pytest.raises(psycopg2.errors.InsufficientPrivilege):role_query(db,'retirement171_executor','UPDATE games SET game_date=game_date WHERE game_id=584')
    receipt=role_query(db,'retirement171_executor','SELECT mlb_retirement_activate(%s::jsonb)',(json.dumps(activation),))[0][0]
    with pytest.raises(psycopg2.Error,match='sealed'):role_query(db,'retirement171_runtime','UPDATE games SET game_date=game_date+interval \'1 minute\' WHERE game_id=584')
    with pytest.raises(psycopg2.Error):role_query(db,'retirement171_executor','SELECT mlb_retirement_activate(%s::jsonb)',(json.dumps(dict(activation,action='REVOKE')),))
    assert state(db)==(3,1,1)
    rows=query(db,"""SELECT c.relname,a.privilege_type FROM pg_class c CROSS JOIN LATERAL aclexplode(coalesce(c.relacl,acldefault('r',c.relowner))) a
        WHERE c.relname IN('mlb_legacy_identity_retirements','mlb_legacy_identity_retirement_events','mlb_identity_topology_fence') AND a.grantee=0""")
    assert rows==[]
    SCENARIO_EVIDENCE.append(dict(scenario='restricted_roles',runtime='retirement171_runtime',executor='retirement171_executor',superuser_assertions=False,
        runtime_operational_write=True,executor_narrow_activation=True,receipt=receipt,public_new_ledger_grants=rows))


def target_for(db):
    from sportsmodel.database.mlb_retirement_guard import OperatorTarget
    c=db()
    try:
        with c.cursor() as cur:
            cur.execute('SELECT host(inet_server_addr()),inet_server_port(),pg_postmaster_start_time(),(pg_control_system()).system_identifier::text')
            address,port,started,system=cur.fetchone()
        return OperatorTarget(host=c.info.host,port=c.info.port,database=c.info.dbname,server_address=address,server_port=port,
            postmaster_started_at=started.isoformat(),identity_kind='isolated',system_identifier=system)
    finally:c.rollback();c.close()


def category_pair(db,kind,subject_start=None):
    pair=seed(db,identity_only=kind!='legacy_market')
    if subject_start is not None:query(db,'UPDATE games SET game_date=%s WHERE game_id=%s',(subject_start,pair['subject']))
    query(db,"UPDATE baseball_player_sources SET external_player_id=(800000+baseball_player_id)::text WHERE source_name='mlb_stats'")
    if kind=='034':
        pair['category']='STALE_MARKET_ONLY_DUPLICATE'
        for gid,event in ((pair['subject'],'synthetic171-old'),(pair['survivor'],'synthetic171-new')):
            query(db,"INSERT INTO game_sources(game_id,source_name,external_game_id) VALUES(%s,'odds_api',%s)",(gid,event))
        book=query(db,"INSERT INTO sportsbooks(name) VALUES('Synthetic171 Observation Book') RETURNING sportsbook_id")[0][0]
        provider=query(db,"INSERT INTO sportsbook_provider_identities(provider_name,provider_bookmaker_key,sportsbook_id) VALUES('odds_api','synthetic171-book',%s) RETURNING sportsbook_provider_identity_id",(book,))[0][0]
        run=query(db,"INSERT INTO odds_ingestion_runs(source_name,sport,status,snapshot_role,target_date,started_at,request_started_at,response_received_at,status_code,request_path,request_regions,request_markets,request_odds_format) VALUES('odds_api','baseball_mlb','running','opening','2026-07-12','2026-07-11T00:00:00Z','2026-07-11T00:00:00Z','2026-07-11T00:00:01Z',200,'synthetic','us','h2h','american') RETURNING odds_ingestion_run_id")[0][0]
        for gid,event in ((pair['subject'],'synthetic171-old'),(pair['survivor'],'synthetic171-new')):
            when=query(db,'SELECT game_date FROM games WHERE game_id=%s',(gid,))[0][0]
            obs=query(db,"INSERT INTO odds_provider_event_observations(odds_ingestion_run_id,source_name,provider_sport_key,external_event_id,provider_commence_time,provider_home_team_name,provider_away_team_name,observed_at) VALUES(%s,'odds_api','baseball_mlb',%s,%s,%s,%s,'2026-07-11T00:00:01Z') RETURNING odds_provider_event_observation_id",(run,event,when,pair['home'],pair['away']))[0][0]
            query(db,"INSERT INTO odds_market_snapshots(game_id,sportsbook_id,market_type,selection_name,price,snapshot_time,source_name,odds_ingestion_run_id,odds_provider_event_observation_id,sportsbook_provider_identity_id,bookmaker_title_at_observation,observed_at) VALUES(%s,%s,'h2h',%s,-110,'2026-07-11T00:00:01Z','odds_api',%s,%s,%s,'Synthetic171 Observation Book','2026-07-11T00:00:01Z')",(gid,book,pair['home'],run,obs,provider))
    return pair


def retire_category(db,pair):
    if pair['category']=='STALE_MARKET_ONLY_DUPLICATE':
        return frozen034_helpers().activate_sql(db,(pair['subject'],pair['survivor'],pair['h'],pair['a']))
    from sportsmodel.operations.mlb_legacy_retirement import preview_retirement,execute_retirement
    when=query(db,'SELECT game_date FROM games WHERE game_id=%s',(pair['subject'],))[0][0]
    raw,evidence,target=request(db,pair,subject_start=when.isoformat())
    preview=preview_retirement(request_bytes=raw,evidence_bytes=evidence,target=target,connection_factory=db)
    return execute_retirement(request_bytes=raw,evidence_bytes=evidence,target=target,connection_factory=db,
        preview=preview,approved_preview_sha256=preview['preview_sha256'],acknowledge_writes=True)


def clone_history(db,pair,times,other_clubs=False):
    h,a=pair['h'],pair['a'];home,away=pair['home'],pair['away']
    if other_clubs:
        club_ids=[]
        for name,external in (('Boston Red Sox',111),('Baltimore Orioles',110)):
            found=query(db,'SELECT team_id FROM teams WHERE team_name=%s',(name,))
            tid=found[0][0] if found else query(db,'INSERT INTO teams(team_name) VALUES(%s) RETURNING team_id',(name,))[0][0]
            query(db,"INSERT INTO baseball_team_sources(team_id,source_name,external_team_id) VALUES(%s,'mlb_stats',%s)",(tid,str(external)));club_ids.append(tid)
        h,a=club_ids;home,away='Boston Red Sox','Baltimore Orioles'
    c=db()
    try:
        with c.cursor() as cur:
            for i,when in enumerate(times):
                cur.execute('INSERT INTO games(game_id,game_date,home_team_id,away_team_id) VALUES(%s,%s,%s,%s)',(50000+i,when,h,a))
                cur.execute("INSERT INTO game_sources(game_id,source_name,external_game_id) VALUES(%s,'mlb_stats',%s)",(50000+i,str(950000+i)))
            for table,key in (('historical_games','historical_game_id'),('team_game_statistics','team_game_statistics_id'),('player_game_pitching_statistics','player_game_pitching_statistics_id')):
                cur.execute('SELECT column_name FROM information_schema.columns WHERE table_schema=\'public\' AND table_name=%s ORDER BY ordinal_position',(table,))
                names=[r[0] for r in cur.fetchall() if r[0]!=key]
                expressions=[]
                for name in names:
                    if name=='game_id':expressions.append('g.game_id')
                    elif name=='mlb_game_id':expressions.append('950000+(g.game_id-50000)')
                    elif name=='game_date':expressions.append("(g.game_date AT TIME ZONE 'America/Los_Angeles')::date")
                    elif name=='home_team':expressions.append('%s')
                    elif name=='away_team':expressions.append('%s')
                    elif name=='team_id':expressions.append('CASE WHEN t.team_id=%s THEN %s ELSE %s END')
                    else:expressions.append('t.'+name)
                params=[]
                for name in names:
                    if name=='home_team':params.append(home)
                    elif name=='away_team':params.append(away)
                    elif name=='team_id':params.extend((pair['h'],h,a))
                params.append(pair['survivor'])
                cur.execute('INSERT INTO '+table+'('+','.join(names)+') SELECT '+','.join(expressions)+' FROM '+table+' t CROSS JOIN games g WHERE t.game_id=%s AND g.game_id BETWEEN 50000 AND '+str(49999+len(times)),params)
        c.commit()
    finally:c.close()


def actual_h1(db,pair):
    from sportsmodel.database.mlb_retirement_repository import capture_identity_knowledge
    from sportsmodel.operations.mlb_history_check import check_feature_history
    starters=[r[0] for r in query(db,'SELECT baseball_player_id FROM player_game_pitching_statistics WHERE game_id=%s ORDER BY team_id',(pair['survivor'],))]
    now=query(db,'SELECT clock_timestamp()')[0][0];day=now.date()+timedelta(days=1)
    when=datetime.combine(day,datetime.min.time(),timezone.utc)+timedelta(hours=19)
    query(db,'INSERT INTO games(game_id,game_date,home_team_id,away_team_id) VALUES(60000,%s,%s,%s)',(when,pair['h'],pair['a']))
    query(db,"INSERT INTO game_sources(game_id,source_name,external_game_id) VALUES(60000,'mlb_stats','960000')")
    knowledge=capture_identity_knowledge(connection_factory=db);cutoff=query(db,'SELECT clock_timestamp()')[0][0]
    return check_feature_history(target_date=day,target_game_ids=(60000,),starting_pitcher_ids=tuple(starters),cutoff_time=cutoff,
        target=target_for(db),connection_factory=db,identity_knowledge=knowledge)


@pytest.mark.parametrize('kind',['legacy_market','identity_only','034'])
@pytest.mark.parametrize('rank',[1,199,200,201])
def test_actual_h1_team_200_boundary(db,kind,rank):
    canonical=datetime(2026,7,12,18,10,tzinfo=timezone.utc)
    subject=canonical+timedelta(minutes=1) if rank==1 else canonical-timedelta(minutes=rank)
    pair=category_pair(db,kind,subject);retire_category(db,pair)
    newer=[canonical-timedelta(minutes=i) for i in range(1,max(1,rank-1))]
    older=[subject-timedelta(minutes=i) for i in range(1,202-len(newer))]
    clone_history(db,pair,newer+older)
    raw=query(db,'SELECT game_id,row_number() OVER(ORDER BY game_date DESC,game_id DESC) FROM games WHERE home_team_id=%s ORDER BY game_date DESC,game_id DESC',(pair['h'],))
    assert dict(raw)[pair['subject']]==rank
    result=actual_h1(db,pair)
    assert result['status']=='PASS'
    window=[r['game_id'] for r in result['retained_team_history_games'] if r['team_id']==pair['h']]
    assert len(window)==200 and pair['subject'] not in window and pair['survivor'] in window
    expected=[gid for gid,_ in raw if gid!=pair['subject']][:200];assert window==expected
    SCENARIO_EVIDENCE.append(dict(scenario='H1_team_boundary',category=kind,subject_raw_rank=rank,window=window,canonical=pair['survivor'],report=result))


@pytest.mark.parametrize('kind',['legacy_market','identity_only','034'])
@pytest.mark.parametrize('rank',[49,50,51])
def test_actual_h1_starter_50_boundary(db,kind,rank):
    pair=category_pair(db,kind);retire_category(db,pair)
    canonical=datetime(2026,7,12,18,10,tzinfo=timezone.utc)
    times=[canonical+timedelta(minutes=i) for i in range(1,rank)]+[canonical-timedelta(minutes=i) for i in range(1,53-rank)]
    clone_history(db,pair,times,other_clubs=True)
    result=actual_h1(db,pair);assert result['status']=='PASS'
    assert pair['survivor'] in result['required_canonical_game_ids'] and pair['subject'] not in result['required_canonical_game_ids']
    players=sorted({r['baseball_player_id'] for r in result['retained_starter_history_games']})
    assert len(players)==2
    for player in players:
        rows=[r for r in result['retained_starter_history_games'] if r['baseball_player_id']==player]
        assert len(rows)==50 and all(r['game_id']!=pair['subject'] for r in rows)
        survivor=[r for r in rows if r['game_id']==pair['survivor']]
        assert (survivor[0]['rank'] if survivor else None)==(rank if rank<=50 else None)
    SCENARIO_EVIDENCE.append(dict(scenario='H1_starter_boundary',category=kind,survivor_rank=rank,report=result,
        clarification='Valid survivor windows; retired pitching rows violate admission and are separately refusal-tested.'))


@pytest.mark.parametrize('invalid',['not-a-provider-id','0','-7'])
def test_survivor_invalid_player_source_refuses_admission(db,invalid):
    from sportsmodel.operations.mlb_legacy_retirement import preview_retirement
    pair=category_pair(db,'identity_only')
    query(db,"UPDATE baseball_player_sources SET external_player_id=%s WHERE baseball_player_source_id=(SELECT min(baseball_player_source_id) FROM baseball_player_sources)",(invalid,))
    raw,evidence,target=request(db,pair)
    with pytest.raises((ValueError,psycopg2.Error),match='player|pitching|canonical'):
        preview_retirement(request_bytes=raw,evidence_bytes=evidence,target=target,connection_factory=db)
    assert state(db)==(1,0,0)


def business_digest(db):
    tables=[r[0] for r in query(db,"SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")]
    excluded={'game_identity_dispositions','game_identity_disposition_events','mlb_game_identity_write_fences',
              'mlb_legacy_identity_retirements','mlb_legacy_identity_retirement_events','mlb_identity_topology_fence'}
    return {t:dict(count=len(rows),sha256=sha256(json.dumps(rows,default=str).encode()).hexdigest())
        for t in tables if t not in excluded
        for rows in [query(db,'SELECT to_jsonb(t)::text FROM '+t+' t ORDER BY to_jsonb(t)::text')]}


@pytest.mark.parametrize('kind',['legacy_market','identity_only'])
def test_all_business_rows_byte_equal_after_activation(db,kind):
    pair=category_pair(db,kind);before=business_digest(db);retire_category(db,pair)
    assert business_digest(db)==before
    SCENARIO_EVIDENCE.append(dict(scenario='all_business_rows_preserved',category=kind,tables=before))


def copy_subject_pitching(db,pair,corrupt=False):
    c=db()
    try:
        with c.cursor() as cur:
            cur.execute("SELECT column_name FROM information_schema.columns WHERE table_schema='public' AND table_name='player_game_pitching_statistics' ORDER BY ordinal_position")
            names=[r[0] for r in cur.fetchall() if r[0]!='player_game_pitching_statistics_id']
            expressions=['%s' if n=='game_id' else n for n in names]
            if corrupt:cur.execute('ALTER TABLE player_game_pitching_statistics DISABLE TRIGGER USER')
            cur.execute('INSERT INTO player_game_pitching_statistics('+','.join(names)+') SELECT '+','.join(expressions)+' FROM player_game_pitching_statistics WHERE game_id=%s',(pair['subject'],pair['survivor']))
            if corrupt:cur.execute('ALTER TABLE player_game_pitching_statistics ENABLE TRIGGER USER')
        c.commit()
    finally:c.close()


@pytest.mark.parametrize('kind',['legacy_market','identity_only','034'])
def test_subject_pitching_admission_and_corrupted_h1_refuse(db,kind):
    pair=category_pair(db,kind);copy_subject_pitching(db,pair)
    with pytest.raises(psycopg2.Error):retire_category(db,pair)
    assert state(db)==(1,0,0)
    query(db,'DELETE FROM player_game_pitching_statistics WHERE game_id=%s',(pair['subject'],))
    retire_category(db,pair)
    # Explicit owner-only fixture corruption, NOT a runtime bypass or successful
    # window. Restore exact triggers before the actual H1 fail-closed assertion.
    copy_subject_pitching(db,pair,corrupt=True)
    with pytest.raises((ValueError,psycopg2.Error),match='Retired|history|prohibited|stale'):
        actual_h1(db,pair)
    SCENARIO_EVIDENCE.append(dict(scenario='corrupt_starter_refusal',category=kind,admission_refused=True,H1_refused=True,
        user_clarification='No legal successful H1 includes retired-subject pitching history.'))


@pytest.mark.parametrize('stage',['case_before','case_after','event_before','event_after'])
def test_activation_server_fault_rolls_back_every_mutation(db,stage):
    from sportsmodel.operations.mlb_legacy_retirement import execute_retirement
    pair=category_pair(db,'identity_only');activation,preview=prepared(db,pair)
    raw,evidence,target=request(db,pair)
    before=business_digest(db);fences=query(db,'SELECT to_jsonb(f) FROM mlb_game_identity_write_fences f ORDER BY game_id');topology=state(db)
    table='mlb_legacy_identity_retirements' if stage.startswith('case') else 'mlb_legacy_identity_retirement_events'
    timing='BEFORE' if stage.endswith('before') else 'AFTER'
    query(db,"CREATE FUNCTION synthetic171_fault() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'Synthetic171 activation fault'; END $$")
    query(db,'CREATE TRIGGER zz171_fault '+timing+' INSERT ON '+table+' FOR EACH ROW EXECUTE FUNCTION synthetic171_fault()')
    with pytest.raises(psycopg2.Error,match='Synthetic171 activation fault'):
        execute_retirement(request_bytes=raw,evidence_bytes=evidence,target=target,connection_factory=db,
            preview=preview,approved_preview_sha256=preview['preview_sha256'],acknowledge_writes=True)
    assert state(db)==topology and business_digest(db)==before
    assert query(db,'SELECT to_jsonb(f) FROM mlb_game_identity_write_fences f ORDER BY game_id')==fences
    SCENARIO_EVIDENCE.append(dict(scenario='activation_fault',stage=stage,topology_before=topology,topology_after=state(db),fences_unchanged=True,business_rows_unchanged=True))


@pytest.mark.parametrize('operation',['orphan_case','orphan_event','caller_time','wrong_action','reactivation','retarget'])
def test_case_event_atomic_permanent_contract(db,operation):
    pair=category_pair(db,'identity_only');activation,preview=prepared(db,pair)
    if operation in ('reactivation','retarget'):retire_category(db,pair)
    before=state(db);c=db()
    try:
        with pytest.raises(psycopg2.Error):
            with c.cursor() as cur:
                if operation=='orphan_case':
                    fields=list(activation['case']);values=[json.dumps(v) if isinstance(v,dict) else v for v in activation['case'].values()]
                    cur.execute('INSERT INTO mlb_legacy_identity_retirements('+','.join(fields)+') VALUES('+','.join(['%s']*len(fields))+')',values)
                elif operation=='orphan_event':
                    cur.execute("INSERT INTO mlb_legacy_identity_retirement_events(retirement_id,action,sequence,approved_preview_sha256,pre_state_sha256,post_state_sha256,receipt) VALUES(999,'ACTIVATE',1,%s,%s,%s,'{}')",('a'*64,'b'*64,'c'*64))
                elif operation=='caller_time':
                    cur.execute('SELECT mlb_retirement_activate(%s::jsonb)',(json.dumps(dict(activation,case=dict(activation['case'],created_at='2026-01-01'))),))
                elif operation=='wrong_action':cur.execute('SELECT mlb_retirement_activate(%s::jsonb)',(json.dumps(dict(activation,action='REVOKE')),))
                elif operation=='reactivation':
                    activation['case']['approved_preview_sha256']='f'*64
                    cur.execute('SELECT mlb_retirement_fingerprint(%s),mlb_retirement_pair_fingerprint(584,26)',(activation['case']['implementation_sha256'],))
                    activation['expected_state_sha256'],activation['expected_pair_sha256']=cur.fetchone()
                    cur.execute('SELECT mlb_retirement_activate(%s::jsonb)',(json.dumps(activation),))
                else:cur.execute('UPDATE mlb_legacy_identity_retirements SET survivor_game_id=584')
            c.commit()
        c.rollback()
    finally:c.close()
    assert state(db)==before


@pytest.mark.parametrize('corruption',['version','seal','digest','cutoff','endpoint'])
def test_actual_committed_v2_forgery_and_timing_refuse(db,corruption):
    from sportsmodel.database.mlb_retirement_repository import capture_identity_knowledge,install_identity_knowledge,IdentityDispositionError
    proof=capture_identity_knowledge(connection_factory=db);cutoff=query(db,'SELECT clock_timestamp()')[0][0]
    if corruption=='version':proof=proof.body()
    elif corruption=='seal':proof=replace(proof,capture_attestation=None)
    elif corruption=='digest':proof=replace(proof,artifact_sha256='f'*64)
    elif corruption=='cutoff':cutoff=datetime(2026,10,8,tzinfo=timezone.utc)
    else:proof=replace(proof,endpoint=('127.0.0.1',55447,'sportsmodel_test_retirement170_34'))
    c=db()
    try:
        with c.cursor() as cur:
            with pytest.raises(IdentityDispositionError):install_identity_knowledge(cur,proof,cutoff_time=cutoff,current_factory=db)
    finally:c.rollback();c.close()


def test_many_proven_subjects_one_survivor_and_lifetime_cross_roles(db):
    pair=category_pair(db,'identity_only');retire_category(db,pair)
    query(db,"INSERT INTO games(game_id,game_date,home_team_id,away_team_id) VALUES(3000,'2026-07-12T18:12:00Z',%s,%s)",(pair['h'],pair['a']))
    second=dict(pair,subject=3000);retire_category(db,second)
    assert query(db,'SELECT subject_game_id,survivor_game_id FROM mlb_active_retired_identities ORDER BY subject_game_id')==[(584,26),(3000,26)]
    for subject,survivor in ((26,584),(26,3000),(584,3000),(3000,584)):
        with pytest.raises(psycopg2.Error):query(db,"SELECT mlb_retirement_cross_pair(%s,%s,%s,'034')",(subject,survivor,pair['pk']))


def test_topology_overflow_and_no_lock_promotion_refuse(db):
    pair=category_pair(db,'identity_only');activation,preview=prepared(db,pair)
    c=db()
    try:
        with c.cursor() as cur:
            cur.execute('SELECT mlb_identity_gate(false)')
            with pytest.raises(psycopg2.Error):cur.execute('SELECT mlb_identity_gate(true)')
    finally:c.rollback();c.close()
    # Owner-only fixture fence at maximum. Restore the exact trigger before
    # attempting the actual narrow activation; failure must leave it unchanged.
    query(db,"ALTER TABLE mlb_identity_topology_fence DISABLE TRIGGER mlb_topology_row; UPDATE mlb_identity_topology_fence SET epoch=9223372036854775807; ALTER TABLE mlb_identity_topology_fence ENABLE TRIGGER mlb_topology_row")
    activation,preview=prepared(db,pair);before=state(db)
    with pytest.raises(psycopg2.Error,match='overflow'):
        query(db,'SELECT mlb_retirement_activate(%s::jsonb)',(json.dumps(activation),))
    assert state(db)==before


def test_altered_function_default_refuses_exact035(db):
    from sportsmodel.database.mlb_retirement_repository import verify_capabilities,IdentityDispositionError
    definition=query(db,"SELECT pg_get_functiondef('mlb_retirement_validate(mlb_legacy_identity_retirements,boolean)'::regprocedure)")[0][0]
    changed=definition.replace('DEFAULT true','DEFAULT false');assert changed!=definition
    query(db,changed)
    c=db()
    try:
        with c.cursor() as cur:
            with pytest.raises(IdentityDispositionError):verify_capabilities(cur)
    finally:c.rollback();c.close()


def preview_run(db):
    from sportsmodel.database.mlb_retirement_repository import capture_identity_knowledge,install_identity_knowledge
    from sportsmodel.database.moneyline_prediction_repository import create_moneyline_prediction_run
    knowledge=capture_identity_knowledge(connection_factory=db);cutoff=query(db,'SELECT clock_timestamp()')[0][0]
    c=db()
    try:
        with c.cursor() as cur:install_identity_knowledge(cur,knowledge,cutoff_time=cutoff,current_factory=db)
        return create_moneyline_prediction_run(c,target_date=date(2026,7,12),model_version='synthetic171-not-a-model',
            feature_schema_version='synthetic171',model_artifact_sha256='a'*64,model_training_cutoff=None,run_type='preview')
    finally:c.close()


PREDICTION_SQL="""INSERT INTO moneyline_game_predictions(moneyline_prediction_run_id,game_id,mlb_game_id,game_start_time,prediction_time,
 home_team_id,away_team_id,home_starter_features_available,away_starter_features_available,starter_coverage,missing_raw_value_count,
 home_win_probability,away_win_probability,predicted_team_id,predicted_probability)
 VALUES(%s,%s,%s,'2026-07-12T18:10:00Z','2026-07-12T12:00:00Z',%s,%s,false,false,'none',0,0.6,0.4,%s,0.6) RETURNING moneyline_game_prediction_id"""


@pytest.mark.parametrize('kind',['legacy_market','identity_only','034'])
def test_runtime_prediction_history_settlement_direct_bypasses_refuse(db,kind):
    pair=category_pair(db,kind);run=preview_run(db);retire_category(db,pair);restricted_roles(db)
    args=(run,pair['subject'],pair['pk'],pair['h'],pair['a'],pair['h'])
    with pytest.raises(psycopg2.Error,match='sealed|stale|Retired'):
        role_query(db,'retirement171_runtime',PREDICTION_SQL,args)
    survivor=role_query(db,'retirement171_runtime',PREDICTION_SQL,(run,pair['survivor'],pair['pk'],pair['h'],pair['a'],pair['h']))[0][0]
    with pytest.raises(psycopg2.Error,match='sealed|stale|Retired'):
        role_query(db,'retirement171_runtime','UPDATE moneyline_game_predictions SET game_id=%s WHERE moneyline_game_prediction_id=%s',(pair['subject'],survivor))
    with pytest.raises(psycopg2.Error,match='sealed|stale|Retired'):
        role_query(db,'retirement171_runtime',"INSERT INTO historical_games(game_id,mlb_game_id,game_date,home_team,away_team,home_score,away_score,home_win) VALUES(%s,999999,'2026-07-12',%s,%s,3,1,true)",(pair['subject'],pair['home'],pair['away']))
    with pytest.raises(psycopg2.Error,match='sealed|stale|Retired'):
        role_query(db,'retirement171_runtime',"INSERT INTO moneyline_paper_candidate_settlements(moneyline_prediction_market_evaluation_id,game_id,home_score,away_score,outcome,profit_units) VALUES(999,%s,3,1,'win',1)",(pair['subject'],))
    assert query(db,'SELECT count(*) FROM moneyline_game_predictions WHERE game_id=%s',(pair['subject'],))==[(0,)]
    SCENARIO_EVIDENCE.append(dict(scenario='direct_decision_bypass',category=kind,role='retirement171_runtime',retired_prediction_and_retarget_and_history_and_settlement_refused=True,survivor_prediction=survivor))


@pytest.mark.parametrize('kind',['legacy_market','034'])
@pytest.mark.parametrize('candidate',[False,True])
def test_runtime_survivor_evaluation_using_subject_market_refuses(db,kind,candidate):
    pair=category_pair(db,kind);run=preview_run(db);retire_category(db,pair);restricted_roles(db)
    pred=role_query(db,'retirement171_runtime',PREDICTION_SQL,(run,pair['survivor'],pair['pk'],pair['h'],pair['a'],pair['h']))[0][0]
    market,odds,book=query(db,'SELECT odds_market_snapshot_id,odds_ingestion_run_id,sportsbook_id FROM odds_market_snapshots WHERE game_id=%s LIMIT 1',(pair['subject'],))[0]
    sql="""INSERT INTO moneyline_prediction_market_evaluations(moneyline_game_prediction_id,odds_ingestion_run_id,odds_market_snapshot_id,sportsbook_id,
      snapshot_time,selection_name,price,model_probability,market_no_vig_probability,sportsbook_count,implied_probability,model_market_edge,model_price_edge,
      model_expected_value,starter_coverage,home_starter_features_available,away_starter_features_available,policy_version,qualifies_as_paper_candidate,
      disqualification_reasons,starter_match_status) VALUES(%s,%s,%s,%s,'2026-07-11T00:00:00Z',%s,-110,0.6,0.5,1,0.5,0.1,0.1,0.2,'none',false,false,
      'synthetic171-EarlyEntry-policy',%s,ARRAY['synthetic171']::text[],'matched')"""
    with pytest.raises(psycopg2.Error,match='sealed|stale|Retired'):
        role_query(db,'retirement171_runtime',sql,(pred,odds,market,book,pair['home'],candidate))
    assert query(db,'SELECT count(*) FROM moneyline_prediction_market_evaluations')==[(0,)]
    SCENARIO_EVIDENCE.append(dict(scenario='indirect_evaluation_candidate_refusal',category=kind,candidate=candidate,role='retirement171_runtime',survivor_prediction=pred,subject_snapshot=market))


@pytest.mark.parametrize('kind',['legacy_market','identity_only'])
@pytest.mark.parametrize('operation',['source','legacy_odds_identity','market','delete_source','price','time','retarget','truncate','run_identity'])
def test_restricted_runtime_sealed_provenance_matrix(db,kind,operation):
    pair=category_pair(db,kind);retire_category(db,pair);restricted_roles(db)
    subject=pair['subject'];before=business_digest(db)
    operations={
      'source':("INSERT INTO game_sources(game_id,source_name,external_game_id) VALUES(%s,'odds_api','synthetic171-forbidden')",(subject,)),
      'legacy_odds_identity':("UPDATE games SET odds_api_event_id='synthetic171-forbidden' WHERE game_id=%s",(subject,)),
      'market':("INSERT INTO odds_market_snapshots(game_id,sportsbook_id,market_type,selection_name,price,snapshot_time,source_name) SELECT %s,sportsbook_id,'h2h',%s,-110,'2026-07-11','odds_api' FROM sportsbooks LIMIT 1",(subject,pair['home'])),
      'delete_source':('DELETE FROM game_sources WHERE game_id=%s',(subject,)),
      'price':('UPDATE odds_market_snapshots SET price=-120 WHERE game_id=%s',(subject,)),
      'time':('UPDATE odds_snapshots SET snapshot_time=snapshot_time+interval \'1 minute\' WHERE game_id=%s',(subject,)),
      'retarget':('UPDATE odds_market_snapshots SET game_id=%s WHERE game_id=%s',(pair['survivor'],subject)),
      'truncate':('TRUNCATE odds_market_snapshots CASCADE',()),
      'run_identity':("UPDATE odds_ingestion_runs SET started_at=started_at-interval '1 minute' WHERE odds_ingestion_run_id IN(SELECT odds_ingestion_run_id FROM odds_market_snapshots WHERE game_id=%s)",(subject,)),
    }
    if kind=='identity_only' and operation in ('delete_source','price','time','retarget','run_identity'):
        # These zero-lineage operations are no-ops, not evidence mutations.
        role_query(db,'retirement171_runtime',*operations[operation])
    else:
        if operation=='truncate':
            # Grant the bounded FK cascade closure only for this adversarial
            # test. Otherwise ACL denial on a child would mask the raw guard.
            related=query(db,"""WITH RECURSIVE r(oid) AS(SELECT 'odds_market_snapshots'::regclass::oid UNION
              SELECT k.conrelid FROM pg_constraint k JOIN r ON k.confrelid=r.oid WHERE k.contype='f')
              SELECT c.relname FROM r JOIN pg_class c ON c.oid=r.oid WHERE c.relnamespace='public'::regnamespace ORDER BY c.relname""")
            for table, in related:
                assert table.replace('_','').isalnum() and not table.startswith('mlb_')
                query(db,'GRANT TRUNCATE ON '+table+' TO retirement171_runtime')
        with pytest.raises(psycopg2.Error,match='sealed|TRUNCATE|provenance|legacy|Legacy'):
            role_query(db,'retirement171_runtime',*operations[operation])
    assert business_digest(db)==before
    SCENARIO_EVIDENCE.append(dict(scenario='sealed_provenance',category=kind,operation=operation,
        zero_lineage_noop=kind=='identity_only' and operation in ('delete_source','price','time','retarget','run_identity'),business_rows_unchanged=True))


@pytest.mark.parametrize('kind',['legacy_market','identity_only','034'])
def test_normal_results_and_reconciliation_never_target_retired_subject(db,kind):
    from sportsmodel.ingest.mlb_stats import save_historical_result
    from sportsmodel.operations.mlb_reconcile import preview_reconciliation
    from sportsmodel.database.mlb_retirement_guard import canonical_json
    pair=category_pair(db,kind);retire_category(db,pair);before=business_digest(db)
    c=db()
    try:
        with c.cursor() as cur:
            with pytest.raises(psycopg2.Error,match='sealed|stale|Retired'):
                save_historical_result(cur,pair['subject'],999999,date(2026,7,12),pair['home'],pair['away'],3,1)
    finally:c.rollback();c.close()
    raw,evidence,target=request(db,dict(pair,category='IDENTITY_ONLY_DUPLICATE'))
    import zipfile
    from io import BytesIO
    with zipfile.ZipFile(BytesIO(evidence)) as z:payload=z.read('synthetic_schedule.json')
    sources=[dict(source_name=s,external_game_id=e) for s,e in query(db,'SELECT source_name,external_game_id FROM game_sources WHERE game_id=%s ORDER BY source_name,external_game_id',(pair['subject'],))]
    allow=dict(version=1,domain='MLB',target_date='2026-07-12',payload_sha256=sha256(payload).hexdigest(),games=[dict(game_pk=pair['pk'],
        home_team=pair['home'],away_team=pair['away'],expected_start='2026-07-12T18:10:00Z',existing_game_id=pair['subject'],current_sources=sources,
        resulting_sources=sorted(sources+[dict(source_name='mlb_stats',external_game_id=str(pair['pk']))],key=lambda r:(r['source_name'],r['external_game_id'])))])
    with pytest.raises((ValueError,psycopg2.Error)):
        preview_reconciliation(payload_bytes=payload,allowlist_bytes=canonical_json(allow).encode(),target=target,connection_factory=db)
    assert business_digest(db)==before
    SCENARIO_EVIDENCE.append(dict(scenario='results_reconciliation_refusal',category=kind,retired_subject=pair['subject'],no_translation=True,no_writes=True))


@pytest.mark.parametrize('case',['conditional','TBD','cancelled','postponed','unknown_type','unknown_club','wrong_date','distinct_game','two_games','reverse','missing_proof','unclear_publication'])
def test_false_event_or_ambiguous_proof_refuses(db,case):
    from sportsmodel.operations.mlb_legacy_retirement import preview_retirement
    from io import BytesIO
    import zipfile
    pair=category_pair(db,'identity_only');raw,evidence,target=request(db,pair)
    body=json.loads(raw)
    with zipfile.ZipFile(BytesIO(evidence)) as z:payload=json.loads(z.read('synthetic_schedule.json'))
    game=payload['dates'][0]['games'][0]
    if case=='conditional':game['ifNecessary']='Y'
    elif case=='TBD':game['status']['startTimeTBD']=True
    elif case in ('cancelled','postponed'):game['status']['detailedState']='Cancelled' if case=='cancelled' else 'Postponed'
    elif case=='unknown_type':game['gameType']='?'
    elif case=='unknown_club':game['teams']['home']['team']['id']=999999
    elif case=='wrong_date':payload['dates'][0]['date']='2026-07-13'
    elif case=='distinct_game':game['gamePk']=999999;body['game_pk']=999999
    elif case=='two_games':payload['dates'][0]['games'].append(dict(game,gamePk=999999))
    elif case=='reverse':game['teams']['home'],game['teams']['away']=game['teams']['away'],game['teams']['home']
    elif case=='missing_proof':body['duplicate_proof_approved']=False
    else:body['publication_attribution_clear']=False
    b=json.dumps(payload).encode();stream=BytesIO()
    with zipfile.ZipFile(stream,'w') as z:z.writestr('synthetic_schedule.json',b)
    evidence=stream.getvalue();body.update(evidence_sha256=sha256(evidence).hexdigest(),mlb_payload_sha256=sha256(b).hexdigest())
    with pytest.raises((ValueError,psycopg2.Error)):
        preview_retirement(request_bytes=json.dumps(body).encode(),evidence_bytes=evidence,target=target,connection_factory=db)
    assert state(db)==(1,0,0)


def test_historical_v1_null_metadata_unchanged_by_exact035(db):
    # Start only after db() has positively pinned container/database/storage.
    # Rebuild a KNOWN001–034 boundary, seed historical rows, then apply ONLY035.
    from sportsmodel.database.mlb_retirement_repository import verify_capabilities
    c=db()
    try:
        with c.cursor() as cur:
            cur.execute('DROP SCHEMA public CASCADE; CREATE SCHEMA public')
            cur.execute((ROOT/'tests/fixtures/database/sportsmodel_foundation_schema.sql').read_text(encoding='utf-8-sig'))
            cur.execute('CREATE TABLE schema_migrations(version integer primary key,filename text not null unique,checksum char(64) not null)')
            paths=[p for p in sorted((ROOT/'database/migrations').glob('*.sql')) if int(p.name[:3])<=34]
            assert [int(p.name[:3]) for p in paths]==list(range(1,35))
            for p in paths:
                if p.name.startswith('007_'):
                    cur.execute("INSERT INTO teams(team_name) VALUES('Synthetic Legacy Home'),('Synthetic Legacy Away'); INSERT INTO games(game_date,home_team_id,away_team_id) SELECT '2025-01-01',h.team_id,a.team_id FROM teams h,teams a WHERE h.team_name='Synthetic Legacy Home' AND a.team_name='Synthetic Legacy Away'; INSERT INTO sportsbooks(name) VALUES('Synthetic Legacy Book'); INSERT INTO odds_market_snapshots(game_id,sportsbook_id,market_type,selection_name,price,snapshot_time) SELECT game_id,sportsbook_id,'h2h','Synthetic Legacy Home',-110,'2025-01-01' FROM games,sportsbooks")
                sql=p.read_text(encoding='utf-8-sig');cur.execute(sql)
                cur.execute('INSERT INTO schema_migrations VALUES(%s,%s,%s)',(int(p.name[:3]),p.name,sha256(sql.encode()).hexdigest()))
            cur.execute('SELECT mlb_identity_ledger_fingerprint(),clock_timestamp()');fp,now=cur.fetchone()
            v1=json.dumps(dict(version=1,ledger_fingerprint=fp,artifact_sha256='a'*64,available_at=now.isoformat()))
            cur.execute("INSERT INTO moneyline_prediction_runs(target_date,model_version,feature_schema_version,model_artifact_sha256,run_type,identity_disposition_knowledge) VALUES('2026-07-12','synthetic171','synthetic171',%s,'preview',NULL),('2026-07-12','synthetic171','synthetic171',%s,'preview',%s::jsonb)",('a'*64,'a'*64,v1))
            cur.execute('SELECT to_jsonb(r)::text FROM moneyline_prediction_runs r ORDER BY moneyline_prediction_run_id');before=cur.fetchall()
            cur.execute('SELECT max(version),count(*) FROM schema_migrations');assert cur.fetchone()==(34,34)
            p=ROOT/'database/migrations/035_create_mlb_legacy_identity_retirements.sql';sql=p.read_text(encoding='utf-8-sig');cur.execute(sql)
            cur.execute('INSERT INTO schema_migrations VALUES(35,%s,%s)',(p.name,sha256(sql.encode()).hexdigest()))
            cur.execute("SELECT (to_jsonb(r)-'identity_retirement_knowledge')::text FROM moneyline_prediction_runs r ORDER BY moneyline_prediction_run_id");assert cur.fetchall()==before
            cur.execute('SELECT identity_retirement_knowledge FROM moneyline_prediction_runs');assert cur.fetchall()==[(None,),(None,)]
            assert verify_capabilities(cur)
        c.commit()
    finally:c.close()
    SCENARIO_EVIDENCE.append(dict(scenario='historical_metadata_actual_migration',v1_and_NULL_rows_unchanged=True,applied_boundary='known001–034 then035only'))


@pytest.mark.parametrize('case',['absent_context','wrong_metadata'])
def test_new_run_cannot_reserve_without_exact_v2(db,case):
    from sportsmodel.database.mlb_retirement_repository import capture_identity_knowledge,install_identity_knowledge
    c=db()
    try:
        if case=='wrong_metadata':
            proof=capture_identity_knowledge(connection_factory=db);cutoff=query(db,'SELECT clock_timestamp()')[0][0]
            with c.cursor() as cur:install_identity_knowledge(cur,proof,cutoff_time=cutoff,current_factory=db)
        with c.cursor() as cur:
            with pytest.raises(psycopg2.Error):
                cur.execute("INSERT INTO moneyline_prediction_runs(target_date,model_version,feature_schema_version,model_artifact_sha256,run_type,identity_retirement_knowledge) VALUES('2026-07-12','synthetic171','synthetic171',%s,'preview',%s::jsonb)",('a'*64,json.dumps(dict(version=2))))
    finally:c.rollback();c.close()
    assert query(db,'SELECT count(*) FROM moneyline_prediction_runs')==[(0,)]


def provider_run(db):
    return query(db,"INSERT INTO odds_ingestion_runs(source_name,sport,status,snapshot_role,started_at,request_started_at,response_received_at,status_code,request_path,request_regions,request_markets,request_odds_format) VALUES('odds_api','baseball_mlb','running','manual','2026-07-11T03:00:00Z','2026-07-11T03:00:00Z','2026-07-11T03:00:01Z',200,'synthetic171','us','h2h','american') RETURNING odds_ingestion_run_id")[0][0]


def test_legacy_provider_observation_seal_and_run_lifecycle(db):
    pair=category_pair(db,'legacy_market');retire_category(db,pair);restricted_roles(db);run=provider_run(db)
    before=query(db,'SELECT count(*) FROM odds_provider_event_observations')
    with pytest.raises(psycopg2.Error,match='sealed'):
        role_query(db,'retirement171_runtime',"INSERT INTO odds_provider_event_observations(odds_ingestion_run_id,source_name,provider_sport_key,external_event_id,provider_commence_time,provider_home_team_name,provider_away_team_name,observed_at) VALUES(%s,'odds_api','baseball_mlb','synthetic-legacy-29','2026-07-12T18:11:00Z',%s,%s,'2026-07-11T03:00:01Z')",(run,pair['home'],pair['away']))
    assert query(db,'SELECT count(*) FROM odds_provider_event_observations')==before
    existing=query(db,'SELECT odds_ingestion_run_id FROM odds_market_snapshots WHERE game_id=29 LIMIT 1')[0][0]
    role_query(db,'retirement171_runtime','UPDATE odds_ingestion_runs SET games_processed=coalesce(games_processed,0)+1 WHERE odds_ingestion_run_id=%s',(existing,))
    assert query(db,'SELECT games_processed FROM odds_ingestion_runs WHERE odds_ingestion_run_id=%s',(existing,))==[(1,)]


def test_034_raw_continuity_stays_append_only_at035(db):
    old=frozen034_helpers()
    # Execute the frozen original append-continuity assertion against035,
    # including exact source observation shape and physical/raw/effective IDs.
    old.test_existing_stale_raw_event_can_append_without_transfer(db)
    assert query(db,'SELECT count(*) FROM mlb_legacy_identity_retirements')==[(0,)]


def test_actual_old034_target_guard_refuses035(db):
    import importlib.util,sys
    from pathlib import Path
    file=Path(__file__).resolve().parents[2]  # verified local baseline export path follows
    file=Path(os.environ['SPORTSMODEL_FROZEN034_EXPORT'])/'src/sportsmodel/database/mlb_operator_guard.py'
    spec=importlib.util.spec_from_file_location('frozen_guard171',file);module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module)
    target=module.OperatorTarget(**dict(target_for(db).artifact(),migration_boundary=34))
    c=db();c.set_session(readonly=True,isolation_level='REPEATABLE READ')
    try:
        with pytest.raises(module.OperatorRefusal,match='001|034|migration|schema|identity'):module.verify_target(c,target,readonly=True)
    finally:c.rollback();c.close()


@pytest.mark.parametrize('relation,column',[('games','game_id'),('odds_market_snapshots','odds_market_snapshot_id'),
    ('moneyline_prediction_runs','moneyline_prediction_run_id'),('moneyline_game_predictions','moneyline_game_prediction_id'),
    ('moneyline_prediction_market_evaluations','moneyline_prediction_market_evaluation_id')])
def test_unknown_aliased_foreign_key_dependency_refuses035(db,relation,column):
    from sportsmodel.database.mlb_retirement_repository import require_schema035,IdentityDispositionError
    pair=category_pair(db,'identity_only')
    query(db,'CREATE TABLE synthetic171_unknown_dependency(canonical_ref bigint REFERENCES '+relation+'('+column+'))')
    if relation=='games':query(db,'INSERT INTO synthetic171_unknown_dependency VALUES(584)')
    with pytest.raises(IdentityDispositionError):require_schema035(db)


@pytest.mark.parametrize('table',['synthetic171_unknown_dependency','nflx_shared_dependency'])
def test_executor_cannot_bypass_unknown_dependency_inventory(db,table):
    pair=category_pair(db,'identity_only');activation,preview=prepared(db,pair);restricted_roles(db)
    assert table in ('synthetic171_unknown_dependency','nflx_shared_dependency')
    query(db,'CREATE TABLE '+table+'(canonical_ref integer REFERENCES games(game_id)); INSERT INTO '+table+' VALUES(584)')
    activation['expected_pair_sha256']=query(db,'SELECT mlb_retirement_pair_fingerprint(584,26)')[0][0]
    before=state(db)
    with pytest.raises(psycopg2.Error,match='Unknown semantic foreign-key'):
        role_query(db,'retirement171_executor','SELECT mlb_retirement_activate(%s::jsonb)',(json.dumps(activation),))
    assert state(db)==before


@pytest.mark.parametrize('isolation',['REPEATABLE READ','SERIALIZABLE'])
def test_measured_wait_actual_v2_install_refuses_old_snapshot(db,isolation):
    from sportsmodel.database.mlb_retirement_repository import capture_identity_knowledge,install_identity_knowledge,IdentityDispositionError
    pair=category_pair(db,'identity_only');activation,preview=prepared(db,pair)
    proof=capture_identity_knowledge(connection_factory=db);cutoff=query(db,'SELECT clock_timestamp()')[0][0]
    a=db();a.set_session(readonly=True,isolation_level=isolation)
    with a.cursor() as cur:cur.execute('SELECT epoch,pg_current_snapshot()::text FROM mlb_identity_topology_fence');before=cur.fetchone()
    b=db();b.set_session(isolation_level='SERIALIZABLE')
    with b.cursor() as cur:cur.execute('SELECT mlb_retirement_activate(%s::jsonb)',(json.dumps(activation),));receipt=cur.fetchone()[0]
    out=[]
    def installed():
        tick=time.perf_counter()
        try:
            with a.cursor() as cur:install_identity_knowledge(cur,proof,cutoff_time=cutoff,current_factory=db)
            out.append(dict(outcome='UNSAFE_SUCCESS'))
        except IdentityDispositionError as e:out.append(dict(refusal=str(e),elapsed_ms=(time.perf_counter()-tick)*1000))
    t=threading.Thread(target=installed);t.start();locks=wait_for_advisory(db,a.info.backend_pid)
    with b.cursor() as cur:cur.execute('SELECT pg_sleep(.15),clock_timestamp()');release=cur.fetchone()[1]
    b.commit();b.close();t.join(10)
    try:
        assert not t.is_alive() and 'Committed retirement changed' in out[0].get('refusal','') and out[0]['elapsed_ms']>=100
        SCENARIO_EVIDENCE.append(dict(scenario='measured_wait_actual_v2',isolation=isolation,before=before,blocked_locks=locks,release=release,
            after=state(db),result=out[0],receipt=receipt,feature_query_reached=False))
    finally:a.rollback();a.close()


def test_history_writer_wins_real_gate_race_without_partial_retirement(db):
    pair=category_pair(db,'identity_only');activation,preview=prepared(db,pair)
    a=db();a.set_session(isolation_level='SERIALIZABLE')
    with a.cursor() as cur:cur.execute('SELECT mlb_retirement_topology_fresh()')
    b=db();b.set_session(isolation_level='SERIALIZABLE');out=[]
    def retiring():
        try:
            with b.cursor() as cur:cur.execute('SELECT mlb_retirement_activate(%s::jsonb)',(json.dumps(activation),))
            b.commit();out.append('UNSAFE_SUCCESS')
        except psycopg2.Error as e:b.rollback();out.append(dict(sqlstate=e.pgcode,refusal=str(e).splitlines()[0]))
    t=threading.Thread(target=retiring);t.start();locks=wait_for_advisory(db,b.info.backend_pid)
    with a.cursor() as cur:
        cur.execute("INSERT INTO historical_games(game_id,mlb_game_id,game_date,home_team,away_team,home_score,away_score,home_win) VALUES(584,999999,'2026-07-12',%s,%s,3,1,true)",(pair['home'],pair['away']))
    a.commit();a.close();t.join(10)
    try:
        assert not t.is_alive() and isinstance(out[0],dict) and out[0]['sqlstate'] in ('40001','P0001')
        assert state(db)==(1,0,0) and query(db,'SELECT count(*) FROM historical_games WHERE game_id=584')==[(1,)]
        SCENARIO_EVIDENCE.append(dict(scenario='history_writer_activation_race',blocked_locks=locks,result=out[0],partial_retirement=False,legal_history_writer_committed=True))
    finally:b.rollback();b.close()


def role_factory(db,role):
    def connected():
        c=db()
        with c.cursor() as cur:
            cur.execute('SET ROLE '+role)
            cur.execute('SELECT current_user,rolsuper FROM pg_roles WHERE rolname=current_user')
            assert cur.fetchone()==(role,False)
        c.commit();return c
    return connected


def test_actual_runtime_v2_capture_and_run_repository(db):
    from sportsmodel.database.mlb_retirement_repository import capture_identity_knowledge,install_identity_knowledge
    from sportsmodel.database.moneyline_prediction_repository import create_moneyline_prediction_run
    restricted_roles(db);factory=role_factory(db,'retirement171_runtime')
    proof=capture_identity_knowledge(connection_factory=factory);cutoff=query(db,'SELECT clock_timestamp()')[0][0]
    c=factory()
    try:
        with c.cursor() as cur:install_identity_knowledge(cur,proof,cutoff_time=cutoff,current_factory=factory)
        rid=create_moneyline_prediction_run(c,target_date=cutoff.date(),model_version='synthetic171',feature_schema_version='synthetic171',
            model_artifact_sha256='a'*64,model_training_cutoff=None,run_type='preview')
    finally:c.close()
    assert query(db,"SELECT identity_retirement_knowledge->>'fingerprint' FROM moneyline_prediction_runs WHERE moneyline_prediction_run_id=%s",(rid,))==[(proof.fingerprint,)]
    with pytest.raises(psycopg2.errors.InsufficientPrivilege):
        role_query(db,'retirement171_runtime',"SELECT nextval('mlb_legacy_identity_retirements_retirement_id_seq')")
    SCENARIO_EVIDENCE.append(dict(scenario='runtime_actual_capture_run',role='retirement171_runtime',superuser=False,run_id=rid,committed_sealed_proof=proof.body()))


@pytest.mark.parametrize('dependency',['prediction','early_entry','completed_publication_run','evaluation','candidate','settlement'])
def test_admission_betting_dependency_matrix(db,dependency):
    pair=category_pair(db,'legacy_market');run=preview_run(db);restricted_roles(db)
    direct=dependency in ('prediction','early_entry','completed_publication_run')
    gid=pair['subject'] if direct else pair['survivor']
    pred=role_query(db,'retirement171_runtime',PREDICTION_SQL,(run,gid,pair['pk'],pair['h'],pair['a'],pair['h']))[0][0]
    if dependency=='early_entry':query(db,"UPDATE moneyline_prediction_runs SET model_version='synthetic171-EarlyEntry' WHERE moneyline_prediction_run_id=%s",(run,))
    if dependency=='completed_publication_run':
        query(db,"UPDATE moneyline_prediction_runs SET status='completed',completed_at=clock_timestamp() WHERE moneyline_prediction_run_id=%s",(run,))
        query(db,"INSERT INTO moneyline_daily_workflow_runs(target_date,status,current_stage,moneyline_prediction_run_id) VALUES('2026-07-12','completed','complete',%s)",(run,))
    if not direct:
        if dependency=='settlement':
            # Independent new survivor market, not a reassignment/price transfer.
            market=query(db,"INSERT INTO odds_market_snapshots(game_id,sportsbook_id,market_type,selection_name,price,snapshot_time,source_name,odds_ingestion_run_id) SELECT %s,sportsbook_id,'h2h',%s,-125,'2026-07-11T02:00:00Z','odds_api',odds_ingestion_run_id FROM odds_market_snapshots WHERE game_id=29 LIMIT 1 RETURNING odds_market_snapshot_id",(pair['survivor'],pair['home']))[0][0]
        else:market=query(db,'SELECT odds_market_snapshot_id FROM odds_market_snapshots WHERE game_id=29 LIMIT 1')[0][0]
        odds,book=query(db,'SELECT odds_ingestion_run_id,sportsbook_id FROM odds_market_snapshots WHERE odds_market_snapshot_id=%s',(market,))[0]
        qualified=dependency=='candidate';reasons=[] if qualified else ['synthetic171']
        evaluation=query(db,"""INSERT INTO moneyline_prediction_market_evaluations(moneyline_game_prediction_id,odds_ingestion_run_id,odds_market_snapshot_id,sportsbook_id,
          snapshot_time,selection_name,price,model_probability,market_no_vig_probability,sportsbook_count,implied_probability,model_market_edge,model_price_edge,
          model_expected_value,starter_coverage,home_starter_features_available,away_starter_features_available,policy_version,qualifies_as_paper_candidate,
          disqualification_reasons,starter_match_status) VALUES(%s,%s,%s,%s,'2026-07-11T02:00:00Z',%s,-125,0.6,0.5,1,0.5,0.1,0.1,0.2,'none',false,false,
          'synthetic171',%s,%s,'matched') RETURNING moneyline_prediction_market_evaluation_id""",(pred,odds,market,book,pair['home'],qualified,reasons))[0][0]
        if dependency=='settlement':query(db,"INSERT INTO moneyline_paper_candidate_settlements(moneyline_prediction_market_evaluation_id,game_id,home_score,away_score,outcome,profit_units) VALUES(%s,29,3,1,'win',1)",(evaluation,))
    before=state(db)
    with pytest.raises(psycopg2.Error,match='Subject history/decision dependency'):retire_category(db,pair)
    assert state(db)==before
    SCENARIO_EVIDENCE.append(dict(scenario='admission_betting_dependency',dependency=dependency,subject=29,attributed_prediction=pred,activation_refused=True))


@pytest.mark.parametrize('kind',['legacy_market','identity_only','034'])
def test_actual_recovery_results_boxscore_refuse_corrupted_retired_mapping(db,kind,monkeypatch):
    from sportsmodel.ingest import mlb_recovery,mlb_stats,boxscore_ingestion
    pair=category_pair(db,kind);retire_category(db,pair)
    from copy import deepcopy
    payload=json.loads((ROOT/'tests/fixtures/mlb_recovery/synthetic.json').read_text())
    def changed(value):
        if isinstance(value,dict):return {('777001' if k=='800' else k):changed(v) for k,v in value.items()}
        if isinstance(value,list):return [changed(v) for v in value]
        if type(value) is int:return 777001 if value==800 else pair['home_external'] if value==10 else pair['away_external'] if value==20 else value
        if isinstance(value,str):return value.replace('2025-08-01','2026-07-12').replace('2025-08-02','2026-07-13').replace('Synthetic Home',pair['home']).replace('Synthetic Away',pair['away'])
        return value
    payload=changed(payload);event=payload['schedule']['dates'][0]['games'][0]
    event.update(ifNecessary='N');event['status']['startTimeTBD']=False
    # Deliberate owner-only source corruption. Runtime/entry cannot add this
    # source; restore the exact guards before exercising actual consumers.
    query(db,"ALTER TABLE game_sources DISABLE TRIGGER USER; INSERT INTO game_sources(game_id,source_name,external_game_id) VALUES(%s,'mlb_stats','777001'); ALTER TABLE game_sources ENABLE TRIGGER USER",(pair['subject'],))
    before=business_digest(db);callbacks=[]
    spec=mlb_recovery.RecoverySpecification(date(2026,7,12),(777001,),'a'*40)
    with pytest.raises(psycopg2.Error,match='Retired'):
        mlb_recovery.plan_recovery(spec,payload,connection_factory=db)
    # Negative external approval: correctly hashed pinned payload with a false
    # old DB snapshot is not authority. Actual execute must independently refuse.
    fake=dict(games={'777001':dict(game_id=pair['subject'],source_id=999,start='2026-07-12T18:11:00+00:00',
              home_team_id=pair['h'],away_team_id=pair['a'],mlb_game_id=None,odds_api_event_id=None,sources=[])},
        teams={str(pair['home_external']):pair['h'],str(pair['away_external']):pair['a']},players={'100':None,'200':None},
        identity_disposition=dict(cases=[],events=[],active={},fingerprint='a'*64))
    forged=mlb_recovery.build_manifest(spec,payload,fake)
    execution=mlb_recovery.execute_recovery(forged,forged['manifest_sha256'],code_revision='a'*40,
        acknowledge_writes=True,connection_factory=db)
    assert execution['status']=='failed-before-write' and execution['committed_results']==[] and execution['committed_boxscores']==[]
    for name in ('fetch_live_feed','fetch_boxscore'):
        monkeypatch.setattr(boxscore_ingestion,name,lambda *a:callbacks.append('provider') or pytest.fail('Provider reached'))
    with pytest.raises(psycopg2.Error,match='Retired'):
        boxscore_ingestion.ingest_boxscore(game_id=pair['subject'],game_pk=777001,connection_factory=db)
    result=mlb_stats.fetch_historical_results(start_date=date(2026,7,12),end_date=date(2026,7,12),connection_factory=db,
        schedule_fetcher=lambda day:payload['schedule'],boxscore_ingestor=lambda **k:callbacks.append('boxscore') or pytest.fail('Boxscore reached'),
        historical_result_saver=lambda **k:callbacks.append('write') or pytest.fail('History write reached'),progress_callback=None)
    assert result.date_summaries[0].database_error and result.games_processed==0 and callbacks==[]
    assert business_digest(db)==before
    SCENARIO_EVIDENCE.append(dict(scenario='actual_recovery_results_boxscore_refusal',category=kind,retired_subject=pair['subject'],
        source_corruption_fixture_only=True,provider_or_write_callbacks=callbacks,results_summary=result.date_summaries[0],execution=execution,business_rows_unchanged=True,
        schedule_source='pinned synthetic bytes only; no network provider'))


def test_034_revoke_refuses_legacy_dependent_survivor(db):
    pair=category_pair(db,'034');first=retire_category(db,pair)
    query(db,"INSERT INTO games(game_id,game_date,home_team_id,away_team_id) VALUES(3000,'2026-07-12T18:12:00Z',%s,%s)",(pair['h'],pair['a']))
    second=dict(pair,subject=3000,category='IDENTITY_ONLY_DUPLICATE');retire_category(db,second)
    # Remove only synthetic survivor history to exercise the additive union
    # reversal check, not merely the stronger original history precondition.
    for table in ('historical_games','team_game_statistics','player_game_pitching_statistics'):query(db,'DELETE FROM '+table+' WHERE game_id=26')
    case,event=query(db,'SELECT d.disposition_id,e.event_id FROM game_identity_dispositions d JOIN game_identity_disposition_events e USING(disposition_id)')[0]
    before=state(db)
    with pytest.raises(psycopg2.Error,match='Legacy dependent survivor'):
        frozen034_helpers().activate_sql(db,(pair['subject'],pair['survivor'],pair['h'],pair['a']),action='REVOKE',case=case,previous=event,sequence=2,evidence='c'*64)
    assert state(db)==before and query(db,'SELECT count(*) FROM mlb_active_retired_identities')==[(2,)]


@pytest.mark.parametrize('kind',['legacy_market','identity_only','034'])
def test_retirement_never_makes_survivor_complete_automatically(db,kind):
    pair=category_pair(db,kind);retire_category(db,pair)
    query(db,'DELETE FROM team_game_statistics WHERE game_id=%s',(pair['survivor'],))
    result=actual_h1(db,pair)
    assert result['status']=='FAIL' and pair['survivor'] in result['required_canonical_game_ids'] and pair['subject'] not in result['required_canonical_game_ids']
    SCENARIO_EVIDENCE.append(dict(scenario='survivor_incomplete',category=kind,report=result))


def test_v1_child_never_uses_second_capture_and_serialization_refuses(db,monkeypatch):
    import pickle
    from sportsmodel.database import mlb_retirement_repository as v2,mlb_identity_disposition_repository as v1
    monkeypatch.setattr(v1,'capture_identity_knowledge',lambda **k:pytest.fail('Independent v1 recapture reached'))
    pair=category_pair(db,'identity_only');retire_category(db,pair)
    proof=v2.capture_identity_knowledge(connection_factory=db);cutoff=query(db,'SELECT clock_timestamp()')[0][0]
    c=db()
    try:
        with c.cursor() as cur:
            v2.install_identity_knowledge(cur,proof,cutoff_time=cutoff,current_factory=db)
            cur.execute("SELECT current_setting('sportsmodel.identity_knowledge')::jsonb,current_setting('sportsmodel.retirement_knowledge')::jsonb")
            child,parent=cur.fetchone();assert child['available_at']==parent['available_at']==proof.available_at and child['ledger_fingerprint']==proof.ledger034
        c.rollback()
        with c.cursor() as cur:
            with pytest.raises(v2.IdentityDispositionError):v2.install_identity_knowledge(cur,pickle.loads(pickle.dumps(proof)),cutoff_time=cutoff,current_factory=db)
    finally:c.rollback();c.close()
    SCENARIO_EVIDENCE.append(dict(scenario='one_capture_child_and_deserialization',parent=parent,child=child,independent_recapture=False,deserialized_seal_refused=True))


@pytest.mark.parametrize('cutoff',[datetime(2026,7,12,tzinfo=timezone.utc),datetime(2026,8,1,tzinfo=timezone.utc),datetime(2026,10,8,tzinfo=timezone.utc)])
def test_actual_historical_cutoffs_and_future_execution_refuse(db,cutoff):
    from sportsmodel.database import mlb_retirement_repository as v2
    proof=v2.capture_identity_knowledge(connection_factory=db);c=db()
    try:
        with c.cursor() as cur:
            with pytest.raises(v2.IdentityDispositionError):v2.install_identity_knowledge(cur,proof,cutoff_time=cutoff,current_factory=db)
            with pytest.raises(v2.IdentityDispositionError):v2.install_identity_knowledge(cur,proof,cutoff_time=datetime.now(timezone.utc)+timedelta(seconds=30),current_factory=db)
    finally:c.rollback();c.close()


def test_commit_failure_before_send_rolls_back_and_inspection_never_retries(db):
    from sportsmodel.operations.mlb_legacy_retirement import preview_retirement,execute_retirement,inspect_receipt
    from sportsmodel.database.mlb_retirement_guard import OperatorRefusal
    pair=category_pair(db,'identity_only');raw,evidence,target=request(db,pair)
    # One immutable artifact pair through preview and execution. Rebuilding the
    # ZIP can change its header timestamp and correctly invalidate approval.
    preview_input=dict(request_bytes=raw,evidence_bytes=evidence)
    preview=preview_retirement(**preview_input,target=target,connection_factory=db)
    execution_input=dict(request_bytes=bytes(raw),evidence_bytes=bytes(evidence))
    assert execution_input['request_bytes']==preview_input['request_bytes']
    assert execution_input['evidence_bytes']==preview_input['evidence_bytes']
    assert preview['request']==json.loads(execution_input['request_bytes'])
    assert preview['request']['evidence_sha256']==sha256(execution_input['evidence_bytes']).hexdigest()
    before=state(db)
    class BeforeSend:
        def __init__(self):self.inner=db();self.attempts=0
        def __getattr__(self,n):return getattr(self.inner,n)
        def commit(self):self.attempts+=1;raise psycopg2.OperationalError('Synthetic171 before commit send')
    proxy=BeforeSend()
    with pytest.raises(OperatorRefusal,match='UNKNOWN'):
        execute_retirement(**execution_input,target=target,connection_factory=lambda:proxy,
            preview=preview,approved_preview_sha256=preview['preview_sha256'],acknowledge_writes=True)
    assert state(db)==before and proxy.attempts==1
    result=inspect_receipt(approved_preview_sha256=preview['preview_sha256'],target=target,connection_factory=db)
    assert result['status']=='NO_COMMITTED_RECEIPT_VISIBLE' and result['retry_authorized'] is False
    SCENARIO_EVIDENCE.append(dict(scenario='before_commit_send_fault',state_unchanged=True,attempts=proxy.attempts,inspection=result,
        preview_execution_bytes_identical=True,request_sha256=sha256(raw).hexdigest(),evidence_sha256=sha256(evidence).hexdigest()))


def test_actual_fence_update_order_and_gate_at_each_update(db):
    pair=category_pair(db,'identity_only');activation,preview=prepared(db,pair)
    query(db,"""CREATE TABLE synthetic171_fence_trace(ordinal bigint generated always as identity,physical_identity integer,gate_held boolean,recorded_at timestamptz);
      CREATE FUNCTION synthetic171_trace() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
      INSERT INTO synthetic171_fence_trace(physical_identity,gate_held,recorded_at) SELECT NEW.game_id,
        EXISTS(SELECT 1 FROM pg_locks WHERE pid=pg_backend_pid() AND locktype='advisory' AND classid=1397574724 AND objid=34 AND mode='ExclusiveLock' AND granted),clock_timestamp(); RETURN NULL; END $$;
      CREATE TRIGGER trace171_fences AFTER INSERT OR UPDATE ON mlb_game_identity_write_fences FOR EACH ROW EXECUTE FUNCTION synthetic171_trace();""")
    query(db,'SELECT mlb_retirement_activate(%s::jsonb)',(json.dumps(activation),))
    trace=query(db,'SELECT physical_identity,gate_held,recorded_at FROM synthetic171_fence_trace ORDER BY ordinal')
    assert [r[0] for r in trace]==[26,584] and all(r[1] for r in trace)
    SCENARIO_EVIDENCE.append(dict(scenario='actual_ascending_fence_order',trace=trace,exclusive_gate_verified_at_every_update=True))


def test_actual_gate_timeout_leaves_no_retirement_delta(db):
    pair=category_pair(db,'identity_only');activation,preview=prepared(db,pair);before=state(db)
    a=db()
    with a.cursor() as cur:cur.execute('SELECT mlb_identity_gate(false)')
    b=db()
    try:
        with b.cursor() as cur:
            cur.execute("SET LOCAL lock_timeout='120ms'")
            tick=time.perf_counter()
            with pytest.raises(psycopg2.errors.LockNotAvailable):cur.execute('SELECT mlb_retirement_activate(%s::jsonb)',(json.dumps(activation),))
            elapsed=(time.perf_counter()-tick)*1000
        b.rollback();assert elapsed>=100 and state(db)==before
        SCENARIO_EVIDENCE.append(dict(scenario='actual_gate_timeout',elapsed_ms=elapsed,state_unchanged=True,sqlstate='55P03'))
    finally:a.rollback();a.close();b.close()


@pytest.mark.parametrize('other_type',[False,True])
def test_real_concurrent_duplicate_or_incompatible_type_one_commit(db,other_type):
    pair=category_pair(db,'identity_only');activation,preview=prepared(db,pair);restricted_roles(db)
    other=json.loads(json.dumps(activation))
    if other_type:other['case']['category']='LEGACY_MARKET_DUPLICATE_WITHOUT_OBSERVATION_PROVENANCE';other['case']['approved_preview_sha256']='f'*64
    sessions=[role_factory(db,'retirement171_executor')() for _ in range(2)]
    for c in sessions:c.set_session(isolation_level='SERIALIZABLE')
    barrier=threading.Barrier(2);out=[]
    def worker(c,request):
        barrier.wait()
        try:
            with c.cursor() as cur:
                cur.execute('SELECT mlb_retirement_activate(%s::jsonb)',(json.dumps(request),));receipt=cur.fetchone()[0]
                cur.execute('SELECT pg_sleep(.05)')  # Real server-held transaction/gate.
            c.commit();out.append(dict(receipt=receipt))
        except psycopg2.Error as e:c.rollback();out.append(dict(sqlstate=e.pgcode))
    threads=[threading.Thread(target=worker,args=(c,r)) for c,r in zip(sessions,(activation,other))]
    for t in threads:t.start()
    for t in threads:t.join(15);assert not t.is_alive()
    for c in sessions:c.close()
    assert state(db)==(3,1,1) and any('receipt' in r for r in out)
    SCENARIO_EVIDENCE.append(dict(scenario='actual_concurrent_executor',incompatible_type=other_type,results=out,automatic_retry=False))


def test_statement_timeout_at_real_gate_leaves_no_partial_state(db):
    pair=category_pair(db,'identity_only');activation,preview=prepared(db,pair);before=state(db)
    a=db();b=db()
    try:
        with a.cursor() as cur:cur.execute('SELECT mlb_identity_gate(false)')
        with b.cursor() as cur:
            cur.execute("SET LOCAL lock_timeout='0'; SET LOCAL statement_timeout='120ms'")
            with pytest.raises(psycopg2.errors.QueryCanceled):cur.execute('SELECT mlb_retirement_activate(%s::jsonb)',(json.dumps(activation),))
        b.rollback();assert state(db)==before
        SCENARIO_EVIDENCE.append(dict(scenario='statement_timeout',sqlstate='57014',no_partial_state=True))
    finally:a.rollback();a.close();b.rollback();b.close()


@pytest.mark.parametrize('fault',['anchor_conflict','malformed_result','misoriented_team','incomplete_pitching','appearance_gap','future_history','unlinked_history','subject_legacy_id'])
def test_more_survivor_authority_faults_refuse_actual_preview(db,fault):
    from sportsmodel.operations.mlb_legacy_retirement import preview_retirement
    pair=category_pair(db,'identity_only')
    changes={
      'anchor_conflict':("UPDATE game_sources SET external_game_id='999999' WHERE game_id=26",()),
      'malformed_result':('UPDATE historical_games SET home_score=2 WHERE game_id=26',()),
      'misoriented_team':('UPDATE team_game_statistics SET is_home=NOT is_home WHERE game_id=26',()),
      'incomplete_pitching':('UPDATE player_game_pitching_statistics SET pitching_outs=26 WHERE game_id=26',()),
      'appearance_gap':('UPDATE player_game_pitching_statistics SET appearance_order=2 WHERE game_id=26',()),
      'future_history':("UPDATE team_game_statistics SET created_at=clock_timestamp()+interval '1 day' WHERE game_id=26",()),
      'unlinked_history':('UPDATE historical_games SET game_id=NULL WHERE game_id=26',()),
      'subject_legacy_id':('UPDATE games SET mlb_game_id=999999 WHERE game_id=584',()),
    }
    query(db,*changes[fault]);raw,evidence,target=request(db,pair);before=state(db)
    with pytest.raises((psycopg2.Error,ValueError)):preview_retirement(request_bytes=raw,evidence_bytes=evidence,target=target,connection_factory=db)
    assert state(db)==before


def test_atomic_capture_before_and_after_uncommitted_activation(db):
    from sportsmodel.database.mlb_retirement_repository import capture_identity_knowledge,install_identity_knowledge,IdentityDispositionError
    pair=category_pair(db,'identity_only');activation,preview=prepared(db,pair)
    initial=capture_identity_knowledge(connection_factory=db);b=db()
    try:
        with b.cursor() as cur:cur.execute('SELECT mlb_retirement_activate(%s::jsonb)',(json.dumps(activation),))
        during=capture_identity_knowledge(connection_factory=db)
        assert (during.ledger034,during.ledger035,during.topology_epoch)==(initial.ledger034,initial.ledger035,initial.topology_epoch)
        b.commit();after=capture_identity_knowledge(connection_factory=db)
        assert after.ledger034==initial.ledger034 and after.fingerprint!=initial.fingerprint and after.topology_epoch==initial.topology_epoch+2
        c=db()
        try:
            with c.cursor() as cur:
                with pytest.raises(IdentityDispositionError):install_identity_knowledge(cur,during,cutoff_time=query(db,'SELECT clock_timestamp()')[0][0],current_factory=db)
        finally:c.rollback();c.close()
        SCENARIO_EVIDENCE.append(dict(scenario='atomic_committed_capture',before=initial.body(),during=during.body(),after=after.body()))
    finally:b.rollback();b.close()


def test_real_cross_ledger_same_subject_proposals_one_legal_commit(db):
    pair=category_pair(db,'identity_only');activation,preview=prepared(db,pair)
    barrier=threading.Barrier(2);out=[]
    def legacy():
        barrier.wait()
        try:query(db,'SELECT mlb_retirement_activate(%s::jsonb)',(json.dumps(activation),));out.append('legacy_committed')
        except psycopg2.Error as e:out.append(e.pgcode)
    def original():
        barrier.wait()
        try:frozen034_helpers().activate_sql(db,(pair['subject'],pair['survivor'],pair['h'],pair['a']));out.append('UNSAFE_034')
        except psycopg2.Error as e:out.append(e.pgcode)
    threads=[threading.Thread(target=f) for f in (legacy,original)]
    for t in threads:t.start()
    for t in threads:t.join(15);assert not t.is_alive()
    assert 'legacy_committed' in out and 'UNSAFE_034' not in out and state(db)==(3,1,1)
    assert query(db,'SELECT count(*) FROM game_identity_dispositions')==[(0,)]
    SCENARIO_EVIDENCE.append(dict(scenario='real_cross_ledger_conflict',outcomes=out,automatic_retry=False))


def test_same_event_different_fixed_survivor_refuses_without_fabricated_anchor(db):
    pair=category_pair(db,'identity_only');retire_category(db,pair)
    query(db,"INSERT INTO games(game_id,game_date,home_team_id,away_team_id) VALUES(3000,'2026-07-12T18:12:00Z',%s,%s),(3001,'2026-07-12T18:13:00Z',%s,%s)",(pair['h'],pair['a'],pair['h'],pair['a']))
    with pytest.raises(psycopg2.Error):query(db,"SELECT mlb_retirement_cross_pair(3000,3001,%s,'034')",(pair['pk'],))
    assert state(db)==(3,1,1)


@pytest.mark.parametrize('kind',['legacy_market','identity_only','034'])
def test_runtime_033_correction_cannot_restore_retired_eligibility(db,kind):
    pair=category_pair(db,kind);retire_category(db,pair);restricted_roles(db)
    sequence=query(db,"SELECT pg_get_serial_sequence('odds_provider_event_canonical_corrections','odds_provider_event_canonical_correction_id')")[0][0]
    assert sequence.replace('.','').replace('_','').isalnum()
    query(db,'GRANT INSERT ON odds_provider_event_canonical_corrections TO retirement171_runtime; GRANT USAGE ON SEQUENCE '+sequence+' TO retirement171_runtime')
    obs=query(db,'SELECT odds_provider_event_observation_id FROM odds_provider_event_observations LIMIT 1')
    oid=obs[0][0] if obs else 999999
    with pytest.raises(psycopg2.Error,match='sealed|stale|Retired'):
        role_query(db,'retirement171_runtime',"INSERT INTO odds_provider_event_canonical_corrections(odds_provider_event_observation_id,original_game_id,corrected_game_id,correction_reason,evidence_reference) VALUES(%s,%s,%s,'synthetic171','synthetic171')",(oid,pair['subject'],pair['survivor']))
    assert query(db,'SELECT count(*) FROM odds_provider_event_canonical_corrections')==[(0,)]


@pytest.mark.parametrize('kind',['legacy_market','identity_only','034'])
def test_actual_late_history_created_at_is_not_retroactive(db,kind):
    from sportsmodel.database.mlb_retirement_repository import capture_identity_knowledge,knowledge_connection_factory
    from sportsmodel.database.team_statistics_repository import PostgresTeamStatisticsRepository
    pair=category_pair(db,kind);retire_category(db,pair)
    query(db,'DELETE FROM team_game_statistics WHERE game_id=%s',(pair['survivor'],))
    proof=capture_identity_knowledge(connection_factory=db);cutoff=query(db,'SELECT clock_timestamp()')[0][0]
    stat(db,'team_game_statistics',dict(game_id=pair['survivor'],team_id=pair['h'],is_home=True,runs=3,hits=5,at_bats=30))
    created=query(db,'SELECT created_at FROM team_game_statistics WHERE game_id=%s',(pair['survivor'],))[0][0]
    assert created>cutoff
    before=PostgresTeamStatisticsRepository(connection_factory=knowledge_connection_factory(db,proof,cutoff_time=cutoff)).get_completed_games_before(team_id=pair['h'],cutoff_time=cutoff,limit=200)
    assert before==()
    later=query(db,'SELECT clock_timestamp()')[0][0]
    after=PostgresTeamStatisticsRepository(connection_factory=knowledge_connection_factory(db,proof,cutoff_time=later)).get_completed_games_before(team_id=pair['h'],cutoff_time=later,limit=200)
    assert [r.game_id for r in after]==[pair['survivor']]
    SCENARIO_EVIDENCE.append(dict(scenario='late_history_not_retroactive',category=kind,earlier_cutoff=cutoff,actual_created_at=created,later_cutoff=later,earlier_window_empty=True,later_window=[r.game_id for r in after]))


@pytest.mark.parametrize('change',["DROP TRIGGER mlb_035_write_guard ON games","DROP FUNCTION mlb_identity_is_retired(integer) CASCADE"])
def test_missing_exact035_guard_or_function_refuses(db,change):
    from sportsmodel.database.mlb_retirement_repository import require_schema035,IdentityDispositionError
    query(db,change)
    with pytest.raises((IdentityDispositionError,psycopg2.Error)):require_schema035(db)


def test_actual_concurrent_different_pair_same_event_cannot_gain_second_survivor(db):
    pair=category_pair(db,'identity_only');activation,preview=prepared(db,pair);restricted_roles(db)
    # Different-date placeholders do not invalidate the legal reviewed pair's
    # unique-date proof. Their competing request falsely claims the SAME pk;
    # no second authoritative anchor or complete survivor is fabricated.
    query(db,"INSERT INTO games(game_id,game_date,home_team_id,away_team_id) VALUES(3000,'2026-07-13T18:12:00Z',%s,%s),(3001,'2026-07-13T18:13:00Z',%s,%s)",(pair['h'],pair['a'],pair['h'],pair['a']))
    wrong=json.loads(json.dumps(activation));wrong['case'].update(subject_game_id=3000,survivor_game_id=3001,approved_preview_sha256='f'*64)
    barrier=threading.Barrier(2);out=[]
    def worker(req):
        barrier.wait()
        try:role_query(db,'retirement171_executor','SELECT mlb_retirement_activate(%s::jsonb)',(json.dumps(req),));out.append('commit')
        except psycopg2.Error as e:out.append(e.pgcode)
    threads=[threading.Thread(target=worker,args=(req,)) for req in (activation,wrong)]
    for t in threads:t.start()
    for t in threads:t.join(15);assert not t.is_alive()
    assert out.count('commit')==1 and state(db)==(3,1,1)
    SCENARIO_EVIDENCE.append(dict(scenario='different_pair_same_event_concurrency',outcomes=out,second_survivor_without_authority_refused=True,automatic_retry=False))


@pytest.mark.parametrize('cohort',['Early Entry','Official'])
def test_real_cohort_selection_dependency_refuses_retirement(db,cohort):
    from sportsmodel.analysis.moneyline_cohort_comparison import COHORT_BETS_QUERY
    pair=category_pair(db,'legacy_market');run=preview_run(db);restricted_roles(db)
    pred=role_query(db,'retirement171_runtime',PREDICTION_SQL,(run,29,pair['pk'],pair['h'],pair['a'],pair['h']))[0][0]
    market,odds,book=query(db,'SELECT odds_market_snapshot_id,odds_ingestion_run_id,sportsbook_id FROM odds_market_snapshots WHERE game_id=29 LIMIT 1')[0]
    query(db,"UPDATE odds_ingestion_runs SET target_date='2026-07-12',snapshot_role='late_night' WHERE odds_ingestion_run_id=%s",(odds,))
    query(db,"UPDATE moneyline_prediction_runs SET target_date='2026-07-12' WHERE moneyline_prediction_run_id=%s",(run,))
    query(db,"""INSERT INTO moneyline_prediction_market_evaluations(moneyline_game_prediction_id,odds_ingestion_run_id,odds_market_snapshot_id,sportsbook_id,
      snapshot_time,selection_name,price,model_probability,market_no_vig_probability,sportsbook_count,implied_probability,model_market_edge,model_price_edge,
      model_expected_value,starter_coverage,home_starter_features_available,away_starter_features_available,policy_version,qualifies_as_paper_candidate,
      disqualification_reasons,starter_match_status) VALUES(%s,%s,%s,%s,'2026-07-11',%s,-110,.6,.5,1,.5,.1,.1,.2,'none',false,false,'synthetic171',true,'{}','matched')""",(pred,odds,market,book,pair['home']))
    if cohort=='Official':
        query(db,"UPDATE moneyline_prediction_runs SET run_type='official',status='completed',completed_at=clock_timestamp() WHERE moneyline_prediction_run_id=%s",(run,))
        query(db,"INSERT INTO moneyline_daily_workflow_runs(target_date,status,current_stage,moneyline_prediction_run_id,odds_ingestion_run_id) VALUES('2026-07-12','completed','complete',%s,%s)",(run,odds))
    selected=query(db,COHORT_BETS_QUERY,(date(2026,7,12),date(2026,7,12),'baseball_mlb',date(2026,7,12)))
    assert len(selected)==1 and selected[0][0]==cohort and selected[0][2]==29
    before=state(db)
    with pytest.raises(psycopg2.Error,match='Subject history/decision dependency'):retire_category(db,pair)
    assert state(db)==before
    SCENARIO_EVIDENCE.append(dict(scenario='actual_cohort_dependency',cohort=cohort,production_selection_sql_matched=True,subject=29,retirement_refused=True))


@pytest.mark.parametrize('isolation',['REPEATABLE READ','SERIALIZABLE'])
def test_measured_wait_old_activation_snapshot_refuses(db,isolation):
    pair=category_pair(db,'identity_only');activation,preview=prepared(db,pair);restricted_roles(db)
    a=role_factory(db,'retirement171_executor')();a.set_session(isolation_level=isolation)
    with a.cursor() as cur:cur.execute('SELECT epoch,pg_current_snapshot()::text FROM mlb_identity_topology_fence');before=cur.fetchone()
    b=role_factory(db,'retirement171_executor')();b.set_session(isolation_level='SERIALIZABLE')
    with b.cursor() as cur:cur.execute('SELECT mlb_retirement_activate(%s::jsonb)',(json.dumps(activation),))
    out=[]
    def stale_activation():
        tick=time.perf_counter()
        try:
            with a.cursor() as cur:cur.execute('SELECT mlb_retirement_activate(%s::jsonb)',(json.dumps(activation),))
            out.append(dict(outcome='UNSAFE_SUCCESS'))
        except psycopg2.Error as e:out.append(dict(sqlstate=e.pgcode,elapsed_ms=(time.perf_counter()-tick)*1000))
    t=threading.Thread(target=stale_activation);t.start();locks=wait_for_advisory(db,a.info.backend_pid)
    with b.cursor() as cur:cur.execute('SELECT pg_sleep(.15),clock_timestamp()');release=cur.fetchone()[1]
    b.commit();b.close();t.join(10)
    try:
        assert not t.is_alive() and out[0].get('sqlstate')=='40001' and out[0]['elapsed_ms']>=100 and state(db)==(3,1,1)
        SCENARIO_EVIDENCE.append(dict(scenario='measured_wait_stale_activation',isolation=isolation,role='retirement171_executor',before=before,blocked_locks=locks,release_db_time=release,result=out[0],automatic_retry=False))
    finally:a.rollback();a.close()


@pytest.mark.parametrize('table',['synthetic171_no_fk_dependency','nflx_no_fk_dependency'])
def test_executor_unknown_semantic_column_without_fk_refuses(db,table):
    pair=category_pair(db,'identity_only');activation,preview=prepared(db,pair);restricted_roles(db)
    query(db,'CREATE TABLE '+table+'(game_id integer); INSERT INTO '+table+' VALUES(584)')
    before=state(db)
    with pytest.raises(psycopg2.Error):role_query(db,'retirement171_executor','SELECT mlb_retirement_activate(%s::jsonb)',(json.dumps(activation),))
    assert state(db)==before
