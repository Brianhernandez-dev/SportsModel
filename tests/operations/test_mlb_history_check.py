"""Independent starter audit unit contracts; SQL semantics verified on disposable PG."""
from datetime import date, datetime, timedelta, timezone
import pytest
from sportsmodel.operations import mlb_history_check as history

CUTOFF = datetime(2026, 10, 9, tzinfo=timezone.utc)


class Cursor:
    def __init__(self, rows=(), malformed=False):
        self.rows=list(rows); self.malformed=malformed; self.sql=[]
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def execute(self, sql, params=None):
        self.sql.append((sql,params))
        if 'LIMIT 1' in sql: self.result=[(1,)] if self.malformed else []
        elif 'ranked_starts' in sql: self.result=self.rows
        elif 'transaction_timestamp' in sql: self.result=[(CUTOFF,)]
        elif 'FROM games g WHERE' in sql: self.result=[(99,CUTOFF+timedelta(days=1,hours=19),1,2)]
        elif 'FROM baseball_players' in sql: self.result=[(10,'100'),(20,'200')]
        elif 'WITH ranked AS' in sql: self.result=self.team_rows
        elif 'FROM game_sources' in sql: self.result=self.sources
        else: raise AssertionError('Unexpected SQL')
    def fetchall(self): return self.result
    def fetchone(self): return self.result[0]


def row(game=7, team=3, rank=1):
    return (10,game,CUTOFF-timedelta(days=rank),team,3,4,CUTOFF-timedelta(hours=1),rank)


def test_starter_query_mirrors_feature_pit_and_has_no_mapping_filter(monkeypatch):
    cur=Cursor([row()]); loaded=[]
    monkeypatch.setattr(history,'load_mlb_teams',lambda c,ids:loaded.append(set(ids)))
    assert history._load_retained_starter_history(cur,(10,20),CUTOFF)==[row()]
    sql,params=cur.sql[-1]
    for clause in ('pitching.is_starter=TRUE','g.game_date < %s','pitching.created_at <= %s','g.home_team_id=pitching.team_id','ORDER BY g.game_date DESC,g.game_id DESC'):
        assert clause in sql
    assert 'game_sources' not in sql and 'source_name' not in sql
    assert params==([10,20],CUTOFF,CUTOFF,50) and loaded==[{3,4}]


@pytest.mark.parametrize('change', ['duplicate','team','opponent','created','date','rank','player'])
def test_malformed_selected_starter_rows_refused(change,monkeypatch):
    r=list(row()); rows=[]
    if change=='duplicate': rows=[tuple(r),tuple(r)]
    elif change=='team': r[3]=8
    elif change=='opponent': r[5]=3
    elif change=='created': r[6]=CUTOFF+timedelta(seconds=1)
    elif change=='date': r[2]=CUTOFF
    elif change=='rank': r[7]=51
    else: r[0]=30
    monkeypatch.setattr(history,'load_mlb_teams',lambda *a:None)
    with pytest.raises(history.OperatorRefusal): history._load_retained_starter_history(Cursor(rows or [tuple(r)]),(10,20),CUTOFF)


def test_invalid_eligible_orientation_refused_before_selection():
    cur=Cursor(malformed=True)
    with pytest.raises(history.OperatorRefusal): history._load_retained_starter_history(cur,(10,20),CUTOFF)
    assert len(cur.sql)==1


def test_non_mlb_starter_participants_refused(monkeypatch):
    def refuse(*a): raise history.OperatorRefusal('Not canonical MLB')
    monkeypatch.setattr(history,'load_mlb_teams',refuse)
    with pytest.raises(history.OperatorRefusal): history._load_retained_starter_history(Cursor([row()]),(10,20),CUTOFF)


def test_limit_drift_refused_before_sql(monkeypatch):
    monkeypatch.setattr(history.completeness,'FEATURE_START_LIMIT',49);cur=Cursor()
    with pytest.raises(history.OperatorRefusal): history._load_retained_starter_history(cur,(10,20),CUTOFF)
    assert not cur.sql


@pytest.mark.parametrize('state',['team_invisible','same_team_invisible','former_team_invisible','ambiguous_identity','mapped_incomplete','complete','excluded'])
def test_full_history_reports_independent_windows_and_always_rolls_back(state,monkeypatch):
    cur=Cursor();cur.team_rows=[];cur.sources=[(99,'999')]
    if state=='team_invisible': cur.team_rows=[(1,7,CUTOFF-timedelta(days=1),1,2,1)]
    elif state!='excluded':
        r=list(row())
        if state=='same_team_invisible':r[3:6]=[1,1,2];cur.team_rows=[(1,7,r[2],1,2,1)]
        cur.rows=[tuple(r)]
    if state in ('mapped_incomplete','complete'):cur.sources.append((7,'700'))
    if state=='ambiguous_identity':cur.sources.extend([(7,'700'),(7,'701')])
    class Connection:
        def __init__(self): self.calls=[]
        def cursor(self): return cur
        def set_session(self,**kw): self.calls.append(kw)
        def rollback(self): self.calls.append('rollback')
        def close(self): self.calls.append('close')
    conn=Connection(); c=history.completeness
    monkeypatch.setattr(history,'verify_target',lambda *a,**k:{})
    monkeypatch.setattr(history,'load_mlb_teams',lambda *a:[])
    monkeypatch.setattr(c,'_load_required_feature_game_pks',lambda **k:())
    selected=[]
    monkeypatch.setattr(c,'_load_completeness_snapshots',lambda pks,**k:selected.extend(pks) or ())
    monkeypatch.setattr(c,'validate_mlb_game_completeness',lambda *a,**k:['incomplete'] if state=='mapped_incomplete' else ())
    monkeypatch.setattr(c,'assert_mlb_feature_history_complete',lambda **k:None)
    out=history.check_feature_history(target_date=date(2026,10,10),target_game_ids=(99,),starting_pitcher_ids=(10,20),cutoff_time=CUTOFF,target=None,connection_factory=lambda:conn)
    assert out['status']==('PASS' if state in ('complete','excluded') else 'FAIL')
    assert conn.calls==[dict(readonly=True,isolation_level='REPEATABLE READ'),'rollback','close']
    assert all(sql.lstrip().startswith(('SELECT','WITH')) for sql,_ in cur.sql)
    if 'invisible' in state: assert out['games_missing_mlb_stats_identity']==[7]
    if state=='former_team_invisible':
        assert out['starter_history_games_missing_mlb_stats_identity']==[7]
        assert out['team_history_games_missing_mlb_stats_identity']==[]
    if state in ('mapped_incomplete','complete'):assert selected==[700]
    if state=='ambiguous_identity':assert out['starter_history_games_missing_mlb_stats_identity']==[7]


def test_fifty_row_starter_window_preserves_ranks_before_identity_dedup(monkeypatch):
    rows=[row(game=100-rank,rank=rank) for rank in range(1,51)]
    cur=Cursor(rows)
    monkeypatch.setattr(history,'load_mlb_teams',lambda *a:None)
    assert history._load_retained_starter_history(cur,(10,20),CUTOFF)==rows
    assert cur.sql[-1][1][-1]==50 and 'WHERE rank <= %s' in cur.sql[-1][0]


def test_empty_starter_window_does_not_require_history_domain_or_mapping(monkeypatch):
    def forbidden(*a): raise AssertionError('No history participants')
    monkeypatch.setattr(history,'load_mlb_teams',forbidden)
    cur=Cursor()
    assert history._load_retained_starter_history(cur,(10,20),CUTOFF)==[]
    assert all('game_sources' not in sql for sql,_ in cur.sql)


@pytest.mark.parametrize('game_ids,starter_ids', [
    ((99,), (10,10)),
    ((99,100), (10,20,10,40)),
    ((99,100), (10,10,30,40)),
    ((99,100), (10,20,30,30)),
])
def test_duplicate_supplied_starters_refused_before_connection_or_history(game_ids,starter_ids,monkeypatch):
    called=[]
    def forbidden(*a,**k):
        called.append(True)
        raise AssertionError('Duplicate input reached database/history certification')
    monkeypatch.setattr(history,'_load_retained_starter_history',forbidden)
    monkeypatch.setattr(history.completeness,'_load_required_feature_game_pks',forbidden)
    monkeypatch.setattr(history.completeness,'_load_completeness_snapshots',forbidden)
    monkeypatch.setattr(history.completeness,'assert_mlb_feature_history_complete',forbidden)
    with pytest.raises(history.OperatorRefusal,match='starter IDs must be unique'):
        history.check_feature_history(target_date=date(2026,10,10),target_game_ids=game_ids,
            starting_pitcher_ids=starter_ids,cutoff_time=CUTOFF,target=None,connection_factory=forbidden)
    assert called==[]


@pytest.mark.parametrize('game_ids,starter_ids', [((99,), (10,20)),((99,100), (10,20,30,40))])
def test_distinct_supplied_starters_proceed_without_deduplication(game_ids,starter_ids,monkeypatch):
    class SlateCursor(Cursor):
        def execute(self,sql,params=None):
            super().execute(sql,params)
            if 'FROM games g WHERE' in sql:
                self.result=[(gid,CUTOFF+timedelta(days=1,hours=19),1,2) for gid in game_ids]
            elif 'FROM baseball_players' in sql:
                self.result=[(pid,str(1000+pid)) for pid in starter_ids]
    cur=SlateCursor();cur.team_rows=[];cur.sources=[(gid,str(1000+gid)) for gid in game_ids]
    class Connection:
        def cursor(self): return cur
        def set_session(self,**kw): assert kw==dict(readonly=True,isolation_level='REPEATABLE READ')
        def rollback(self): pass
        def close(self): pass
    monkeypatch.setattr(history,'verify_target',lambda *a,**k:{})
    monkeypatch.setattr(history,'load_mlb_teams',lambda *a:[])
    c=history.completeness; observed=[]
    def required(**kw): observed.append(kw['starting_pitcher_ids']);return ()
    monkeypatch.setattr(c,'_load_required_feature_game_pks',required)
    monkeypatch.setattr(c,'_load_completeness_snapshots',lambda *a,**k:())
    monkeypatch.setattr(c,'validate_mlb_game_completeness',lambda *a,**k:())
    monkeypatch.setattr(c,'assert_mlb_feature_history_complete',lambda **kw:observed.append(kw['starting_pitcher_ids']))
    out=history.check_feature_history(target_date=date(2026,10,10),target_game_ids=game_ids,
        starting_pitcher_ids=starter_ids,cutoff_time=CUTOFF,target=None,connection_factory=Connection)
    assert out['status']=='PASS' and out['starting_pitcher_ids']==list(starter_ids)
    assert observed==[starter_ids,starter_ids] and cur.sql
