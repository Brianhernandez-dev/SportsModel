"""Explicit036 target/candidate guard; no ambient credential/provider discovery."""
from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
import json
import re

from sportsmodel.database.mlb_retirement_guard import OperatorTarget as Target035
from sportsmodel.database.mlb_operator_guard import OperatorRefusal, aware, native_process_proof, validate_native_proof
from sportsmodel.database import mlb_retirement_repository as frozen035

MIGRATION = '036_create_mlb_canonical_time_arbitration.sql'
FROZEN034 = '82D7840198A88780E24D264F929EA78D3EE6CE0BCCA08060C8D8E3767CB432D9'
FROZEN035 = 'BF9A6FAD169FDB62441289DED2E9E5664244E91F4C4AE3EEB3B9D27DE5233A47'


def reject_uncertified036(cursor):
    """Legacy MLB time readers refuse036 instead of accepting a forged v2 GUC."""
    cursor.execute("SELECT EXISTS(SELECT 1 FROM pg_catalog.pg_namespace WHERE nspname='mlb036_private')")
    row=cursor.fetchone()
    if type(row) is not tuple or len(row)!=1 or row[0] is not False:
        raise OperatorRefusal('Schema036 time-sensitive MLB input requires an explicit certified reader')


@dataclass(frozen=True)
class OperatorTarget(Target035):
    migration_boundary: int = 36

    def __post_init__(self):
        if self.migration_boundary != 36 or type(self.migration_boundary) is not int:
            raise OperatorRefusal('Exact036 target required')
        value = asdict(self)
        value['migration_boundary'] = 35
        Target035(**value)


def migration_reference():
    root = Path(__file__).resolve().parents[3]
    files = sorted((root/'database/migrations').glob('*.sql'))
    if [int(p.name[:3]) for p in files] != list(range(1, 37)):
        raise OperatorRefusal('Exact001-036 inventory required')
    frozen = {p.name[:3]: sha256(p.read_bytes()).hexdigest().upper() for p in files}
    if frozen['034'] != FROZEN034 or frozen['035'] != FROZEN035:
        raise OperatorRefusal('Frozen034/035 bytes changed')
    return tuple((int(p.name[:3]), p.name, sha256(p.read_text(encoding='utf-8-sig').encode()).hexdigest()) for p in files)


def profile_fingerprint():
    root = Path(__file__).resolve().parents[3]
    files = {p.relative_to(root).as_posix(): sha256(p.read_bytes()).hexdigest()
             for p in (root/'src/sportsmodel').rglob('*.py')
             if not any(part in ('nfl','models','modeling') for part in p.relative_to(root/'src/sportsmodel').parts)}
    files['migrations'] = migration_reference()
    files['schema035_catalog'] = sha256(Path(__file__).with_name('mlb_retirement_schema035.json').read_bytes()).hexdigest()
    files['schema036_catalog'] = sha256(Path(__file__).with_name('mlb_canonical_time_schema036.json').read_bytes()).hexdigest()
    return sha256(json.dumps(files,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def schema_catalog036(cursor):
    """OID/role-name independent structural036 catalog; metadata SELECT only."""
    # Deparser qualification must not depend on the client's namespace ACL or
    # ambient search_path. All inspected catalog objects remain fully named.
    cursor.execute("SELECT pg_catalog.set_config('search_path','pg_catalog',true)")
    observed={}
    cursor.execute("""SELECT n.nspname,c.relname,a.attname,format_type(a.atttypid,a.atttypmod),a.attnotnull,a.attidentity,a.attgenerated,pg_get_expr(d.adbin,d.adrelid)
      FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid JOIN pg_namespace n ON n.oid=c.relnamespace
      LEFT JOIN pg_attrdef d ON d.adrelid=a.attrelid AND d.adnum=a.attnum
      WHERE a.attnum>0 AND NOT a.attisdropped AND
        ((n.nspname='mlb036_private' AND c.relkind IN('r','p')) OR
        (n.nspname='public' AND c.relname='moneyline_prediction_runs' AND a.attname='canonical_time_knowledge')) ORDER BY n.nspname,c.relname,a.attnum""")
    observed['columns']=cursor.fetchall()
    cursor.execute("""SELECT n.nspname,c.relname,k.conname,k.contype,pg_get_constraintdef(k.oid,true)
      FROM pg_constraint k JOIN pg_class c ON c.oid=k.conrelid JOIN pg_namespace n ON n.oid=c.relnamespace
      WHERE n.nspname='mlb036_private' ORDER BY c.relname,k.conname""")
    observed['constraints']=cursor.fetchall()
    cursor.execute("""SELECT p.proname,pg_get_function_identity_arguments(p.oid),pg_get_function_result(p.oid),l.lanname,
      p.proretset,p.proisstrict,p.proleakproof,pg_get_function_arguments(p.oid),p.proconfig
      FROM pg_proc p JOIN pg_language l ON l.oid=p.prolang WHERE p.pronamespace='mlb036_private'::regnamespace ORDER BY p.proname,p.oid""")
    observed['function_signatures']=cursor.fetchall()
    cursor.execute("""SELECT n.nspname,c.relname,t.tgname,t.tgenabled,pg_get_triggerdef(t.oid)
      FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_namespace n ON n.oid=c.relnamespace
      WHERE NOT t.tgisinternal AND (n.nspname='mlb036_private' OR
        (n.nspname='public' AND t.tgname IN('mlb_036_game_seal','mlb036_correction_complete','mlb_036_source_seal','mlb_000036_run_knowledge','mlb_000036_prediction_knowledge')))
      ORDER BY n.nspname,c.relname,t.tgname""")
    observed['triggers']=cursor.fetchall()
    cursor.execute("SELECT indexname,indexdef FROM pg_indexes WHERE schemaname='mlb036_private' ORDER BY indexname")
    observed['indexes']=cursor.fetchall()
    return json.loads(json.dumps(observed))


def verify_schema_catalog036(cursor):
    root=Path(__file__).resolve().parents[3]
    reference=json.loads(Path(__file__).with_name('mlb_canonical_time_schema036.json').read_text(encoding='utf-8'))
    if (set(reference)!= {'migration_raw_sha256','catalog'}
        or reference['migration_raw_sha256']!=sha256((root/'database/migrations'/MIGRATION).read_bytes()).hexdigest()):
        raise OperatorRefusal('Unreviewed036 structural catalog reference')
    if schema_catalog036(cursor)!=reference['catalog']:
        raise OperatorRefusal('Changed036 columns/constraints/signatures/triggers/indexes')


class _CatalogCursor:
    """Resolve frozen catalog identities without granting public namespace use.

    This adapter executes SELECT-only metadata queries. It never executes a public
    callable or reads a business row; the unchanged034/035 verifiers retain their
    exact predicates, using numeric catalog OIDs instead of ACL-checked name casts.
    """
    def __init__(self,cursor):self._cursor=cursor;self._normalize=False
    def __getattr__(self,name):return getattr(self._cursor,name)

    def _oid(self,name,kind):
        if kind=='regnamespace':
            if name not in ('public','mlb036_private'):raise OperatorRefusal('Unreviewed catalog namespace')
            self._cursor.execute('SELECT oid FROM pg_catalog.pg_namespace WHERE nspname=%s',(name,))
        else:
            if not re.fullmatch(r'public\.[a-z_]+',name):raise OperatorRefusal('Unreviewed frozen catalog relation')
            self._cursor.execute("SELECT c.oid FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND c.relname=%s",(name.split('.')[1],))
        rows=self._cursor.fetchall()
        if len(rows)!=1:raise OperatorRefusal('Missing/ambiguous frozen catalog identity')
        return rows[0][0]

    def execute(self,statement,params=None):
        if type(statement) is not str or not statement.lstrip().upper().startswith('SELECT'):
            raise OperatorRefusal('Catalog adapter is metadata SELECT only')
        self._normalize=any(name in statement for name in ('pg_get_viewdef','pg_get_function_identity_arguments',
            'pg_get_function_result','pg_get_function_arguments','pg_get_constraintdef','pg_get_expr'))
        statement=re.sub(r"'([a-z_.]+)'::(regclass|regnamespace)",
            lambda match:str(self._oid(match[1],match[2]))+'::oid',statement)
        if '%s::regclass' in statement:
            if statement.count('%s')!=1 or params is None or len(params)!=1:
                raise OperatorRefusal('Unreviewed parameterized catalog identity')
            params=(self._oid(params[0],'regclass'),)
            statement=statement.replace('%s::regclass','%s::oid')
        statement=re.sub(r"to_regclass\('([a-z_.]+)'\)",
            lambda match:str(self._oid(match[1],'regclass'))+'::oid',statement)
        return self._cursor.execute(statement,params)

    def _render(self,row):
        if not self._normalize:return row
        def normalize(value):
            if type(value) is not str:return value
            # Only visibility-driven public identifier qualifiers change. Never
            # rewrite quoted SQL literals, function bodies, or index definitions.
            pieces=re.split(r"('(?:[^']|'')*')",value)
            return ''.join(piece if i%2 else re.sub(r'\bpublic\.','',piece) for i,piece in enumerate(pieces))
        return tuple(normalize(value) for value in row)

    def fetchone(self):
        row=self._cursor.fetchone()
        return None if row is None else self._render(row)

    def fetchall(self):return [self._render(row) for row in self._cursor.fetchall()]


def verify_capabilities(cursor):
    """Retain exact035 validation; add exact036 bodies/attributes, no max-version shortcut."""
    frozen035.verify_capabilities(_CatalogCursor(cursor))
    verify_schema_catalog036(cursor)
    path = Path(__file__).resolve().parents[3]/'database/migrations'/MIGRATION
    text = path.read_text(encoding='utf-8-sig')
    expected = {}
    for name, attrs, body in re.findall(r'CREATE FUNCTION mlb036_private\.([a-z_]+)\b(.*?)\bAS\s+\$\$(.*?)\$\$;',text,re.S):
        expected[name] = (body.strip(), 'i' if 'IMMUTABLE' in attrs else 's' if 'STABLE' in attrs else 'v',
                          'SECURITY DEFINER' in attrs, 's' if 'PARALLEL SAFE' in attrs else 'u')
    cursor.execute("""SELECT p.proname,p.prosrc,p.provolatile,p.prosecdef,p.proparallel FROM pg_proc p
        WHERE p.pronamespace='mlb036_private'::regnamespace""")
    rows=cursor.fetchall()
    observed = {r[0]: (r[1].strip(), *r[2:]) for r in rows}
    if len(rows)!=len(expected) or observed != expected:
        raise OperatorRefusal('Unknown/missing/changed036 function capability')
    cursor.execute("""SELECT r.rolcanlogin,r.rolsuper,r.rolcreaterole,r.rolcreatedb,r.rolreplication,r.rolbypassrls FROM pg_namespace n
        JOIN pg_roles r ON r.oid=n.nspowner WHERE n.nspname='mlb036_private'""")
    if cursor.fetchone() != (False, False, False, False, False, False):
        raise OperatorRefusal('036 non-login non-bypass owner required')
    cursor.execute("""SELECT relname FROM pg_class WHERE relnamespace='mlb036_private'::regnamespace AND relkind IN('r','p') ORDER BY relname""")
    if [r[0] for r in cursor.fetchall()] != ['arbitration_events','arbitrations','authority','knowledge_receipts']:
        raise OperatorRefusal('036 strict audit/receipt registry differs')
    cursor.execute("""SELECT p.proname,p.proconfig,p.proowner,r.rolcanlogin,r.rolsuper,r.rolcreaterole,r.rolcreatedb,r.rolreplication,r.rolbypassrls
        FROM pg_proc p JOIN pg_roles r ON r.oid=p.proowner WHERE p.pronamespace='mlb036_private'::regnamespace""")
    owners={}
    for name,config,owner,login,superuser,create_role,create_db,replication,bypass in cursor.fetchall():
        if any((login,superuser,create_role,create_db,replication,bypass)):
            raise OperatorRefusal('036 callable owner is not restricted non-login')
        if not config or not any(v in config for v in ('search_path=pg_catalog','search_path=pg_catalog, mlb036_private, public, pg_temp')):
            raise OperatorRefusal('036 callable trusted search path differs')
        owners[name]=owner
    if (len({owners[n] for n in ('context','validate_knowledge','certified_data','post_correction_preview','inspect_knowledge','raw_case_snapshot')})!=1
        or owners['certified_data']==owners['issue_knowledge'] or owners['certified_data']==owners['correct_exact']):
        raise OperatorRefusal('036 read/write definer owner separation missing')
    return True


def verify_target(connection, target, *, readonly, process_probe=native_process_proof):
    if not isinstance(target, OperatorTarget):
        raise OperatorRefusal('Explicit036 target object required')
    if (connection.info.host,connection.info.port,connection.info.dbname) != (target.host,target.port,target.database):
        raise OperatorRefusal('036 client endpoint differs')
    with connection.cursor() as cursor:
        cursor.execute('SELECT mlb036_private.describe_target()')
        identity=cursor.fetchone()[0]
        db,address,port,started,backend,version,read_only,isolation = (identity[k] for k in ('database','address','port','started','backend','version','readonly','isolation'))
        started=aware(started)
        if (db,address,port,started) != (target.database,target.server_address,target.server_port,aware(target.postmaster_started_at)):
            raise OperatorRefusal('036 server identity/epoch differs')
        if int(version)//10000 != 16 or read_only != ('on' if readonly else 'off'):
            raise OperatorRefusal('036 PostgreSQL16/read-only boundary differs')
        if isolation != ('repeatable read' if readonly else 'serializable'):
            raise OperatorRefusal('036 operator isolation differs')
        if target.identity_kind == 'native':
            validate_native_proof(process_probe(backend),backend)
        else:
            if identity['system_identifier'] != target.system_identifier:
                raise OperatorRefusal('036 isolated system identity differs')
        if tuple((v,n,h.strip()) for v,n,h in identity['migrations']) != migration_reference():
            raise OperatorRefusal('036 exact migration checksums differ')
        verify_capabilities(cursor)
    return dict(target=target.artifact(),profile=profile_fingerprint())


def verify_locked_target(connection,target,*,expected_migrations,expected_profile):
    """SQL-only X check against preloaded identities; no filesystem/provider I/O."""
    if (connection.info.host,connection.info.port,connection.info.dbname)!=(target.host,target.port,target.database):
        raise OperatorRefusal('036 locked client endpoint differs')
    with connection.cursor() as cursor:
        cursor.execute('SELECT mlb036_private.describe_target()')
        identity=cursor.fetchone()[0]
        db,address,port,started,version,readonly,isolation=(identity[k] for k in ('database','address','port','started','version','readonly','isolation'))
        started=aware(started)
        if ((db,address,port,started)!=(target.database,target.server_address,target.server_port,aware(target.postmaster_started_at))
            or int(version)//10000!=16 or readonly!='off' or isolation!='serializable'):
            raise OperatorRefusal('036 locked target/isolation differs')
        if tuple((v,n,h.strip()) for v,n,h in identity['migrations'])!=expected_migrations:
            raise OperatorRefusal('036 locked migration identities differ')
        if target.identity_kind=='isolated':
            if identity['system_identifier']!=target.system_identifier:raise OperatorRefusal('036 locked system identity differs')
        # operator_state independently checks current protected catalog/authority.
        cursor.execute('SELECT mlb036_private.operator_state()')
        observed=cursor.fetchone()[0]
        if observed['state']['profile']!=expected_profile:
            raise OperatorRefusal('036 registered candidate profile differs')
    return dict(target=target.artifact(),profile=expected_profile)


@dataclass(frozen=True)
class KnowledgeReceipt:
    receipt_id: int
    body_sha256: str
    available_at: datetime
    profile: str
    endpoint: tuple

    def __post_init__(self):
        if (type(self.receipt_id) is not int or not 0 < self.receipt_id < 2**63
            or type(self.body_sha256) is not str or not re.fullmatch('[0-9a-f]{64}',self.body_sha256)
            or type(self.profile) is not str or not re.fullmatch('[0-9a-f]{64}',self.profile)
            or not isinstance(self.available_at,datetime) or self.available_at.tzinfo is None
            or self.available_at.utcoffset() is None or type(self.endpoint) is not tuple or len(self.endpoint)!=3
            or self.endpoint[0] != '127.0.0.1'
            or type(self.endpoint[1]) is not int or not 0 < self.endpoint[1] < 65536
            or type(self.endpoint[2]) is not str or not self.endpoint[2]):
            raise OperatorRefusal('Strict committed knowledge receipt required')


def issue_knowledge(*, connection_factory):
    """Explicit Y write transaction only; never a read-only side effect or auto-retry."""
    expected_profile=profile_fingerprint()
    connection = connection_factory()
    committing = False
    try:
        connection.set_session(readonly=False,isolation_level='READ COMMITTED',autocommit=False)
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL lock_timeout='1500ms'")
            cursor.execute("SET LOCAL statement_timeout='15000ms'")
            cursor.execute('SELECT mlb036_private.issue_knowledge()')
            row = cursor.fetchone()[0]
            if row.get('schema_capability_profile')!=expected_profile:
                raise OperatorRefusal('036 issuance source/profile differs')
        committing = True
        connection.commit()
        committing = False
        return KnowledgeReceipt(row['receipt_id'],row['receipt_body_sha256'],aware(row['available_at']),
                                row['schema_capability_profile'],
                                (connection.info.host,connection.info.port,connection.info.dbname))
    except Exception:
        try:connection.rollback()
        except Exception:raise OperatorRefusal('UNKNOWN issuance outcome; inspection only, no retry') from None
        if committing:raise OperatorRefusal('UNKNOWN issuance acknowledgement; inspect committed receipt, no retry') from None
        raise
    finally:connection.close()


def inspect_knowledge(*, connection_factory):
    """Read-only Y acknowledgement inspection; absent evidence is not rollback."""
    expected_profile=profile_fingerprint();c=connection_factory()
    try:
        c.set_session(readonly=True,isolation_level='READ COMMITTED',autocommit=False)
        with c.cursor() as cursor:
            cursor.execute("SET LOCAL lock_timeout='1500ms'")
            cursor.execute("SET LOCAL statement_timeout='15000ms'")
            cursor.execute('SELECT mlb036_private.inspect_knowledge()')
            result=cursor.fetchone()[0]
        if result.get('status')=='INDETERMINATE_NO_CURRENT_COMMITTED_RECEIPT':
            return result
        if result.get('status')!='CURRENT_COMMITTED_RECEIPT' or result.get('receipt',{}).get('schema_capability_profile')!=expected_profile:
            raise OperatorRefusal('036 inspected receipt/profile differs')
        row=result['receipt']
        return KnowledgeReceipt(row['receipt_id'],row['receipt_body_sha256'],aware(row['available_at']),row['schema_capability_profile'],
            (c.info.host,c.info.port,c.info.dbname))
    finally:
        try:c.rollback()
        finally:c.close()


def validate_knowledge(cursor, receipt, *, cutoff_time, readonly=True):
    if not isinstance(receipt,KnowledgeReceipt) or type(receipt.receipt_id) is not int or receipt.receipt_id<=0:
        raise OperatorRefusal('Typed receipt locator required')
    if (not isinstance(cutoff_time,datetime) or cutoff_time.tzinfo is None
        or cutoff_time.utcoffset() is None or receipt.available_at>cutoff_time):
        raise OperatorRefusal('036 unavailable at cutoff')
    endpoint = (cursor.connection.info.host,cursor.connection.info.port,cursor.connection.info.dbname)
    if endpoint != receipt.endpoint or receipt.profile != profile_fingerprint():
        raise OperatorRefusal('036 receipt client endpoint/profile differs')
    cursor.execute('SELECT mlb036_private.validate_knowledge(%s,%s,%s)',(receipt.receipt_id,cutoff_time,readonly))
    result = cursor.fetchone()[0]
    if result['receipt']['receipt_body_sha256'] != receipt.body_sha256:
        raise OperatorRefusal('036 receipt bytes changed')
    return result


@dataclass(frozen=True)
class CertifiedReader:
    """Explicit036 data interface. No ambient factory, v2 fallback or caller SQL."""
    connection_factory: object
    receipt: KnowledgeReceipt
    cutoff_time: datetime

    def __post_init__(self):
        if not callable(self.connection_factory) or not isinstance(self.receipt,KnowledgeReceipt):
            raise OperatorRefusal('Explicit connection factory and committed receipt required')
        if (not isinstance(self.cutoff_time,datetime) or self.cutoff_time.tzinfo is None
            or self.cutoff_time.utcoffset() is None):
            raise OperatorRefusal('Aware fixed cutoff required')

    def rows(self,purpose,**params):
        if self.receipt.profile!=profile_fingerprint() or self.receipt.available_at>self.cutoff_time:
            raise OperatorRefusal('036 reader source/profile/availability differs')
        c=self.connection_factory()
        try:
            if (c.info.host,c.info.port,c.info.dbname)!=self.receipt.endpoint:
                raise OperatorRefusal('036 reader client endpoint differs')
            c.set_session(readonly=True,isolation_level='READ COMMITTED',autocommit=False)
            with c.cursor() as cursor:
                cursor.execute("SET LOCAL lock_timeout='1500ms'")
                cursor.execute("SET LOCAL statement_timeout='15000ms'")
                cursor.execute('SELECT mlb036_private.certified_data(%s,%s,%s,%s::jsonb)',
                    (self.receipt.receipt_id,self.cutoff_time,purpose,json.dumps(params,allow_nan=False)))
                packet=cursor.fetchone()[0]
            if (type(packet) is not dict or set(packet)!= {'receipt_id','receipt_body_sha256','cutoff_time','state_fingerprint','rows','certification'}
                or packet.get('receipt_body_sha256')!=self.receipt.body_sha256
                or type(packet.get('receipt_id')) is not int
                or type(packet.get('rows')) is not list or any(type(row) is not dict for row in packet['rows'])
                or type(packet.get('state_fingerprint')) is not str or not re.fullmatch('[0-9a-f]{64}',packet['state_fingerprint'])
                or packet.get('certification')!='MLB036_CERTIFIED' or packet['receipt_id']!=self.receipt.receipt_id
                or aware(packet['cutoff_time'])!=self.cutoff_time):
                raise OperatorRefusal('036 certified result identity differs')
            return tuple(packet['rows'])
        finally:
            try:c.rollback()
            finally:c.close()

    def _write(self, operation, params):
        """Only typed036 lifecycle calls; this is not an arbitrary SQL connection."""
        statements={
            'reserve': 'SELECT mlb036_private.reserve_run(%s,%s,%s::jsonb)',
            'finish': 'SELECT mlb036_private.finish_run(%s,%s,%s,%s,%s,%s::jsonb,%s)',
            'prediction': 'SELECT mlb036_private.insert_prediction(%s,%s,%s::jsonb)',
        }
        if operation not in statements or self.receipt.profile!=profile_fingerprint():
            raise OperatorRefusal('036 typed lifecycle/profile required')
        c=self.connection_factory();committing=False
        try:
            if (c.info.host,c.info.port,c.info.dbname)!=self.receipt.endpoint:
                raise OperatorRefusal('036 lifecycle endpoint differs')
            c.set_session(readonly=False,isolation_level='READ COMMITTED',autocommit=False)
            with c.cursor() as cursor:
                cursor.execute("SET LOCAL lock_timeout='1500ms'")
                cursor.execute("SET LOCAL statement_timeout='15000ms'")
                if operation!='finish':
                    cursor.execute('SELECT mlb036_private.validate_knowledge(%s,%s,false)',(self.receipt.receipt_id,self.cutoff_time))
                    validated=cursor.fetchone()
                    if (validated is None or type(validated[0]) is not dict
                        or validated[0].get('receipt',{}).get('receipt_body_sha256')!=self.receipt.body_sha256):
                        raise OperatorRefusal('036 lifecycle receipt bytes differ')
                cursor.execute(statements[operation],params)
                row=cursor.fetchone()
                if row is None:raise OperatorRefusal('036 lifecycle returned no result')
            committing=True;c.commit();committing=False
            return row[0]
        except Exception:
            try:c.rollback()
            except Exception:raise OperatorRefusal('UNKNOWN lifecycle outcome; inspection only, no retry') from None
            if committing:raise OperatorRefusal('UNKNOWN lifecycle acknowledgement; inspection only, no retry') from None
            raise
        finally:c.close()

    def reserve_run(self, *, target_date, model_version, feature_schema_version, model_artifact_sha256,
                    model_training_cutoff, run_type='official'):
        if type(target_date) is not date:
            raise OperatorRefusal('Exact run date required')
        if (type(model_version) is not str or not 1<=len(model_version.strip())<=100
            or type(feature_schema_version) is not str or not 1<=len(feature_schema_version.strip())<=50
            or type(model_artifact_sha256) is not str or not re.fullmatch('[0-9a-f]{64}',model_artifact_sha256)
            or run_type not in ('official','preview')):
            raise OperatorRefusal('Exact bounded run metadata required')
        if model_training_cutoff is not None:
            if (not isinstance(model_training_cutoff,datetime) or model_training_cutoff.utcoffset() is None
                or model_training_cutoff>self.cutoff_time):raise OperatorRefusal('Aware prospective training cutoff required')
        request=dict(target_date=target_date.isoformat(),run_type=run_type,model_version=model_version.strip(),
            feature_schema_version=feature_schema_version.strip(),model_artifact_sha256=model_artifact_sha256,
            model_training_cutoff=None if model_training_cutoff is None else model_training_cutoff.isoformat())
        return self._write('reserve',(self.receipt.receipt_id,self.cutoff_time,json.dumps(request,allow_nan=False)))

    def finish_run(self, *, run_id, outcome, games_received, predictions_created, games_skipped, error_message=None):
        if type(run_id) is not int or run_id<=0 or outcome not in ('completed','failed'):
            raise OperatorRefusal('Typed run completion required')
        counts=dict(games_received=games_received,predictions_created=predictions_created,games_skipped=games_skipped)
        if any(type(v) is not int or v<0 for v in counts.values()):raise OperatorRefusal('Exact nonnegative run counts required')
        if predictions_created+games_skipped>games_received:
            raise OperatorRefusal('Inconsistent run counts')
        if (outcome=='failed' and (type(error_message) is not str or not 1<=len(error_message.strip())<=1000)
            or outcome=='completed' and error_message is not None):raise OperatorRefusal('Exact bounded completion reason required')
        return self._write('finish',(self.receipt.receipt_id,self.cutoff_time,self.receipt.body_sha256,run_id,outcome,json.dumps(counts,allow_nan=False),error_message))

    def insert_prediction(self, prediction):
        from sportsmodel.models.moneyline_prediction import MoneylineGamePrediction
        if not isinstance(prediction,MoneylineGamePrediction) or prediction.prediction_time!=self.cutoff_time:
            raise OperatorRefusal('Typed prediction at original cutoff required')
        request=asdict(prediction)
        for key,value in request.items():
            if isinstance(value,datetime):request[key]=value.isoformat()
            elif isinstance(value,Decimal):request[key]=str(value)
        return self._write('prediction',(self.receipt.receipt_id,self.cutoff_time,json.dumps(request,allow_nan=False)))

    def game(self,game_id):
        from sportsmodel.models.baseball_game import BaseballGame
        rows=self.rows('game',id=game_id)
        if len(rows)>1:raise OperatorRefusal('036 ambiguous game')
        return None if not rows else BaseballGame(game_id=rows[0]['game_id'],game_start_time=aware(rows[0]['game_date']),
            home_team_id=rows[0]['home_team_id'],away_team_id=rows[0]['away_team_id'])

    def next_game(self):
        from sportsmodel.models.baseball_game import BaseballGame
        rows=self.rows('next_game')
        if len(rows)>1:raise OperatorRefusal('036 ambiguous next game')
        return None if not rows else BaseballGame(game_id=rows[0]['game_id'],game_start_time=aware(rows[0]['game_date']),
            home_team_id=rows[0]['home_team_id'],away_team_id=rows[0]['away_team_id'])

    def team_history(self,team_id,limit):
        from dataclasses import fields
        from sportsmodel.models.team_game_statistics import TeamGameStatistics
        from sportsmodel.models.historical_team_game import HistoricalTeamGame
        names={f.name for f in fields(TeamGameStatistics)}
        result=[]
        for row in self.rows('team_stats',id=team_id,limit=limit):
            stats=TeamGameStatistics(**{k:v for k,v in row['statistics'].items() if k in names})
            result.append(HistoricalTeamGame(game_id=row['game_id'],game_start_time=aware(row['game_date']),team_id=row['team_id'],
                opponent_team_id=row['opponent_team_id'],is_home=row['is_home'],statistics=stats))
        return tuple(result)

    def pitching_history(self,identifier,*,starter,limit=50):
        from dataclasses import fields
        from sportsmodel.models.player_game_pitching_statistics import PlayerGamePitchingStatistics,PitchingDecision
        from sportsmodel.models.historical_pitcher_start import HistoricalPitcherStart
        from sportsmodel.models.historical_bullpen_appearance import HistoricalBullpenAppearance
        names={f.name for f in fields(PlayerGamePitchingStatistics)}
        params=dict(id=identifier)
        if starter:params['limit']=limit
        result=[]
        for row in self.rows('starter_stats' if starter else 'bullpen_stats',**params):
            values={k:v for k,v in row['statistics'].items() if k in names}
            if values.get('decision') is not None:values['decision']=PitchingDecision(values['decision'])
            stats=PlayerGamePitchingStatistics(**values)
            model=HistoricalPitcherStart if starter else HistoricalBullpenAppearance
            result.append(model(game_id=row['game_id'],game_start_time=aware(row['game_date']),team_id=row['team_id'],
                opponent_team_id=row['opponent_team_id'],is_home=row['is_home'],statistics=stats))
        return tuple(result)
