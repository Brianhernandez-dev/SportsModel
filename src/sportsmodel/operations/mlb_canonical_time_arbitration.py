"""Exact reviewed case only; explicit offline evidence/target/approval, no CLI discovery."""
from datetime import date
from hashlib import sha256
from io import BytesIO
from email.utils import parsedate_to_datetime
import re
import zipfile

from sportsmodel.database.mlb_operator_guard import OperatorRefusal,aware,canonical_json,digest,strict_json
from sportsmodel.database.mlb_canonical_time_repository import OperatorTarget,profile_fingerprint,verify_target,verify_locked_target,migration_reference
from sportsmodel.database.mlb_operator_guard import native_process_proof,validate_native_proof
from sportsmodel.ingest.mlb_game_policy import extract_schedule_games,confirmed_championship_game,championship_game_type,MLB_CLUB_NAMES,MLB_CLUB_ALIASES
from sportsmodel.operations.mlb_identity_disposition import current_commit

FORMAT='MLB_CANONICAL_TIME_ARBITRATION_EXECUTABLE_V1'
ORIGIN_METADATA_ENTRY='origin_metadata.json'
SOURCE_CHAIN_ENTRY='source_chain.zip'
NATIVE_RETAINED_ORIGIN_SHA256='fa628ec01db3189fc79e5a7a7519b1d8f0456780e48458cb3bd15d4ac9b7fe00'
NATIVE_RETAINED_PAYLOAD_SHA256='f8a664f6cc3a0eaa640b5669cd490502f36edc9a0087c58219d462a8d606b23b'
NATIVE_RETAINED_CHAIN_SHA256='e71cc17ee25dddf4c55a69a073192f0665cb66dbc9e5a67813bf871eba6b02e3'
ORIGIN_KEYS={'url','final_url','http_status','observed_utc','sha256','bytes','requests','anonymous','paid_Odds_API','server_date','content_type'}
KEYS={'format','version','domain','subject','survivor','game_pk','target_date','old_start','new_start',
      'evidence_sha256','payload_entry','payload_sha256','origin_attestation_sha256','operator_identity','tool_identity',
      'implementation_commit','profile','duplicate_proof_approved','publication_attribution_clear'}


def _exact_timestamp(value):
    if type(value) is not str or not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?(?:Z|[+-][0-9]{2}:[0-9]{2})',value):
        raise OperatorRefusal('Exact aware microsecond timestamp required; no truncation')
    return aware(value)


def _validate_schedule_record(game):
    """Validate every surrounding record, not only the chosen authoritative event."""
    modeled=championship_game_type(game)
    if type(game.get('gamePk')) is not int or game['gamePk']<=0 or game.get('officialDate')!='2026-07-12':
        raise OperatorRefusal('Malformed surrounding schedule identity/date')
    _exact_timestamp(game.get('gameDate'))
    if type(game.get('gameNumber')) is not int or game['gameNumber']<1:
        raise OperatorRefusal('Malformed surrounding schedule game number')
    status=game.get('status')
    if (type(status) is not dict or status.get('abstractGameState') not in ('Preview','Live','Final')
        or type(status.get('detailedState')) is not str or not status['detailedState'].strip()
        or (status['detailedState']=='Final' and status['abstractGameState']!='Final')
        or ('startTimeTBD' in status and type(status['startTimeTBD']) is not bool)):
        raise OperatorRefusal('Malformed or contradictory surrounding schedule status')
    teams=game.get('teams')
    if type(teams) is not dict:
        raise OperatorRefusal('Malformed surrounding schedule participants')
    identifiers=[]
    for side in ('home','away'):
        section=teams.get(side)
        team=section.get('team') if type(section) is dict else None
        if type(team) is not dict or type(team.get('id')) is not int or team['id']<=0:
            raise OperatorRefusal('Malformed surrounding schedule participant identity')
        if modeled and (team['id'] not in MLB_CLUB_NAMES or team.get('name') not in
            ({MLB_CLUB_NAMES[team['id']]}|MLB_CLUB_ALIASES.get(team['id'],frozenset()))):
            raise OperatorRefusal('Malformed surrounding schedule participant name')
        if not modeled and (type(team.get('name')) is not str or not 1<=len(team['name'].strip())<=200):
            raise OperatorRefusal('Malformed deliberately excluded schedule participant name')
        if ('score' in section or status['abstractGameState']=='Final') and (type(section.get('score')) is not int or section['score']<0):
            raise OperatorRefusal('Malformed surrounding schedule score')
        identifiers.append(team['id'])
    if identifiers[0]==identifiers[1]:
        raise OperatorRefusal('Surrounding schedule participants must differ')


def _bounded_archive(archive):
    if (len(archive.namelist())>100 or len(set(archive.namelist()))!=len(archive.namelist())
        or any(info.file_size>2_000_000 for info in archive.infolist())
        or sum(info.file_size for info in archive.infolist())>20_000_000 or archive.testzip() is not None):
        raise OperatorRefusal('Invalid bounded evidence archive')


def _origin_provenance(archive,payload,request,target):
    """Bind retained bytes/lineage, not cryptographic or fresh provider authenticity."""
    if ORIGIN_METADATA_ENTRY not in archive.namelist() or SOURCE_CHAIN_ENTRY not in archive.namelist():
        raise OperatorRefusal('Missing origin metadata/source-chain bytes')
    raw=archive.read(ORIGIN_METADATA_ENTRY)
    if len(raw)>8192 or sha256(raw).hexdigest()!=request['origin_attestation_sha256']:
        raise OperatorRefusal('Origin metadata bytes/hash differ')
    metadata=strict_json(raw)
    keys=ORIGIN_KEYS|({'synthetic'} if target.identity_kind=='isolated' else set())
    endpoint='https://statsapi.mlb.com/api/v1/schedule?sportId=1&date=2026-07-12'
    if (type(metadata) is not dict or set(metadata)!=keys
        or (target.identity_kind=='isolated' and metadata['synthetic'] is not True)
        or metadata.get('url')!=endpoint or metadata.get('final_url')!=endpoint
        or type(metadata.get('http_status')) is not int or metadata['http_status']!=200
        or type(metadata.get('bytes')) is not int or metadata['bytes']!=len(payload)
        or type(metadata.get('requests')) is not int or metadata['requests']!=1
        or metadata.get('anonymous') is not True or metadata.get('paid_Odds_API') is not False
        or type(metadata.get('sha256')) is not str or not re.fullmatch('[0-9A-Fa-f]{64}',metadata['sha256'])
        or metadata['sha256'].lower()!=request['payload_sha256']
        or type(metadata.get('content_type')) is not str or len(metadata['content_type'])>128
        or metadata['content_type'].split(';',1)[0].strip().lower()!='application/json'
        or type(metadata.get('server_date')) is not str or not 1<=len(metadata['server_date'])<=128):
        raise OperatorRefusal('Origin acquisition record differs from exact payload/endpoint/policy')
    observed=_exact_timestamp(metadata['observed_utc'])
    if observed<_exact_timestamp(request['new_start']):
        raise OperatorRefusal('Played evidence acquisition predates event')
    try:
        server_time=parsedate_to_datetime(metadata['server_date'])
        if server_time.tzinfo is None or server_time.utcoffset() is None:
            raise ValueError
    except (TypeError,ValueError,OverflowError):
        raise OperatorRefusal('Malformed origin server date') from None
    chain_bytes=archive.read(SOURCE_CHAIN_ENTRY)
    if target.identity_kind=='native' and (
        sha256(raw).hexdigest()!=NATIVE_RETAINED_ORIGIN_SHA256
        or sha256(payload).hexdigest()!=NATIVE_RETAINED_PAYLOAD_SHA256
        or sha256(chain_bytes).hexdigest()!=NATIVE_RETAINED_CHAIN_SHA256):
        raise OperatorRefusal('Native evidence must retain the reviewed acquisition chain; fresh authenticity/approval is a separate gate')
    with zipfile.ZipFile(BytesIO(chain_bytes)) as chain:
        _bounded_archive(chain)
        if 'REVIEW_MANIFEST.md' not in chain.namelist():
            raise OperatorRefusal('Source chain lacks its byte inventory')
        manifest=chain.read('REVIEW_MANIFEST.md')
        declarations=re.findall(r'^\|\s*([^|]+?)\s*\|\s*([0-9]+)\s*\|\s*([0-9A-Fa-f]{64})\s*\|\s*$',manifest.decode('utf-8'),re.M)
        names=[name.strip() for name,_,_ in declarations]
        if len(names)!=len(set(names)) or set(chain.namelist())!=set(names)|{'REVIEW_MANIFEST.md'}:
            raise OperatorRefusal('Source-chain inventory incomplete or duplicate')
        payload_entries=[];metadata_entries=[]
        for name,size,claimed in declarations:
            name=name.strip()
            member=chain.read(name)
            if len(member)!=int(size) or sha256(member).hexdigest()!=claimed.lower():
                raise OperatorRefusal('Source-chain declared bytes/hash differ')
            if member==payload:payload_entries.append(name)
            if member==raw:metadata_entries.append(name)
        if len(payload_entries)!=1 or len(metadata_entries)!=1:
            raise OperatorRefusal('Source-chain payload/origin bytes are absent or ambiguous')
    return dict(metadata=metadata,metadata_utf8=raw.decode('utf-8'),metadata_raw_sha256=sha256(raw).hexdigest(),
        chain_sha256=sha256(chain_bytes).hexdigest(),chain_manifest_sha256=sha256(manifest).hexdigest(),
        chain_entries=dict(payload=payload_entries[0],metadata=metadata_entries[0]))


def validate_request(raw,evidence_bytes,target):
    if not isinstance(target,OperatorTarget) or type(raw) is not bytes or type(evidence_bytes) is not bytes:
        raise OperatorRefusal('Explicit target/raw request/evidence bytes required')
    if len(raw)>128_000 or len(evidence_bytes)>10_000_000:
        raise OperatorRefusal('Bounded request/evidence required')
    request=strict_json(raw)
    if type(request) is not dict or set(request)!=KEYS:
        raise OperatorRefusal('Exact036 request schema required')
    if (request['format']!=FORMAT or type(request['version']) is not int or request['version']!=1
        or request['domain']!='MLB' or request['subject']!=584 or request['survivor']!=26
        or type(request['subject']) is not int or type(request['survivor']) is not int
        or request['target_date']!='2026-07-12'
        or _exact_timestamp(request['old_start']).isoformat()!='2026-07-12T17:41:00+00:00'
        or _exact_timestamp(request['new_start']).isoformat()!='2026-07-12T17:40:00+00:00'
        or request['duplicate_proof_approved'] is not True or request['publication_attribution_clear'] is not True):
        raise OperatorRefusal('Fixed reviewed036 case and affirmative proof only')
    expected_pk=823842 if target.identity_kind=='native' else 900584
    if type(request['game_pk']) is not int or request['game_pk']!=expected_pk:
        raise OperatorRefusal('Fixed native or isolated synthetic gamePk required')
    if target.identity_kind=='isolated' and not re.fullmatch(r'sportsmodel_test_arbitration210_[0-9]+',target.database):
        raise OperatorRefusal('Synthetic equivalent restricted to isolated profile')
    if request['implementation_commit']!=current_commit() or request['profile']!=profile_fingerprint():
        raise OperatorRefusal('Current exact implementation identity required')
    for key in('evidence_sha256','payload_sha256','origin_attestation_sha256','profile'):
        if type(request[key]) is not str or not re.fullmatch('[0-9a-f]{64}',request[key]):
            raise OperatorRefusal('Exact bound audit hash required')
    for key in('operator_identity','tool_identity'):
        if type(request[key]) is not str or not 1<=len(request[key].strip())<=1000:
            raise OperatorRefusal('Explicit bounded operator identity required')
    if sha256(evidence_bytes).hexdigest()!=request['evidence_sha256']:
        raise OperatorRefusal('Evidence bytes differ')
    entry=request['payload_entry']
    if type(entry) is not str or not re.fullmatch(r'[A-Za-z0-9_.-]+\.json',entry):
        raise OperatorRefusal('Safe single raw payload name required')
    with zipfile.ZipFile(BytesIO(evidence_bytes)) as z:
        _bounded_archive(z)
        payload=z.read(entry)
        provenance=_origin_provenance(z,payload,request,target)
    if sha256(payload).hexdigest()!=request['payload_sha256']:
        raise OperatorRefusal('Exact raw payload hash differs')
    events=extract_schedule_games(strict_json(payload),expected_date=date(2026,7,12))
    for event in events:
        _validate_schedule_record(event)
    if len({event['gamePk'] for event in events})!=len(events):
        raise OperatorRefusal('Duplicate surrounding schedule event')
    selected=[g for g in events if g.get('gamePk')==request['game_pk']]
    if len(selected)!=1:raise OperatorRefusal('Unique official event required')
    g=selected[0]
    if (type(g.get('gamePk')) is not int or type(g.get('gameNumber')) is not int
        or not confirmed_championship_game(g) or g['gameType']!='R' or g['status'].get('detailedState')!='Final'
        or g['status'].get('abstractGameState')!='Final'
        or g['status'].get('startTimeTBD') is not False or g.get('ifNecessary')!='N'
        or g.get('doubleHeader')!='N' or g.get('gameNumber')!=1 or g.get('officialDate')!='2026-07-12'
        or aware(g['gameDate'])!=aware(request['new_start'])
        or any('reschedul' in k.lower() or 'resum' in k.lower() for k in g)):
        raise OperatorRefusal('Played final fixed single-event authoritative proof required')
    home=g['teams']['home']['team'];away=g['teams']['away']['team']
    if (type(home.get('id')) is not int or type(away.get('id')) is not int
        or (home['id'],home['name'],away['id'],away['name'])!=(146,'Miami Marlins',114,'Cleveland Guardians')):
        raise OperatorRefusal('Exact oriented fixed franchise identity required')
    for side in ('home','away'):
        score=g['teams'][side].get('score')
        if type(score) is not int or score<0:
            raise OperatorRefusal('Strict nonnegative authoritative score required')
    oriented=[v for v in events if v['teams']['home']['team']['id']==146 and v['teams']['away']['team']['id']==114]
    if len(oriented)!=1:raise OperatorRefusal('Ambiguous same-date event')
    if target.identity_kind=='native' and (g['teams']['home']['score'],g['teams']['away']['score'])!=(2,5):
        raise OperatorRefusal('Fixed native authoritative result required')
    proof=dict(version=1,duplicate_proof_approved=True,publication_attribution_clear=True,gamePk=g['gamePk'],
        officialDate=g['officialDate'],gameDate=g['gameDate'],home_mlb_id=146,away_mlb_id=114,
        home_name=home['name'],away_name=away['name'],home_score=g['teams']['home']['score'],away_score=g['teams']['away']['score'],
        gameType='R',status='Final',doubleHeader='N',gameNumber=1,ifNecessary='N',startTimeTBD=False,
        raw_payload_sha256=request['payload_sha256'],subject_start=request['new_start'])
    case=dict(domain='MLB',subject_game_id=584,survivor_game_id=26,game_pk=request['game_pk'],category='IDENTITY_ONLY_DUPLICATE',
        policy_version='1.0.0',evidence_reference=request['origin_attestation_sha256'],evidence_sha256=request['evidence_sha256'],
        operator_identity=request['operator_identity'],tool_identity=request['tool_identity'],implementation_commit=request['implementation_commit'],
        implementation_sha256=request['profile'],approved_preview_sha256='0'*64,proof=proof)
    db_request=dict(request_sha256=sha256(raw).hexdigest(),evidence_sha256=request['evidence_sha256'],retirement_case=case,
        profile=request['profile'],old_start=request['old_start'],new_start=request['new_start'],subject=584,survivor=26,game_pk=request['game_pk'],
        origin_provenance=provenance)
    return request,db_request


def preview_arbitration(*,request_bytes,evidence_bytes,target,connection_factory):
    request,db_request=validate_request(request_bytes,evidence_bytes,target)
    connection=connection_factory()
    try:
        connection.set_session(readonly=True,isolation_level='REPEATABLE READ',autocommit=False)
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL lock_timeout='1500ms'")
            cursor.execute("SET LOCAL statement_timeout='15000ms'")
        guard=verify_target(connection,target,readonly=True)
        with connection.cursor() as cursor:
            cursor.execute('SELECT mlb036_private.operator_state()');state=cursor.fetchone()[0]
        body=dict(format='MLB_CANONICAL_TIME_ARBITRATION_PREVIEW_V1',version=1,request=request,db_request=db_request,
                  request_sha256=sha256(request_bytes).hexdigest(),evidence_sha256=sha256(evidence_bytes).hexdigest(),guard=guard,state=state)
        return dict(body,preview_sha256=digest(body))
    finally:
        try:connection.rollback()
        finally:connection.close()


def execute_arbitration(*,request_bytes,evidence_bytes,target,connection_factory,preview,approved_preview_sha256,acknowledge_writes=False):
    request,db_request=validate_request(request_bytes,evidence_bytes,target)
    if acknowledge_writes is not True or type(preview) is not dict:
        raise OperatorRefusal('Separate exact write authorization required')
    keys={'format','version','request','db_request','request_sha256','evidence_sha256','guard','state','preview_sha256'}
    body={k:v for k,v in preview.items() if k!='preview_sha256'}
    if (set(preview)!=keys or preview['format']!='MLB_CANONICAL_TIME_ARBITRATION_PREVIEW_V1'
        or preview['version']!=1 or preview['request']!=request or preview['db_request']!=db_request
        or preview['request_sha256']!=sha256(request_bytes).hexdigest() or preview['evidence_sha256']!=sha256(evidence_bytes).hexdigest()
        or digest(body)!=approved_preview_sha256 or preview['preview_sha256']!=approved_preview_sha256):
        raise OperatorRefusal('Exact request/evidence/preview byte identity required')
    # Load file identities before X; no source/evidence filesystem reads under locks.
    expected_migrations=migration_reference();expected_profile=request['profile']
    c=connection_factory();committing=False
    try:
        if target.identity_kind=='native':
            validate_native_proof(native_process_proof(c.info.backend_pid),c.info.backend_pid)
        c.set_session(readonly=False,isolation_level='SERIALIZABLE',autocommit=False)
        with c.cursor() as cur:
            cur.execute("SET LOCAL lock_timeout='1500ms'")
            cur.execute("SET LOCAL statement_timeout='15000ms'")
            cur.execute('SELECT mlb036_private.acquire_exact_gate()')
            guard=verify_locked_target(c,target,expected_migrations=expected_migrations,expected_profile=expected_profile)
            if guard!=preview['guard']:raise OperatorRefusal('036 target/profile drift')
            cur.execute('SELECT mlb036_private.lock_exact()')
            cur.execute('SELECT mlb036_private.operator_state()');local=cur.fetchone()[0]
            probe=connection_factory()
            try:
                probe.set_session(readonly=True,isolation_level='READ COMMITTED',autocommit=False)
                if (probe.info.host,probe.info.port,probe.info.dbname)!=(c.info.host,c.info.port,c.info.dbname):
                    raise OperatorRefusal('036 fresh probe endpoint differs')
                with probe.cursor() as p:
                    p.execute("SET LOCAL lock_timeout='1500ms'")
                    p.execute("SET LOCAL statement_timeout='15000ms'")
                    # Must NOT acquire a second shared gate while X holds exclusive.
                    p.execute('SELECT mlb036_private.operator_state()');fresh=p.fetchone()[0]
            finally:
                try:probe.rollback()
                finally:probe.close()
            if local.get('operation') is not None:
                operation=local['operation']
                if (local!=fresh or operation.get('request_sha256')!=sha256(request_bytes).hexdigest()
                    or operation.get('approval_sha256')!=approved_preview_sha256
                    or operation.get('post_state_current') is not True):
                    raise OperatorRefusal('Applied operation request/approval/post-state mismatch; no replay')
                raise OperatorRefusal('ALREADY_APPLIED_REFUSAL')
            if local!=fresh or local!=preview['state']:
                raise OperatorRefusal('036 fresh/local/approved state drift')
            cur.execute('SELECT mlb036_private.correct_exact(%s::jsonb,%s::jsonb,%s)',
                        (canonical_json(db_request),canonical_json(local),approved_preview_sha256))
            receipt=cur.fetchone()[0]
            cur.execute('SET CONSTRAINTS ALL IMMEDIATE')
        committing=True;c.commit();committing=False
        return receipt
    except Exception:
        try:c.rollback()
        except Exception:raise OperatorRefusal('UNKNOWN correction outcome; inspection only, no retry') from None
        if committing:raise OperatorRefusal('UNKNOWN commit acknowledgement; inspect receipt, no retry') from None
        raise
    finally:c.close()


def inspect_arbitration(*, request_sha256, target, connection_factory):
    """Read-only committed operation inspection; an absent row is NOT rollback proof.

    In particular a disconnected/pending original backend may still commit later.
    This interface never retries correction or turns absent evidence into permission.
    """
    if type(request_sha256) is not str or not re.fullmatch('[0-9a-f]{64}',request_sha256):
        raise OperatorRefusal('Exact operation request hash required')
    c=connection_factory()
    try:
        c.set_session(readonly=True,isolation_level='REPEATABLE READ',autocommit=False)
        with c.cursor() as cursor:
            cursor.execute("SET LOCAL lock_timeout='1500ms'")
            cursor.execute("SET LOCAL statement_timeout='15000ms'")
        guard=verify_target(c,target,readonly=True)
        with c.cursor() as cursor:
            cursor.execute('SELECT mlb036_private.operator_state()');observed=cursor.fetchone()[0]
        operation=observed.get('operation')
        if operation is None:
            return dict(status='INDETERMINATE_NO_COMMITTED_RECEIPT',retry_authorized=False,
                        rollback_proven=False,guard=guard,label='RAW_FORENSIC',historically_certified=False)
        if operation.get('request_sha256')!=request_sha256 or operation.get('post_state_current') is not True:
            raise OperatorRefusal('Operation identity/post-state differs; no retry')
        return dict(status='COMMITTED_APPLIED',retry_authorized=False,operation=operation,guard=guard,
                    label='RAW_FORENSIC',historically_certified=False)
    finally:
        try:c.rollback()
        finally:c.close()
