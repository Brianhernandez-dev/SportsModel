"""Populated typed target/deadline controls on a positively isolated fixture.

Two synthetic future physical rows and one source mapping commit once as explicit
test controls. No run/prediction/provider action occurs; no fixtures are deleted.
"""
from datetime import datetime,time,timedelta,timezone
from zoneinfo import ZoneInfo
import pytest
from sportsmodel.database.mlb_canonical_time_repository import CertifiedReader,KnowledgeReceipt
from sportsmodel.database.scheduled_execution_repository import (
    GET_EARLIEST_MLB_GAME_START_QUERY,get_earliest_mlb_game_start_for_pacific_date,
)
from tests.database.test_mlb_canonical_time_postgres import (
    ENABLED,TARGETS,DATABASE,prepared_case,committed_proof,
)

pytestmark=pytest.mark.skipif(ENABLED not in TARGETS,reason='requires centrally isolated committed arbitration210 PG16')

@pytest.fixture(scope='module')
def target_controls(prepared_case,committed_proof):
    receipt,cutoff=committed_proof
    target_date=cutoff.astimezone(ZoneInfo('America/Los_Angeles')).date()+timedelta(days=1)
    early=datetime.combine(target_date,time(12),ZoneInfo('America/Los_Angeles')).astimezone(timezone.utc)
    mapped=early+timedelta(minutes=10)
    state_before=prepared_case.rows('SELECT mlb036_private.state()')
    with prepared_case.session() as c:
        c.rollback();c.set_session(readonly=False,isolation_level='READ COMMITTED')
        with c.cursor() as cur:
            cur.execute('SELECT count(*) FROM public.games WHERE game_id IN(953440,953441)')
            assert cur.fetchone()==(0,),'Never reseed/reset target controls'
            cur.execute('INSERT INTO public.games(game_id,game_date,home_team_id,away_team_id) '
                'SELECT v.id,v.start,g.home_team_id,g.away_team_id FROM public.games g CROSS JOIN '
                '(VALUES(953440,%s::timestamptz),(953441,%s::timestamptz)) v(id,start) WHERE g.game_id=26',(early,mapped))
            assert cur.rowcount==2
            cur.execute("INSERT INTO public.game_sources(game_source_id,game_id,source_name,external_game_id) "
                "VALUES(953442,953441,'mlb_stats','99953441')")
            cur.execute('SET CONSTRAINTS ALL IMMEDIATE')
        c.commit()
    assert prepared_case.rows('SELECT mlb036_private.state()')==state_before
    typed=KnowledgeReceipt(receipt['receipt_id'],receipt['receipt_body_sha256'],
        datetime.fromisoformat(receipt['available_at']),receipt['schema_capability_profile'],
        ('127.0.0.1',prepared_case.port,DATABASE))
    # Independent connection to the exact test fixture; API itself establishes RO RC.
    import psycopg2
    def factory():
        return psycopg2.connect(host='127.0.0.1',port=prepared_case.port,dbname=DATABASE,
            user=prepared_case.roles['reader'],password=prepared_case._password,connect_timeout=5)
    r=CertifiedReader(factory,typed,cutoff)
    return dict(reader=r,target_date=target_date,early=early,mapped=mapped)


def test_T44_earliest_deadline_requires_same_mlb_source_as_retained_contract(prepared_case,target_controls):
    control=target_controls
    start=datetime.combine(control['target_date'],time.min,ZoneInfo('America/Los_Angeles')).astimezone(timezone.utc)
    end=start+timedelta(days=1)
    legacy=prepared_case.rows(GET_EARLIEST_MLB_GAME_START_QUERY,('mlb_stats',start,end))[0][0]
    assert legacy==control['mapped']
    observed=get_earliest_mlb_game_start_for_pacific_date(control['target_date'],connection_factory=control['reader'])
    assert observed==legacy, 'Certified deadline must not promote an unmapped physical/provider row to canonical MLB evidence'


def test_T44_earliest_unmapped_only_window_is_empty(target_controls):
    control=target_controls
    rows=control['reader'].rows('earliest_start',start=control['early'].isoformat(),end=control['mapped'].isoformat())
    assert rows==(), 'A physical row without the existing required MLB source cannot set the canonical deadline'


def test_T44_other_target_purposes_keep_existing_physical_row_and_half_open_semantics(target_controls):
    control=target_controls;r=control['reader']
    assert r.game(953440).game_start_time==control['early']
    assert r.next_game().game_id==953440
    rows=r.rows('slate',start=control['early'].isoformat(),end=control['mapped'].isoformat())
    assert [row['game_id'] for row in rows]==[953440]
