"""MLB active-event eligibility is separate from immutable Odds acquisition.

No automatic survivor redirection. Capture committed knowledge with a dedicated
read-only transaction; current-state reads cannot certify a historical cutoff.
"""
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path
import re
_COMMITTED_CAPTURE = object()

# Exact PG16 expansion of the reviewed migration's active relation. Whitespace
# is immaterial; changed projection, action, ordering or limit must refuse.
ACTIVE_VIEW_DEFINITION = """SELECT d.disposition_id,d.domain,d.subject_game_id,d.survivor_game_id,
 d.disposition_type,d.policy_version,d.reason,d.evidence_reference,d.evidence_sha256,
 d.operator_identity,d.tool_identity,d.implementation_commit,d.implementation_sha256,
 d.initial_manifest_sha256,d.created_at,e.event_id,e.sequence,e.created_at AS state_recorded_at,
 e.approved_manifest_sha256 FROM game_identity_dispositions d JOIN LATERAL (
 SELECT ev.event_id,ev.disposition_id,ev.sequence,ev.previous_event_id,ev.action,ev.reason,
 ev.evidence_reference,ev.evidence_sha256,ev.operator_identity,ev.tool_identity,
 ev.implementation_commit,ev.implementation_sha256,ev.approved_manifest_sha256,
 ev.pre_state_sha256,ev.post_state_sha256,ev.receipt,ev.created_at
 FROM game_identity_disposition_events ev WHERE ev.disposition_id = d.disposition_id
 ORDER BY ev.sequence DESC LIMIT 1) e ON true WHERE e.action = 'ACTIVATE'::text;"""

GUARDED_TABLES = ('games','game_sources','historical_games','game_results','teams','baseball_team_sources',
                 'sportsbooks','sportsbook_provider_identities','odds_ingestion_runs',
                 'team_game_statistics','player_game_pitching_statistics','model_predictions',
                 'moneyline_game_predictions','moneyline_prediction_market_evaluations',
                 'moneyline_paper_candidate_settlements','market_analysis','odds_snapshots',
                 'odds_market_snapshots','odds_provider_event_observations',
                 'odds_provider_event_canonical_corrections')


def expected_functions():
    path = Path(__file__).resolve().parents[3]/'database/migrations/034_create_mlb_identity_dispositions.sql'
    source = path.read_text(encoding='utf-8-sig')
    return {name:(body.strip(), 's' if re.search(r'\bSTABLE\b', attributes) else 'v',
                  'SECURITY DEFINER' in attributes,
                  ['search_path=pg_catalog, public'] if 'SET search_path' in attributes else None)
            for name,attributes,body in re.findall(r'CREATE FUNCTION (mlb_[a-z_]+)\b(.*?)\bAS\s+\$\$(.*?)\$\$;',source,re.S)}


def verify_capabilities(cursor):
    """Verify actual function bodies/attributes and enabled write-boundary guards."""
    expected = expected_functions()
    if not {'mlb_identity_gate','mlb_identity_write_guard','mlb_identity_event_insert',
            'mlb_identity_history_guard','mlb_identity_assert_active'} <= set(expected):
        raise IdentityDispositionError('Invalid migration034 source capability inventory')
    cursor.execute("""SELECT p.proname,p.prosrc,p.provolatile,p.prosecdef,p.proconfig
        FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
        WHERE n.nspname='public' AND p.proname=ANY(%s) ORDER BY p.proname""", (list(expected),))
    rows = cursor.fetchall()
    observed = {row[0]:(row[1].strip(),row[2],row[3],row[4]) for row in rows}
    if len(rows)!=len(observed) or observed!=expected:
        raise IdentityDispositionError('Missing/changed migration034 function capability')
    cursor.execute("SELECT relname FROM pg_class WHERE relnamespace='public'::regnamespace AND relkind IN ('r','p')")
    tables = {row[0] for row in cursor.fetchall()}
    if not {'game_identity_dispositions','game_identity_disposition_events','mlb_game_identity_write_fences'} <= tables:
        raise IdentityDispositionError('Missing migration034 ledger/fence capability')
    cursor.execute("""SELECT DISTINCT c.relname FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid
        WHERE c.relnamespace='public'::regnamespace AND c.relkind IN ('r','p')
        AND a.attnum>0 AND NOT a.attisdropped
        AND a.attname IN ('game_id','original_game_id','corrected_game_id',
                         'odds_market_snapshot_id','moneyline_game_prediction_id',
                         'moneyline_prediction_market_evaluation_id')""")
    uncovered = {row[0] for row in cursor.fetchall()} - set(GUARDED_TABLES) - {'mlb_game_identity_write_fences'}
    if any(not name.startswith('nfl_') for name in uncovered):
        raise IdentityDispositionError('Uncovered semantic identity/decision dependency capability')
    required = {(table,name) for table,names in {
        'game_identity_dispositions':('mlb_case_insert','mlb_case_complete','mlb_case_immutable','mlb_case_truncate','mlb_case_ingress'),
        'game_identity_disposition_events':('mlb_event_insert','mlb_event_immutable','mlb_event_truncate','mlb_event_ingress'),
        'mlb_game_identity_write_fences':('mlb_fence_row','mlb_fence_truncate'),
        'game_sources':('mlb_source_truncate',),'odds_market_snapshots':('mlb_snapshot_truncate',),
        'odds_provider_event_observations':('mlb_observation_truncate',)}.items() for name in names}
    required |= {(table,name) for table in GUARDED_TABLES if table in tables
                 for name in ('mlb_identity_ingress','mlb_identity_write_guard')}
    cursor.execute("""SELECT c.relname,t.tgname,t.tgenabled,p.proname,n.nspname,t.tgdeferrable,t.tginitdeferred
        FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid
        JOIN pg_proc p ON p.oid=t.tgfoid JOIN pg_namespace n ON n.oid=p.pronamespace
        WHERE c.relnamespace='public'::regnamespace
        AND t.tgname LIKE 'mlb_%'""")
    trigger_rows = cursor.fetchall()
    bindings = {'mlb_case_insert':'mlb_identity_case_insert','mlb_case_complete':'mlb_identity_case_complete',
        'mlb_event_insert':'mlb_identity_event_insert','mlb_fence_row':'mlb_identity_fence_integrity',
        'mlb_fence_truncate':'mlb_identity_fence_integrity','mlb_identity_write_guard':'mlb_identity_write_guard'}
    enabled = set()
    for row in trigger_rows:
        name=row[1]
        expected_binding=bindings.get(name,
            'mlb_identity_ingress' if name.endswith('ingress') else
            'mlb_identity_provenance_truncate' if name in ('mlb_source_truncate','mlb_snapshot_truncate','mlb_observation_truncate')
            else 'mlb_identity_immutable')
        if row[2]=='O' and row[3]==expected_binding and row[4]=='public':
            if name=='mlb_case_complete' and (not row[5] or not row[6]):
                raise IdentityDispositionError('Initial ACTIVATE deferred constraint is incompatible')
            enabled.add((row[0],name))
    if not required <= enabled:
        raise IdentityDispositionError('Missing/disabled migration034 trigger capability')
    cursor.execute("SELECT to_regclass('public.mlb_active_stale_identity_dispositions')")
    if cursor.fetchone()[0] is None:
        raise IdentityDispositionError('Missing active-disposition read relation')
    cursor.execute("SELECT pg_get_viewdef('public.mlb_active_stale_identity_dispositions'::regclass,true)")
    definition=cursor.fetchone()[0]
    if re.sub(r'\s+','',definition)!=re.sub(r'\s+','',ACTIVE_VIEW_DEFINITION):
        raise IdentityDispositionError('Changed active-disposition read relation')
    return True


def require_schema034(connection_factory):
    """Normal live preflight, before providers/reservations; no ambient fallback."""
    from sportsmodel.database.mlb_operator_guard import migration_reference
    connection = connection_factory()
    try:
        connection.set_session(readonly=True,isolation_level='REPEATABLE READ')
        with connection.cursor() as cursor:
            cursor.execute('SELECT version,filename,checksum FROM schema_migrations ORDER BY version')
            if tuple((v,name,value.strip()) for v,name,value in cursor.fetchall()) != migration_reference():
                raise IdentityDispositionError('Exact001-034 migration identity required')
            verify_capabilities(cursor)
    finally:
        connection.rollback()
        connection.close()


class IdentityDispositionError(RuntimeError):
    """Malformed identity state or ineligible active-event use."""


ACTIVE_PREDICATE = "NOT EXISTS (SELECT 1 FROM mlb_active_stale_identity_dispositions identity_disposition WHERE identity_disposition.subject_game_id = {alias}.game_id)"


def active_predicate(alias):
    if alias not in {'g', 'game', 'candidate', 'requested'}:
        raise ValueError('Unreviewed SQL alias')
    return ACTIVE_PREDICATE.format(alias=alias)


def assert_active(cursor, game_id):
    if type(game_id) is not int or game_id <= 0:
        raise IdentityDispositionError('Positive physical game identity required')
    cursor.execute('SELECT mlb_identity_assert_active(%s)', (game_id,))
    if cursor.fetchone() != (True,):
        raise IdentityDispositionError('Active identity could not be verified')


def acquire_writer_gate(cursor):
    """Must precede identity reads and row locks; no lock promotion/retry."""
    cursor.execute('SELECT mlb_identity_gate(false)', ())


def assert_decision_write(cursor, **links):
    """Validate application write admission before any result/decision mutation."""
    allowed = {'game_id', 'odds_market_snapshot_id', 'moneyline_game_prediction_id',
               'moneyline_prediction_market_evaluation_id'}
    if not links or set(links)-allowed or any(type(value) is not int or value<=0 for value in links.values()):
        raise IdentityDispositionError('Exact positive decision linkage required')
    acquire_writer_gate(cursor)
    cursor.execute('SELECT mlb_identity_assert_decision_links(%s::jsonb)', (json.dumps(links, sort_keys=True),))


def load_identity_state(cursor):
    cursor.execute("""SELECT to_jsonb(d) FROM game_identity_dispositions d
        ORDER BY subject_game_id LIMIT 1001""")
    cases = [r[0] for r in cursor.fetchall()]
    cursor.execute("""SELECT to_jsonb(e) FROM game_identity_disposition_events e
        ORDER BY disposition_id,sequence LIMIT 10001""")
    events = [r[0] for r in cursor.fetchall()]
    if len(cases)>1000 or len(events)>10000:
        raise IdentityDispositionError('Ledger exceeds bounded policy capacity')
    latest = {}
    for event in events:
        previous = latest.get(event['disposition_id'])
        if (event['action'] not in ('ACTIVATE', 'REVOKE')
                or event['sequence'] != (previous['sequence'] + 1 if previous else 1)
                or event['previous_event_id'] != (previous['event_id'] if previous else None)
                or (previous and event['action'] == previous['action'])
                or (not previous and event['action'] != 'ACTIVATE')):
            raise IdentityDispositionError('Malformed identity event chain')
        latest[event['disposition_id']] = event
    subjects = set()
    active = {}
    for case in cases:
        event = latest.get(case['disposition_id'])
        if (case['domain'] != 'MLB' or case['policy_version'] != '1.0.0'
                or case['disposition_type'] != 'STALE_MARKET_ONLY_DUPLICATE'
                or case['subject_game_id'] == case['survivor_game_id']
                or case['subject_game_id'] in subjects or event is None):
            raise IdentityDispositionError('Malformed identity case')
        subjects.add(case['subject_game_id'])
        if event['action'] == 'ACTIVATE':
            active[case['subject_game_id']] = dict(case=case, event=event)
    if len(latest) != len(cases) or any(v['case']['survivor_game_id'] in active for v in active.values()):
        raise IdentityDispositionError('Orphan event or disposition chain/cycle')
    cursor.execute('SELECT mlb_identity_ledger_fingerprint()')
    fingerprint = cursor.fetchone()[0]
    if not isinstance(fingerprint, str) or not re.fullmatch('[0-9a-f]{64}',fingerprint):
        raise IdentityDispositionError('Invalid ledger fingerprint')
    return dict(cases=cases, events=events, active=active, fingerprint=fingerprint)


def raw_identity(cursor, game_id):
    """Forensic-only physical lookup, explicitly labelled; never a redirect."""
    state = load_identity_state(cursor)
    cursor.execute('SELECT to_jsonb(g) FROM games g WHERE game_id=%s', (game_id,))
    row = cursor.fetchone()
    if row is None:
        raise IdentityDispositionError('Missing physical game')
    case = next((item for item in state['cases'] if item['subject_game_id'] == game_id), None)
    event = next((item for item in reversed(state['events']) if case and item['disposition_id'] == case['disposition_id']), None)
    disposition = dict(case=case,event=event) if case else None
    return dict(physical_game=row[0], disposition=disposition,
                active_event_eligibility_verified=False, lookup_purpose='RAW_FORENSIC',
                ledger_fingerprint=state['fingerprint'])


@dataclass(frozen=True)
class IdentityKnowledgeSnapshot:
    ledger_fingerprint: str
    available_at: str
    artifact_sha256: str
    capture_attestation: object = None

    def body(self):
        return dict(version=1, ledger_fingerprint=self.ledger_fingerprint, available_at=self.available_at)


def _knowledge_hash(body):
    return sha256(json.dumps(body, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def capture_identity_knowledge(*, connection_factory):
    """Fresh READ ONLY snapshot proves committed availability, not insert time."""
    connection = connection_factory()
    try:
        connection.set_session(readonly=True, isolation_level='REPEATABLE READ')
        with connection.cursor() as cursor:
            verify_capabilities(cursor)
            state = load_identity_state(cursor)
            cursor.execute('SELECT clock_timestamp()')
            available = cursor.fetchone()[0]
        if available.tzinfo is None:
            raise IdentityDispositionError('Aware trusted DB clock required')
        body = dict(version=1, ledger_fingerprint=state['fingerprint'], available_at=available.isoformat())
        return IdentityKnowledgeSnapshot(body['ledger_fingerprint'], body['available_at'], _knowledge_hash(body), _COMMITTED_CAPTURE)
    finally:
        connection.rollback()
        connection.close()


def install_identity_knowledge(cursor, snapshot, *, cutoff_time):
    if (not isinstance(snapshot, IdentityKnowledgeSnapshot) or cutoff_time.tzinfo is None
            or snapshot.capture_attestation is not _COMMITTED_CAPTURE):
        raise IdentityDispositionError('Committed knowledge snapshot and aware cutoff required')
    available = datetime.fromisoformat(snapshot.available_at)
    if available.tzinfo is None or available > cutoff_time or _knowledge_hash(snapshot.body()) != snapshot.artifact_sha256:
        raise IdentityDispositionError('Knowledge snapshot unavailable or changed at cutoff')
    body = dict(snapshot.body(), cutoff_time=cutoff_time.isoformat())
    cursor.execute("SELECT set_config('sportsmodel.identity_knowledge',%s,true)", (json.dumps(body, sort_keys=True),))
    cursor.execute('SELECT mlb_identity_history_guard()')
    if cursor.fetchone() != (True,):
        raise IdentityDispositionError('Knowledge-state changed after capture')


def knowledge_connection_factory(factory, snapshot, *, cutoff_time):
    """Share one verified knowledge artifact across independent feature reads."""
    def connected():
        connection = factory()
        try:
            with connection.cursor() as cursor:
                install_identity_knowledge(cursor, snapshot, cutoff_time=cutoff_time)
            return connection
        except Exception:
            connection.rollback()
            connection.close()
            raise
    return connected
