"""Actual read-only history CLI chain on an explicitly new isolated PG16 target."""
from datetime import datetime,timedelta,timezone
from pathlib import Path
from zoneinfo import ZoneInfo
import importlib.util,json,os,re,subprocess,time
import psycopg2,pytest

ROOT=Path(__file__).resolve().parents[2]
NAME='sportsmodel-identity-112-20261011-a'
DATABASE='sportsmodel_test_112a20261011'
PORT=55448
SCENARIO_EVIDENCE=[]
pytestmark=pytest.mark.skipif(os.getenv('SPORTSMODEL_HISTORY_DISPOSABLE_CONTAINER')!=NAME,
    reason='requires explicitly verified fresh history-112 isolated PG16')


@pytest.fixture
def db():
    # Reuse the unchanged reviewed synthetic seed/migration fixture, with a new
    # target namespace, port and owned volume. Its exact topology checks still run.
    spec=importlib.util.spec_from_file_location('reviewed_identity_fixture',ROOT/'tests/database/test_mlb_identity_disposition_postgres.py')
    fixture=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture)
    fixture.NAME=NAME;fixture.DATABASE=DATABASE;fixture.PORT=PORT
    factory=fixture.db.__wrapped__()
    return factory,fixture


def state(factory):
    connection=factory()
    try:
        connection.set_session(readonly=True)
        with connection.cursor() as cursor:
            cursor.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")
            tables=[row[0] for row in cursor.fetchall()]
            values={}
            for table in tables:
                assert table.replace('_','').isalnum()
                cursor.execute('SELECT to_jsonb(t)::text FROM public.'+table+' t ORDER BY to_jsonb(t)::text')
                values[table]=cursor.fetchall()
            return values
    finally:connection.rollback();connection.close()


@pytest.mark.parametrize('mode',['prospective','no_wait','too_far','historical6','historical7','historical8','changed','missing','malformed','empty','incomplete','interrupted'])
def test_documented_history_cli_committed_knowledge_chain(db,tmp_path,monkeypatch,capsys,mode):
    from sportsmodel.operations import mlb_operator_cli as cli,mlb_history_check as history
    from sportsmodel.database import mlb_identity_disposition_repository as identity
    from sportsmodel.database.mlb_operator_guard import canonical_json
    factory,fixture=db
    pair=fixture.seed(factory)
    case=event=None
    if mode!='empty':case,event,_=fixture.activate_sql(factory,pair)
    # A future slate with no retained historical rows isolates admission from
    # completeness failure. These synthetic canonical clubs/starter sources do
    # not overlap the retired pair. No model, predictions or providers are used.
    h,a=[r[0] for r in fixture.query(factory,"INSERT INTO teams(team_name) VALUES('Chicago Cubs'),('Boston Red Sox') RETURNING team_id")]
    fixture.query(factory,"INSERT INTO baseball_team_sources(team_id,source_name,external_team_id) VALUES(%s,'mlb_stats','112'),(%s,'mlb_stats','111')",(h,a))
    if mode=='incomplete':h,a=pair[2:]
    day=(datetime.now(timezone.utc).astimezone(ZoneInfo('America/Los_Angeles'))+timedelta(days=1)).date()
    when=datetime(day.year,day.month,day.day,17,tzinfo=ZoneInfo('America/Los_Angeles'))
    game=fixture.query(factory,'INSERT INTO games(game_date,home_team_id,away_team_id) VALUES(%s,%s,%s) RETURNING game_id',(when,h,a))[0][0]
    fixture.query(factory,"INSERT INTO game_sources(game_id,source_name,external_game_id) VALUES(%s,'mlb_stats','900003')",(game,))
    players=[r[0] for r in fixture.query(factory,"INSERT INTO baseball_players(full_name) VALUES('Synthetic CLI Starter One'),('Synthetic CLI Starter Two') RETURNING baseball_player_id")]
    fixture.query(factory,"INSERT INTO baseball_player_sources(baseball_player_id,source_name,external_player_id) VALUES(%s,'mlb_stats','100'),(%s,'mlb_stats','200')",tuple(players))
    _,_,target=fixture.evidence_request(factory,pair)
    target_path=tmp_path/'target.json';target_path.write_text(canonical_json(target.artifact()))
    output=tmp_path/'history.json'
    cutoff=(datetime(2026,10,int(mode[-1]) if mode.startswith('historical') else 6,tzinfo=timezone.utc) if mode.startswith('historical') or mode=='empty'
            else datetime.now(timezone.utc)+timedelta(seconds=60 if mode=='too_far' else 3 if mode=='no_wait' else 1))
    wait_mode=mode not in ('no_wait','empty')
    connections=[];sql=[];captures=[];order=[]
    class Cursor:
        def __init__(self,inner,number):self.inner=inner;self.number=number
        def __enter__(self):return self
        def __exit__(self,*args):self.inner.close()
        def __getattr__(self,name):return getattr(self.inner,name)
        def execute(self,query,params=None):
            assert query.lstrip().startswith(('SELECT','WITH')),query
            assert not re.search(r'\b(INSERT|UPDATE|DELETE|TRUNCATE|ALTER|DROP|CREATE)\b',query,re.I),query
            assert self.number!=1 or not wait_mode or self.inner.connection.autocommit
            sql.append(dict(connection=self.number,query=query))
            return self.inner.execute(query,params)
    class Connection:
        def __init__(self,inner):self.inner=inner;self.number=len(connections);self.settings=[];self.closed=False;connections.append(self)
        def __getattr__(self,name):return getattr(self.inner,name)
        def cursor(self):return Cursor(self.inner.cursor(),self.number)
        def set_session(self,**kwargs):
            assert kwargs.get('readonly') is True
            self.settings.append(kwargs);return self.inner.set_session(**kwargs)
        def commit(self):pytest.fail('Read-only H-1 committed a transaction')
        def close(self):self.closed=True;self.inner.close()
    def connector(**kwargs):
        assert (kwargs['host'],kwargs['port'],kwargs['dbname'])==('127.0.0.1',PORT,DATABASE)
        assert 'default_transaction_read_only=on' in kwargs['options']
        # No test-connector sleep: timing admission must use the CLI's actual
        # trusted DB-clock wait implementation.
        return Connection(psycopg2.connect(**kwargs))
    real_capture=identity.capture_identity_knowledge
    real_check=history.check_feature_history
    after_injected=[]
    def capture(*,connection_factory):
        order.append('capture');value=real_capture(connection_factory=connection_factory)
        assert connections[0].closed
        captures.append(value)
        return None if mode=='missing' else object() if mode=='malformed' else value
    def check(**kwargs):
        order.append('check')
        if mode not in ('missing','malformed'):assert kwargs['identity_knowledge'] is captures[0]
        assert kwargs['cutoff_time']==cutoff and kwargs['target']==target
        return real_check(**kwargs)
    monkeypatch.setattr(identity,'capture_identity_knowledge',capture)
    monkeypatch.setattr(history,'check_feature_history',check)
    original_sleep=time.sleep
    def waiting(seconds):
        assert len(connections)==2 and connections[0].closed and not connections[1].closed
        assert connections[1].inner.autocommit and connections[1].inner.get_transaction_status()==0
        if mode=='changed' and not after_injected:
            fixture.activate_sql(factory,pair,case=case,previous=event,sequence=2,action='REVOKE',evidence='b'*64)
            after_injected.append(state(factory))
        if mode=='interrupted':raise KeyboardInterrupt
        original_sleep(seconds)
    monkeypatch.setattr(cli.time,'sleep',waiting)
    before=state(factory)
    result=cli.main(['history','--target',str(target_path),'--db-user','postgres','--output',str(output),
        '--acknowledge-db-read','--date',day.isoformat(),'--game-ids',str(game),'--starter-ids',*[str(p) for p in players],
        '--cutoff',cutoff.isoformat(),*(['--wait-for-cutoff'] if wait_mode else [])],connector=connector,password_reader=lambda _:next(
            value.split('=',1)[1] for value in json.loads(subprocess.run(['docker','inspect',NAME],capture_output=True,check=True).stdout)[0]['Config']['Env']
            if value.startswith('POSTGRES_PASSWORD=')))
    reached_check=mode in ('prospective','no_wait','empty','incomplete','changed')
    assert order==(['capture','check'] if reached_check else ['capture'])
    expected_connections=3 if mode in ('prospective','incomplete','changed') else 2 if mode in ('no_wait','empty','too_far','interrupted') else 1
    assert len(connections)==expected_connections and all(c.closed for c in connections)
    for connection in connections:
        expected=dict(readonly=True,isolation_level='REPEATABLE READ')
        if wait_mode and connection.number==1:expected['autocommit']=True
        assert connection.settings==[expected]
    assert state(factory)==(after_injected[0] if after_injected else before)
    diagnostic=json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    if mode in ('prospective','empty','incomplete'):
        report=json.loads(output.read_text())
        assert result==(1 if mode=='incomplete' else 0) and report['status']==('FAIL' if mode=='incomplete' else 'PASS')
        assert report['cutoff_time']==cutoff.isoformat()
        if wait_mode:
            assert report['cutoff_wait']['requested_cutoff_argument']==cutoff.isoformat()
            assert datetime.fromisoformat(report['cutoff_wait']['db_time_reached'])>=cutoff
            assert report['cutoff_wait']['maximum_seconds']==30
        if mode=='incomplete':assert pair[1] in report['required_canonical_game_ids'] and report['issues']
    else:
        assert result==(130 if mode=='interrupted' else 1) and not output.exists()
        if mode=='changed':assert diagnostic['error_type']=='RaiseException'
        elif mode=='no_wait':
            assert diagnostic['error_type']=='RaiseException'
            assert datetime.fromisoformat(captures[0].available_at)<=cutoff
            assert fixture.query(factory,'SELECT clock_timestamp()')[0][0]<cutoff
        elif mode=='too_far':assert 'bounded wait' in diagnostic['reason']
        elif mode=='interrupted':assert 'interrupted' in diagnostic['reason']
        else:assert 'capture' in diagnostic['reason']
    if mode=='prospective':assert datetime.fromisoformat(captures[0].available_at)<=cutoff
    if mode.startswith('historical'):assert datetime.fromisoformat(captures[0].available_at)>cutoff
    SCENARIO_EVIDENCE.append(dict(scenario=mode,exit_code=result,cutoff=cutoff.isoformat(),
        committed_capture=captures[0].body(),artifact_sha256=captures[0].artifact_sha256,
        order=order,connections=[dict(number=c.number,settings=c.settings,closed=c.closed) for c in connections],
        SQL=sql,operator_zero_writes=True,no_test_connector_sleep=True,wait_flag=wait_mode,
        fixture_revoke_only=mode=='changed',diagnostic=diagnostic,
        report=json.loads(output.read_text()) if output.exists() else None))
