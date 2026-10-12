"""Exact schema035 retirement and committed v2 knowledge. No ambient access."""
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from pathlib import Path
import json
import re

from sportsmodel.database import mlb_identity_disposition_repository as legacy034

IdentityDispositionError = legacy034.IdentityDispositionError
_COMMITTED = object()
MIGRATION = '035_create_mlb_legacy_identity_retirements.sql'
GUARDED_TABLES = tuple(t for t in legacy034.GUARDED_TABLES
                       if t not in ('sportsbooks', 'sportsbook_provider_identities'))
PRIVILEGED_FUNCTIONS = ('mlb_retirement_ledger_ingress', 'mlb_retirement_topology_integrity',
                       'mlb_retirement_case_insert', 'mlb_retirement_case_complete',
                       'mlb_retirement_event_insert','mlb_retirement_activate')
VIEW_DEFINITIONS = {
    "mlb_active_retired_identities": " SELECT '034'::text AS origin,\n    mlb_active_stale_identity_dispositions.disposition_id AS case_id,\n    mlb_active_stale_identity_dispositions.subject_game_id,\n    mlb_active_stale_identity_dispositions.survivor_game_id,\n    mlb_active_stale_identity_dispositions.disposition_type AS category,\n    mlb_active_stale_identity_dispositions.event_id,\n    mlb_active_stale_identity_dispositions.sequence,\n    mlb_active_stale_identity_dispositions.state_recorded_at\n   FROM mlb_active_stale_identity_dispositions\nUNION ALL\n SELECT '035'::text AS origin,\n    r.retirement_id AS case_id,\n    r.subject_game_id,\n    r.survivor_game_id,\n    r.category,\n    e.event_id,\n    e.sequence,\n    e.created_at AS state_recorded_at\n   FROM mlb_legacy_identity_retirements r\n     JOIN mlb_legacy_identity_retirement_events e USING (retirement_id);",
    "mlb_eligible_active_market_snapshots": " SELECT odds_market_snapshot_id,\n    game_id AS physical_game_id,\n    sportsbook_id,\n    market_type,\n    selection_name,\n    line_value,\n    price,\n    snapshot_time,\n    source_name,\n    created_at,\n    odds_ingestion_run_id,\n    odds_provider_event_observation_id,\n    sportsbook_provider_identity_id,\n    bookmaker_title_at_observation,\n    bookmaker_updated_at,\n    market_updated_at,\n    observed_at\n   FROM odds_market_snapshots m\n  WHERE NOT (EXISTS ( SELECT 1\n           FROM mlb_active_retired_identities r\n          WHERE r.subject_game_id = m.game_id));"
}


def migration_reference():
    root = Path(__file__).resolve().parents[3]
    paths = sorted((root/'database/migrations').glob('*.sql'))
    if [int(p.name[:3]) for p in paths] != list(range(1, 36)):
        raise IdentityDispositionError('Exact001-035 migration inventory required')
    return tuple((int(p.name[:3]),p.name,sha256(p.read_text(encoding='utf-8-sig').encode()).hexdigest()) for p in paths)


def profile_fingerprint():
    root=Path(__file__).resolve().parents[3]
    files = {str(p.relative_to(root)).replace('\\','/'):sha256(p.read_bytes()).hexdigest()
             for p in (root/'src/sportsmodel').rglob('*.py')
             if not any(part in ('nfl','models','modeling') for part in p.relative_to(root/'src/sportsmodel').parts)}
    files['migrations']=migration_reference()
    files['schema035_catalog']=sha256(Path(__file__).with_name('mlb_retirement_schema035.json').read_bytes()).hexdigest()
    return sha256(json.dumps(files,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def verify_capabilities(cursor):
    legacy034.verify_capabilities(cursor)
    path=Path(__file__).resolve().parents[3]/'database/migrations'/MIGRATION
    expected={name:(body.strip(),'s' if re.search(r'\bSTABLE\b',attrs) else 'v',
                    'SECURITY DEFINER' in attrs,['search_path=pg_catalog, public'])
              for name,attrs,body in re.findall(r'CREATE FUNCTION (mlb_[a-z_]+)\b(.*?)\bAS\s+\$\$(.*?)\$\$;',path.read_text(),re.S)}
    cursor.execute("""SELECT p.proname,p.prosrc,p.provolatile,p.prosecdef,p.proconfig
        FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
        WHERE n.nspname='public' AND p.proname=ANY(%s)""",(list(expected),))
    rows=cursor.fetchall()
    if len(rows)!=len(expected) or {r[0]:(r[1].strip(),*r[2:]) for r in rows}!=expected:
        raise IdentityDispositionError('Changed/missing035 function capability')
    cursor.execute("SELECT relname FROM pg_class WHERE relnamespace='public'::regnamespace AND relkind IN('r','p')")
    tables={r[0] for r in cursor.fetchall()}
    if not {'mlb_legacy_identity_retirements','mlb_legacy_identity_retirement_events','mlb_identity_topology_fence'}<=tables:
        raise IdentityDispositionError('Missing035 ledger/topology')
    cursor.execute("""SELECT DISTINCT c.relname FROM pg_constraint k JOIN pg_class c ON c.oid=k.conrelid
        WHERE k.contype='f' AND c.relnamespace='public'::regnamespace AND k.confrelid IN(
          'public.games'::regclass,'public.odds_market_snapshots'::regclass,
          'public.moneyline_prediction_runs'::regclass,'public.moneyline_game_predictions'::regclass,
          'public.moneyline_prediction_market_evaluations'::regclass)""")
    known=set(legacy034.GUARDED_TABLES)|{'game_identity_dispositions','mlb_legacy_identity_retirements','mlb_game_identity_write_fences','moneyline_daily_workflow_runs'}
    if any(row[0] not in known and not row[0].startswith('nfl_') for row in cursor.fetchall()):
        raise IdentityDispositionError('Unknown semantic foreign-key dependency capability')
    required={(t,'mlb_035_write_guard','mlb_retirement_write_guard',False,False) for t in GUARDED_TABLES if t in tables}
    required|={(t,'mlb_035_topology_ingress','mlb_retirement_ledger_ingress',False,False) for t in
        ('game_identity_dispositions','game_identity_disposition_events','mlb_legacy_identity_retirements','mlb_legacy_identity_retirement_events')}
    required|={(t,'mlb_z035_cross_guard','mlb_retirement_034_cross_guard',False,False) for t in
        ('game_identity_dispositions','game_identity_disposition_events')}
    required|={(t,'mlb_035_provenance_truncate','mlb_retirement_truncate',False,False) for t in
        ('game_sources','odds_snapshots','odds_market_snapshots','odds_provider_event_observations') if t in tables}
    required|={('mlb_legacy_identity_retirements','mlb_legacy_case_insert','mlb_retirement_case_insert',False,False),
        ('mlb_legacy_identity_retirements','mlb_legacy_case_complete','mlb_retirement_case_complete',True,True),
        ('mlb_legacy_identity_retirement_events','mlb_legacy_event_insert','mlb_retirement_event_insert',False,False),
        ('mlb_identity_topology_fence','mlb_topology_row','mlb_retirement_topology_integrity',False,False),
        ('mlb_identity_topology_fence','mlb_topology_truncate','mlb_retirement_topology_integrity',False,False)}
    required.add(('moneyline_prediction_runs','mlb_035_run_knowledge','mlb_retirement_run_guard',False,False))
    required|={(t,n,'mlb_identity_immutable',False,False) for t in
        ('mlb_legacy_identity_retirements','mlb_legacy_identity_retirement_events') for n in ('mlb_legacy_immutable','mlb_legacy_truncate')}
    cursor.execute("""SELECT c.relname,t.tgname,p.proname,t.tgdeferrable,t.tginitdeferred,t.tgenabled,t.tgtype::integer,n.nspname
        FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_proc p ON p.oid=t.tgfoid
        JOIN pg_namespace n ON n.oid=p.pronamespace
        WHERE c.relnamespace='public'::regnamespace AND t.tgname LIKE 'mlb_%'""")
    types={'mlb_035_write_guard':31,'mlb_035_topology_ingress':6,'mlb_z035_cross_guard':7,
           'mlb_035_provenance_truncate':34,'mlb_legacy_case_insert':7,'mlb_legacy_case_complete':5,
           'mlb_legacy_event_insert':7,'mlb_topology_row':31,'mlb_topology_truncate':34,
           'mlb_035_run_knowledge':23,'mlb_legacy_immutable':27,'mlb_legacy_truncate':34}
    observed={tuple(r[:5]) for r in cursor.fetchall() if r[5]=='O' and r[7]=='public' and r[6]==types.get(r[1])}
    if not required<=observed:
        raise IdentityDispositionError('Missing/disabled035 trigger capability')
    if set(VIEW_DEFINITIONS)!={'mlb_active_retired_identities','mlb_eligible_active_market_snapshots'}:
        raise IdentityDispositionError('Unreviewed035 view reference')
    for name,expected_view in VIEW_DEFINITIONS.items():
        cursor.execute('SELECT pg_get_viewdef(%s::regclass,true)',('public.'+name,))
        if re.sub(r'\s+','',cursor.fetchone()[0])!=re.sub(r'\s+','',expected_view):
            raise IdentityDispositionError('Changed035 read relation')
    cursor.execute("""SELECT c.relname,a.grantee,a.privilege_type FROM pg_class c
        CROSS JOIN LATERAL aclexplode(coalesce(c.relacl,acldefault('r',c.relowner))) a
        WHERE c.relnamespace='public'::regnamespace AND c.relname=ANY(%s)
        AND a.grantee<>c.relowner AND (a.grantee=0 OR a.privilege_type<>'SELECT')""",
        (['mlb_legacy_identity_retirements','mlb_legacy_identity_retirement_events','mlb_identity_topology_fence'],))
    if cursor.fetchall():
        raise IdentityDispositionError('Unsafe035 audit/topology ACL')
    cursor.execute("""SELECT p.proname FROM pg_proc p CROSS JOIN LATERAL
        aclexplode(coalesce(p.proacl,acldefault('f',p.proowner))) a
        WHERE p.pronamespace='public'::regnamespace AND p.proname=ANY(%s) AND a.grantee=0""",
        (list(PRIVILEGED_FUNCTIONS),))
    if cursor.fetchall():
        raise IdentityDispositionError('Unsafe035 privileged function ACL')
    verify_schema_catalog(cursor,list(expected))
    return True


def verify_schema_catalog(cursor,names):
    reference=json.loads(Path(__file__).with_name('mlb_retirement_schema035.json').read_text())
    migration=Path(__file__).resolve().parents[3]/'database/migrations'/MIGRATION
    if reference['migration_raw_sha256']!=sha256(migration.read_bytes()).hexdigest():
        raise IdentityDispositionError('Unreviewed035 catalog reference')
    tables=['mlb_identity_topology_fence','mlb_legacy_identity_retirements','mlb_legacy_identity_retirement_events']
    observed={}
    cursor.execute("""SELECT c.relname,a.attname,format_type(a.atttypid,a.atttypmod),a.attnotnull,a.attidentity,a.attgenerated,pg_get_expr(d.adbin,d.adrelid)
      FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid LEFT JOIN pg_attrdef d ON d.adrelid=a.attrelid AND d.adnum=a.attnum
      WHERE c.relnamespace='public'::regnamespace AND a.attnum>0 AND NOT a.attisdropped
      AND (c.relname=ANY(%s) OR(c.relname='moneyline_prediction_runs' AND a.attname='identity_retirement_knowledge')) ORDER BY c.relname,a.attnum""",(tables,))
    observed['columns']=cursor.fetchall()
    cursor.execute("""SELECT c.relname,k.conname,k.contype,pg_get_constraintdef(k.oid,true) FROM pg_constraint k JOIN pg_class c ON c.oid=k.conrelid
      WHERE c.relnamespace='public'::regnamespace AND (c.relname=ANY(%s) OR k.conname='chk_moneyline_retirement_knowledge') ORDER BY c.relname,k.conname""",(tables,))
    observed['constraints']=cursor.fetchall()
    cursor.execute("SELECT p.proname,pg_get_function_identity_arguments(p.oid),pg_get_function_result(p.oid),l.lanname,p.proretset,p.proisstrict,p.proleakproof,pg_get_function_arguments(p.oid) FROM pg_proc p JOIN pg_language l ON l.oid=p.prolang WHERE p.pronamespace='public'::regnamespace AND p.proname=ANY(%s) ORDER BY p.proname",(names,))
    observed['function_signatures']=cursor.fetchall()
    cursor.execute("SELECT indexname,indexdef FROM pg_indexes WHERE schemaname='public' AND indexname='mlb_legacy_survivor_idx'")
    observed['indexes']=cursor.fetchall()
    if json.loads(json.dumps(observed))!=reference['catalog']:
        raise IdentityDispositionError('Changed035 semantic catalog capability')
    cursor.execute("""SELECT count(*) FROM (
      SELECT relowner AS owner FROM pg_class WHERE relnamespace='public'::regnamespace AND relname=ANY(%s)
      UNION ALL SELECT proowner FROM pg_proc WHERE pronamespace='public'::regnamespace AND proname=ANY(%s)) x
      WHERE owner<>(SELECT relowner FROM pg_class WHERE oid='public.game_identity_dispositions'::regclass)""",(tables,names))
    if cursor.fetchone()!=(0,):raise IdentityDispositionError('Changed035 schema/function owner boundary')


def require_schema035(connection_factory):
    connection=connection_factory()
    try:
        connection.set_session(readonly=True,isolation_level='REPEATABLE READ')
        with connection.cursor() as cursor:
            cursor.execute('SELECT version,filename,checksum FROM schema_migrations ORDER BY version')
            if tuple((v,n,h.strip()) for v,n,h in cursor.fetchall())!=migration_reference():
                raise IdentityDispositionError('Exact001-035 schema required')
            verify_capabilities(cursor)
    finally:
        connection.rollback();connection.close()


def acquire_writer_gate(cursor):
    cursor.execute('SELECT mlb_retirement_topology_fresh()',())


def assert_active(cursor,game_id):
    if type(game_id) is not int or game_id<=0:raise IdentityDispositionError('Positive identity required')
    cursor.execute('SELECT mlb_retirement_assert_active(%s)',(game_id,))
    if cursor.fetchone()!=(True,):raise IdentityDispositionError('Active retirement identity unproven')


def assert_decision_write(cursor,**links):
    allowed={'game_id','odds_market_snapshot_id','moneyline_game_prediction_id','moneyline_prediction_market_evaluation_id'}
    if not links or set(links)-allowed or any(type(v) is not int or v<=0 for v in links.values()):
        raise IdentityDispositionError('Exact positive decision links required')
    acquire_writer_gate(cursor)
    cursor.execute('SELECT mlb_retirement_assert_decision_links(%s::jsonb)',(json.dumps(links,sort_keys=True),))


def active_predicate(alias):
    if alias not in ('g','game','candidate','requested'):raise ValueError('Unreviewed alias')
    return f'NOT EXISTS (SELECT 1 FROM mlb_active_retired_identities r WHERE r.subject_game_id={alias}.game_id)'


def load_identity_state(cursor):
    state=legacy034.load_identity_state(cursor)
    cursor.execute('SELECT to_jsonb(r) FROM mlb_legacy_identity_retirements r ORDER BY subject_game_id LIMIT 1001')
    cases=[r[0] for r in cursor.fetchall()]
    cursor.execute('SELECT to_jsonb(e) FROM mlb_legacy_identity_retirement_events e ORDER BY retirement_id LIMIT 1001')
    events=[r[0] for r in cursor.fetchall()]
    if len(cases)>1000 or len(events)!=len(cases):raise IdentityDispositionError('Invalid legacy bounded ledger')
    for case in cases:
        event=[e for e in events if e['retirement_id']==case['retirement_id']]
        if (case['domain']!='MLB' or case['category'] not in ('LEGACY_MARKET_DUPLICATE_WITHOUT_OBSERVATION_PROVENANCE','IDENTITY_ONLY_DUPLICATE')
                or case['policy_version']!='1.0.0' or type(case['game_pk']) is not int or case['game_pk']<=0
                or case['subject_game_id']==case['survivor_game_id']
                or len(event)!=1 or event[0]['action']!='ACTIVATE' or event[0]['sequence']!=1
                or event[0]['approved_preview_sha256']!=case['approved_preview_sha256']
                or any(c['subject_game_id']==case['subject_game_id'] or c['subject_game_id']==case['survivor_game_id']
                       or c['survivor_game_id']==case['subject_game_id'] for c in state['cases'])):
            raise IdentityDispositionError('Malformed combined retirement state')
        state['active'][case['subject_game_id']]=dict(case=case,event=event[0],origin='035')
    if any(v['case']['survivor_game_id'] in state['active'] for v in state['active'].values()):
        raise IdentityDispositionError('Combined role chain/cycle')
    cursor.execute('SELECT mlb_retirement_legacy_fingerprint(),epoch,mlb_retirement_fingerprint(%s) FROM mlb_identity_topology_fence WHERE singleton',(profile_fingerprint(),))
    row=cursor.fetchone()
    if row is None:raise IdentityDispositionError('Missing topology')
    state.update(ledger034=state['fingerprint'],legacy_cases=cases,legacy_events=events,
                 ledger035=row[0],topology_epoch=row[1],fingerprint=row[2])
    return state


def raw_identity(cursor,game_id):
    state=load_identity_state(cursor)
    cursor.execute('SELECT to_jsonb(g) FROM games g WHERE game_id=%s',(game_id,))
    row=cursor.fetchone()
    if row is None:raise IdentityDispositionError('Missing physical game')
    return dict(physical_game=row[0],retirement=state['active'].get(game_id),lookup_purpose='RAW_FORENSIC',
                active_event_eligibility_verified=False,ledger_fingerprint=state['fingerprint'])


@dataclass(frozen=True)
class IdentityKnowledgeSnapshot:
    profile: str
    fingerprint: str
    ledger034: str
    ledger035: str
    topology_epoch: int
    available_at: str
    endpoint: tuple
    artifact_sha256: str
    capture_attestation: object=None

    def body(self):
        return dict(version=2,profile=self.profile,fingerprint=self.fingerprint,ledger034=self.ledger034,
                    ledger035=self.ledger035,topology_epoch=self.topology_epoch,
                    available_at=self.available_at,endpoint=list(self.endpoint))


def _hash(body):return sha256(json.dumps(body,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def capture_identity_knowledge(*,connection_factory):
    connection=connection_factory()
    try:
        connection.set_session(readonly=True,isolation_level='REPEATABLE READ')
        with connection.cursor() as cursor:
            cursor.execute('SELECT version,filename,checksum FROM schema_migrations ORDER BY version')
            if tuple((v,n,h.strip()) for v,n,h in cursor.fetchall())!=migration_reference():raise IdentityDispositionError('Exact035 schema required')
            verify_capabilities(cursor)
            state=load_identity_state(cursor)
            cursor.execute('SELECT clock_timestamp()');available=cursor.fetchone()[0]
        if available.tzinfo is None:raise IdentityDispositionError('Aware DB clock required')
        body=dict(version=2,profile=profile_fingerprint(),fingerprint=state['fingerprint'],ledger034=state['ledger034'],
                  ledger035=state['ledger035'],topology_epoch=state['topology_epoch'],available_at=available.isoformat(),
                  endpoint=[connection.info.host,connection.info.port,connection.info.dbname])
        return IdentityKnowledgeSnapshot(**{k:tuple(v) if k=='endpoint' else v for k,v in body.items() if k!='version'},
                                         artifact_sha256=_hash(body),capture_attestation=_COMMITTED)
    finally:connection.rollback();connection.close()


def install_identity_knowledge(cursor,snapshot,*,cutoff_time,current_factory=None):
    if not isinstance(snapshot,IdentityKnowledgeSnapshot) or snapshot.capture_attestation is not _COMMITTED or cutoff_time.tzinfo is None:
        raise IdentityDispositionError('Sealed committed v2 knowledge required')
    if (datetime.fromisoformat(snapshot.available_at)>cutoff_time or _hash(snapshot.body())!=snapshot.artifact_sha256
            or snapshot.profile!=profile_fingerprint()):raise IdentityDispositionError('Unavailable/changed v2 knowledge')
    # Advisory locks are permitted in read-only sessions. Probe a fresh dedicated
    # RO snapshot while SHARED is held: old RR membership cannot hide activation.
    cursor.execute('SELECT mlb_identity_gate(false)',())
    if current_factory is None:raise IdentityDispositionError('Fresh current-state factory required')
    probe=current_factory()
    try:
        if (probe.info.host,probe.info.port,probe.info.dbname)!=snapshot.endpoint:raise IdentityDispositionError('Knowledge endpoint differs')
        probe.set_session(readonly=True,isolation_level='REPEATABLE READ')
        with probe.cursor() as c:
            verify_capabilities(c)
            c.execute('SELECT mlb_retirement_fingerprint(%s),clock_timestamp()',(snapshot.profile,))
            current,now=c.fetchone()
        if current!=snapshot.fingerprint or cutoff_time>now:raise IdentityDispositionError('Committed retirement changed/future cutoff')
    finally:probe.rollback();probe.close()
    child=dict(version=1,ledger_fingerprint=snapshot.ledger034,available_at=snapshot.available_at,cutoff_time=cutoff_time.isoformat())
    cursor.execute("SELECT set_config('sportsmodel.identity_knowledge',%s,true)",(json.dumps(child,sort_keys=True),))
    cursor.execute("SELECT set_config('sportsmodel.retirement_knowledge',%s,true)",(json.dumps(dict(snapshot.body(),cutoff_time=cutoff_time.isoformat(),artifact_sha256=snapshot.artifact_sha256),sort_keys=True),))
    cursor.execute('SELECT mlb_retirement_history_guard()')
    if cursor.fetchone()!=(True,):raise IdentityDispositionError('Unproven retirement knowledge')


def knowledge_connection_factory(factory,snapshot,*,cutoff_time):
    def connected():
        connection=factory()
        try:
            with connection.cursor() as cursor:install_identity_knowledge(cursor,snapshot,cutoff_time=cutoff_time,current_factory=factory)
            return connection
        except Exception:connection.rollback();connection.close();raise
    return connected


_COMMITTED_CAPTURE=_COMMITTED
_knowledge_hash=_hash
