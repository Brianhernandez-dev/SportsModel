import copy
from datetime import date, datetime, timezone
from hashlib import sha256
from types import SimpleNamespace

import pytest

from sportsmodel.database import mlb_retirement_guard as guard
from sportsmodel.operations import mlb_reconcile as reconcile
from sportsmodel.operations import mlb_operator_cli as cli


STAMP = datetime(2026, 10, 1, tzinfo=timezone.utc)


def synthetic_knowledge():
    # Unit plumbing only. Real sealed capture is tested against isolated PG16.
    from sportsmodel.database import mlb_retirement_repository as identity
    body=dict(version=2,profile='a'*64,fingerprint='b'*64,ledger034='c'*64,
              ledger035='d'*64,topology_epoch=1,available_at=STAMP.isoformat(),
              endpoint=['127.0.0.1',55448,'sportsmodel_test_retirement170_35'])
    return identity.IdentityKnowledgeSnapshot(**{k:tuple(v) if k=='endpoint' else v for k,v in body.items() if k!='version'},
        artifact_sha256=identity._knowledge_hash(body),capture_attestation=identity._COMMITTED_CAPTURE)


@pytest.fixture(autouse=True)
def valid_offline_catalog(monkeypatch):
    from sportsmodel.database import mlb_retirement_repository as identity
    monkeypatch.setattr(identity,'verify_capabilities',lambda cursor:True)
    monkeypatch.setattr(guard,'verify_capabilities',lambda cursor:True)


def target(**changes):
    values = dict(host="127.0.0.1", port=5432, database="sportsmodel",
                  server_address="127.0.0.1", server_port=5432,
                  postmaster_started_at=STAMP.isoformat(), identity_kind="native")
    values.update(changes)
    return guard.OperatorTarget(**values)


def proof(pid):
    return dict(service_name="SportsModelPostgreSQL16", state="Running", service_pid=10,
                backend_pid=pid, postmaster_pid=20, postmaster_parent=10,
                service_path=r'D:\PostgreSQL\16\server\bin\pg_ctl.exe runservice -N SportsModelPostgreSQL16 -D D:\PostgreSQL\16\data',
                listeners=[dict(LocalAddress="127.0.0.1", LocalPort=5432, OwningProcess=20)])


class Cursor:
    def __init__(self, connection): self.connection = connection
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def execute(self, sql, params=None):
        self.connection.sql.append(sql)
        if "current_database()" in sql:
            self.rows = self.connection.identity
        elif "schema_migrations" in sql:
            self.rows = self.connection.migrations
        else:
            raise AssertionError("Unplanned unit query")
    def fetchall(self): return self.rows


class Connection:
    def __init__(self):
        self.info = SimpleNamespace(host="127.0.0.1", port=5432, dbname="sportsmodel")
        self.identity = [("sportsmodel", "127.0.0.1", 5432, STAMP, 30, "160015", "on", "repeatable read")]
        self.migrations = list(guard.migration_reference())
        self.sql = []
    def cursor(self): return Cursor(self)


@pytest.mark.parametrize("changes", [
        {"domain": "NFL"}, {"migration_boundary": 33}, {"migration_boundary": 34}, {"host": "localhost"},
    {"database": "other"}, {"port": 55499}, {"server_port": 55499},
    {"postmaster_started_at": "2026-10-01"}, {"identity_kind": "unknown"},
    {"port": True}, {"database": ""}, {"server_address": "alias"},
])
def test_target_contract_refuses_wrong_or_ambiguous_fields(changes):
    with pytest.raises(guard.OperatorRefusal): target(**changes)


@pytest.mark.parametrize("index,value", [(0,"wrong"),(1,"::1"),(2,55499),(3,datetime(2026,10,2,tzinfo=timezone.utc)),(5,"170001"),(6,"off"),(7,"read committed")])
def test_observed_target_mismatch_fails_closed(index, value):
    c=Connection(); row=list(c.identity[0]);row[index]=value;c.identity=[tuple(row)]
    with pytest.raises(guard.OperatorRefusal): guard.verify_target(c,target(),readonly=True,process_probe=proof)


def test_guard_never_reads_privileged_setting_for_native_role():
    c=Connection()
    result=guard.verify_target(c,target(),readonly=True,process_probe=proof)
    assert result["target"]["database"]=="sportsmodel"
    assert all("data_directory" not in sql and "pg_control_system" not in sql for sql in c.sql)


def test_guard_refuses_wrong_client_port_before_sql():
    c=Connection();c.info.port=55499
    with pytest.raises(guard.OperatorRefusal):guard.verify_target(c,target(),readonly=True,process_probe=proof)
    assert c.sql==[]


@pytest.mark.parametrize("mode", ["missing", "extra", "checksum"])
def test_exact_migration_inventory_not_max_version(mode):
    c=Connection()
    if mode=="missing":c.migrations=c.migrations[1:]
    elif mode=="extra":c.migrations.append((34,"034_extra.sql","a"*64))
    else:c.migrations[0]=(1,c.migrations[0][1],"a"*64)
    with pytest.raises(guard.OperatorRefusal):guard.verify_target(c,target(),readonly=True,process_probe=proof)


@pytest.mark.parametrize("field,value", [("listeners",[]),("listeners",[{},{}]),("state","Stopped"),("postmaster_parent",99),("backend_pid",99)])
def test_ambiguous_native_process_proof_refused(field,value):
    p=proof(30);p[field]=value
    with pytest.raises(guard.OperatorRefusal):guard.validate_native_proof(p,30)


def test_native_storage_prefix_is_not_exact_identity():
    p=proof(30);p['service_path']+= '-different'
    with pytest.raises(guard.OperatorRefusal):guard.validate_native_proof(p,30)


@pytest.mark.parametrize('rows', [[(1,'Cleveland Browns','114',1)],[(1,'Cleveland Guardians','9999',1)],[(1,'Cleveland Guardians','114',1),(1,'Cleveland Guardians','114',2)]])
def test_mlb_team_domain_requires_exact_franchise_and_unique_source(rows):
    cur=SimpleNamespace(execute=lambda *a:None,fetchall=lambda:rows)
    with pytest.raises(guard.OperatorRefusal):guard.load_mlb_teams(cur,(1,))


def inputs():
    game=dict(gamePk=800,gameType="D",ifNecessary="N",gameDate="2026-10-07T19:00:00Z",
              status=dict(abstractGameState="Preview",detailedState="Scheduled",startTimeTBD=False),
              teams=dict(home=dict(team=dict(id=145,name="Chicago White Sox")),away=dict(team=dict(id=114,name="Cleveland Guardians"))))
    payload=dict(dates=[dict(date="2026-10-07",games=[game])])
    raw=guard.canonical_json(payload).encode()
    before=[dict(source_name="odds_api",external_game_id="SYNTHETIC_EVENT")]
    allow=dict(version=1,domain="MLB",target_date="2026-10-07",payload_sha256=sha256(raw).hexdigest(),
               games=[dict(game_pk=800,home_team="Chicago White Sox",away_team="Cleveland Guardians",
                    expected_start="2026-10-07T19:00:00Z",existing_game_id=7,current_sources=before,
                    resulting_sources=before+[dict(source_name="mlb_stats",external_game_id="800")])])
    return payload,allow


def validate(payload,allow):
    raw=guard.canonical_json(payload).encode()
    allow=copy.deepcopy(allow);allow["payload_sha256"]=sha256(raw).hexdigest()
    return reconcile.validate_inputs(raw,guard.canonical_json(allow).encode())


def test_valid_exact_allowlist():
    p,a=inputs();day,rows=validate(p,a)
    assert day==date(2026,10,7) and rows[0]["home_mlb_id"]==145


@pytest.mark.parametrize("case", ["extra","missing","wrong_pk","reversed","placeholder","tbd","conditional","wrong_date","bad_type","duplicate","start","source_delete","extra_field","bool_pk","duplicate_target"])
def test_pinned_inputs_refuse_bad_evidence(case):
    p,a=inputs();g=p["dates"][0]["games"][0]
    if case=="extra":p["dates"][0]["games"].append(dict(g,gamePk=801))
    elif case=="missing":p["dates"][0]["games"]=[]
    elif case=="wrong_pk":g["gamePk"]=801
    elif case=="reversed":g["teams"]["home"],g["teams"]["away"]=g["teams"]["away"],g["teams"]["home"]
    elif case=="placeholder":g["teams"]["home"]["team"]=dict(id=5521,name="AL Seed")
    elif case=="tbd":g["status"]["startTimeTBD"]=True
    elif case=="conditional":g["ifNecessary"]="Y"
    elif case=="wrong_date":p["dates"][0]["date"]="2026-10-08"
    elif case=="bad_type":g["gameType"]="P"
    elif case=="duplicate":p["dates"][0]["games"].append(g)
    elif case=="start":g["gameDate"]="2026-10-07T19:01:00Z"
    elif case=="source_delete":a["games"][0]["resulting_sources"]=[dict(source_name="mlb_stats",external_game_id="800")]
    elif case=="extra_field":a["wildcard"]=True
    elif case=="bool_pk":g["gamePk"]=True
    else:a["games"].append(dict(a["games"][0],game_pk=801))
    with pytest.raises((guard.OperatorRefusal,ValueError)):validate(p,a)


def test_payload_exact_byte_hash_required():
    p,a=inputs()
    with pytest.raises(guard.OperatorRefusal):reconcile.validate_inputs(guard.canonical_json(p).encode()+b"\n",guard.canonical_json(a).encode())


def test_json_duplicate_or_nonfinite_fields_refused():
    for raw in ('{"domain":"MLB","domain":"NFL"}', '{"x":NaN}'):
        with pytest.raises(guard.OperatorRefusal):guard.strict_json(raw)


def test_execute_requires_authorization_before_connection():
    p,a=inputs();called=[]
    with pytest.raises(guard.OperatorRefusal):reconcile.execute_reconciliation(payload_bytes=guard.canonical_json(p).encode(),allowlist_bytes=guard.canonical_json(a).encode(),preview={},approved_preview_sha256="a"*64,target=target(),connection_factory=lambda:called.append(True))
    assert called==[]


def test_bad_preview_binding_refused_before_connection():
    p,a=inputs();called=[]
    with pytest.raises(guard.OperatorRefusal):reconcile.execute_reconciliation(payload_bytes=guard.canonical_json(p).encode(),allowlist_bytes=guard.canonical_json(a).encode(),preview={},approved_preview_sha256="a"*64,target=target(),connection_factory=lambda:called.append(True),acknowledge_writes=True)
    assert called==[]


def test_cli_history_fail_is_nonzero(tmp_path,monkeypatch):
    from sportsmodel.operations import mlb_history_check
    from sportsmodel.database import mlb_retirement_repository
    path=tmp_path/"target.json";path.write_text(guard.canonical_json(target().artifact()))
    monkeypatch.setattr(mlb_history_check,"check_feature_history",lambda **kw:{"status":"FAIL","issues":["synthetic missing identity"]})
    monkeypatch.setattr(mlb_retirement_repository,"capture_identity_knowledge",lambda **kw:object())
    code=cli.main(["history","--target",str(path),"--db-user","synthetic","--output",str(tmp_path/"out.json"),"--acknowledge-db-read","--date","2026-10-07","--game-ids","1","--starter-ids","1","2","--cutoff","2026-10-07T00:00:00Z"],connector=lambda **kw:None,password_reader=lambda _:"SYNTHETIC_DB_SENTINEL")
    assert code==1 and guard.strict_json((tmp_path/"out.json").read_bytes())["status"]=="FAIL"


def test_history_cli_passes_exact_capture_and_preserves_cutoff(tmp_path,monkeypatch):
    from sportsmodel.operations import mlb_history_check
    from sportsmodel.database import mlb_retirement_repository as identity
    path=tmp_path/'target.json';path.write_text(guard.canonical_json(target().artifact()))
    capture=synthetic_knowledge()
    calls=[];factory_seen=[]
    def captured(*,connection_factory):
        calls.append('capture');factory_seen.append(connection_factory);return capture
    def checked(**kwargs):
        calls.append('check')
        assert kwargs['identity_knowledge'] is capture
        assert kwargs['connection_factory'] is factory_seen[0]
        assert kwargs['target']==target() and kwargs['cutoff_time']==STAMP
        return {'status':'PASS'}
    monkeypatch.setattr(identity,'capture_identity_knowledge',captured)
    monkeypatch.setattr(mlb_history_check,'check_feature_history',checked)
    def connection(**kwargs):
        pytest.fail('Unit plumbing test unexpectedly connected')
    assert cli.main(['history','--target',str(path),'--db-user','synthetic','--output',str(tmp_path/'out.json'),
        '--acknowledge-db-read','--date','2026-10-07','--game-ids','1','--starter-ids','1','2',
        '--cutoff',STAMP.isoformat()],connector=connection,password_reader=lambda _:'SYNTHETIC_DB_SENTINEL')==0
    assert calls==['capture','check']


@pytest.mark.parametrize('case',['success','already_satisfied','too_far','historical','naive','malformed','bad_clock','expired','interrupted'])
def test_bounded_wait_uses_db_clock_and_closes_connection(monkeypatch,case):
    from datetime import timedelta
    knowledge=synthetic_knowledge()
    cutoff=STAMP+timedelta(seconds=1)
    if case=='too_far':cutoff=STAMP+timedelta(seconds=31)
    if case=='historical':cutoff=STAMP-timedelta(seconds=1)
    if case=='naive':cutoff=cutoff.replace(tzinfo=None)
    if case=='malformed':knowledge=None
    clocks=iter([cutoff] if case=='already_satisfied' else [STAMP,cutoff]);events=[]
    class WaitConnection:
        def set_session(self,**kw):
            assert kw==dict(readonly=True,isolation_level='REPEATABLE READ',autocommit=True)
        def cursor(self):return self
        def __enter__(self):events.append('cursor');return self
        def __exit__(self,*a):events.append('cursor_closed')
        def execute(self,sql):events.append(sql)
        def fetchone(self):return ((STAMP.replace(tzinfo=None) if case=='bad_clock' else next(clocks)),)
        def close(self):events.append('connection_closed')
    monkeypatch.setattr(guard,'verify_target',lambda connection,target,readonly:events.append('target_verified'))
    ticks=iter([0,31] if case=='expired' else [0]*20)
    monkeypatch.setattr(cli.time,'monotonic',lambda:next(ticks))
    def sleep(seconds):
        assert events[-1]=='cursor_closed' and 0<seconds<=cli.CUTOFF_POLL_SECONDS
        events.append('sleep')
        if case=='interrupted':raise KeyboardInterrupt
    monkeypatch.setattr(cli.time,'sleep',sleep)
    kwargs=dict(knowledge=knowledge,cutoff_time=cutoff,target=target(),connection_factory=WaitConnection)
    if case in ('success','already_satisfied'):
        result=cli._wait_for_history_cutoff(**kwargs)
        assert result['cutoff_time']==cutoff.isoformat() and result['polls']==(1 if case=='already_satisfied' else 2)
    else:
        with pytest.raises(KeyboardInterrupt if case=='interrupted' else guard.OperatorRefusal):cli._wait_for_history_cutoff(**kwargs)
    if case in ('historical','naive','malformed'):assert events==[]
    else:assert events[-1]=='connection_closed'
    if case in ('already_satisfied','too_far','expired','bad_clock'):assert 'sleep' not in events


@pytest.mark.parametrize('cutoff',['not-a-date','2026-10-11T12:00:00'])
def test_wait_cli_rejects_malformed_naive_cutoff_before_credentials(tmp_path,cutoff):
    called=[]
    with pytest.raises(SystemExit) as failure:
        cli.main(['history','--target',str(tmp_path/'unused.json'),'--db-user','synthetic','--output',str(tmp_path/'out.json'),
            '--acknowledge-db-read','--date','2026-10-11','--game-ids','1','--starter-ids','1','2',
            '--cutoff',cutoff,'--wait-for-cutoff'],connector=lambda **kw:called.append('connection'),password_reader=lambda _:called.append('password'))
    assert failure.value.code==2 and called==[] and not (tmp_path/'out.json').exists()


def test_cli_echo_fallback_fails_closed(tmp_path):
    import getpass,warnings
    path=tmp_path/"target.json";path.write_text(guard.canonical_json(target().artifact()))
    def fallback(_):warnings.warn("synthetic",getpass.GetPassWarning);return "SYNTHETIC"
    called=[]
    code=cli.main(["history","--target",str(path),"--db-user","synthetic","--output",str(tmp_path/"out.json"),"--acknowledge-db-read","--date","2026-10-07","--game-ids","1","--starter-ids","1","2","--cutoff","2026-10-07T00:00:00Z"],connector=lambda **kw:called.append(True),password_reader=fallback)
    assert code==1 and called==[] and not (tmp_path/"out.json").exists()


def test_exclusive_output(tmp_path):
    path=tmp_path/"out.json";path.write_text("retained")
    with pytest.raises(guard.OperatorRefusal):cli._write_output(path,{"status":"PASS"})
    assert path.read_text()=="retained"


def test_readonly_snapshot_close_does_not_close_owner():
    owner=SimpleNamespace(cursor=lambda:"cursor")
    proxy=guard.SnapshotConnection(owner);proxy.close()
    assert proxy.cursor()=="cursor"


@pytest.mark.parametrize('mode', [(False,False),('false',False)])
def test_matcher_disallows_unlinked_creation_in_readonly_mode(mode):
    from sportsmodel.ingest.game_matching import get_or_create_canonical_game
    called=[]
    cur=SimpleNamespace(execute=lambda *a:called.append(True))
    with pytest.raises(ValueError):get_or_create_canonical_game(cur,source_name='mlb_stats',external_game_id='800',game_datetime=STAMP,home_team_id=1,away_team_id=2,existing_only=mode[0],persist_mapping=mode[1])
    assert called==[]


def test_documented_synthetic_payload_and_allowlist_are_byte_bound():
    from pathlib import Path
    root=Path(__file__).resolve().parents[2]
    day,rows=reconcile.validate_inputs((root/'docs/operations/mlb_reconciliation_schedule.synthetic.json').read_bytes(),(root/'docs/operations/mlb_reconciliation_allowlist.synthetic.json').read_bytes())
    assert day==date(2026,10,7) and rows[0]['game_pk']==800


@pytest.mark.parametrize('field,value',[('version',1),('version',3),('domain','NFL')])
def test_approved_hash_does_not_admit_wrong_preview_envelope(field,value):
    p,a=inputs();raw=guard.canonical_json(p).encode();allowed=guard.canonical_json(a).encode()
    body=dict(version=2,domain='MLB',target_date='2026-10-07',target=target().artifact(),payload_sha256=sha256(raw).hexdigest(),allowlist_sha256=sha256(allowed).hexdigest(),guard={},implementation_fingerprint=reconcile.fingerprint(),plans=[])
    body[field]=value;body['preview_sha256']=guard.digest(body)
    called=[]
    with pytest.raises(guard.OperatorRefusal,match='version/domain'):reconcile.execute_reconciliation(payload_bytes=raw,allowlist_bytes=allowed,preview=body,approved_preview_sha256=body['preview_sha256'],target=target(),connection_factory=lambda:called.append(True),acknowledge_writes=True)
    assert called==[]
