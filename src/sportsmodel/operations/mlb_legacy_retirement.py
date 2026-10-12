"""Offline-evidence-bound legacy ACTIVATE only. No providers or ambient secrets."""
from hashlib import sha256
from io import BytesIO
import re
import zipfile
from sportsmodel.database.mlb_retirement_guard import (
    OperatorRefusal,aware,positive,strict_json,canonical_json,digest,verify_target,
)
from sportsmodel.database.mlb_retirement_repository import profile_fingerprint,load_identity_state
from sportsmodel.ingest.mlb_game_policy import extract_schedule_games,confirmed_championship_game
from sportsmodel.operations.mlb_identity_disposition import current_commit

FORMAT='MLB_LEGACY_RETIREMENT_EXECUTABLE_V1'
CATEGORIES=('LEGACY_MARKET_DUPLICATE_WITHOUT_OBSERVATION_PROVENANCE','IDENTITY_ONLY_DUPLICATE')
KEYS={'format','version','domain','action','category','policy_version','subject_game_id','survivor_game_id',
      'game_pk','target_date','expected_start','subject_start','reason','evidence_reference','evidence_sha256',
      'mlb_payload_entry','mlb_payload_sha256','operator_identity','tool_identity','implementation_commit',
      'duplicate_proof_approved','publication_attribution_clear'}


def validate_request(raw,evidence_bytes):
    if len(raw)>128_000 or len(evidence_bytes)>10_000_000:raise OperatorRefusal('Bounded evidence required')
    request=strict_json(raw)
    if not isinstance(request,dict) or set(request)!=KEYS:raise OperatorRefusal('Exact executable request required')
    if request['format']!=FORMAT or type(request['version']) is not int or request['version']!=1:
        raise OperatorRefusal('Wrong legacy executable version; design/old approvals refuse')
    if (request['domain']!='MLB' or request['action']!='ACTIVATE' or request['category'] not in CATEGORIES
            or request['policy_version']!='1.0.0' or request['duplicate_proof_approved'] is not True
            or request['publication_attribution_clear'] is not True):raise OperatorRefusal('Affirmative reviewed legacy activation required')
    for key in ('subject_game_id','survivor_game_id','game_pk'):positive(request[key])
    if request['subject_game_id']==request['survivor_game_id']:raise OperatorRefusal('Distinct pair required')
    if request['implementation_commit']!=current_commit():raise OperatorRefusal('Implementation base differs')
    for key in ('reason','evidence_reference','operator_identity','tool_identity'):
        if not isinstance(request[key],str) or not 1<=len(request[key].strip())<=1000:raise OperatorRefusal('Bounded audit fields required')
    for key in ('evidence_sha256','mlb_payload_sha256'):
        if not isinstance(request[key],str) or not re.fullmatch('[0-9a-f]{64}',request[key]):raise OperatorRefusal('Exact hash required')
    if sha256(evidence_bytes).hexdigest()!=request['evidence_sha256']:raise OperatorRefusal('Evidence bytes differ')
    name=request['mlb_payload_entry']
    if not isinstance(name,str) or not re.fullmatch(r'[A-Za-z0-9_.-]+\.json',name):raise OperatorRefusal('One safe raw entry required')
    with zipfile.ZipFile(BytesIO(evidence_bytes)) as archive:
        if (len(archive.namelist())>100 or len(set(archive.namelist()))!=len(archive.namelist())
                or any(i.file_size>2_000_000 for i in archive.infolist())
                or sum(i.file_size for i in archive.infolist())>20_000_000 or archive.testzip() is not None):
            raise OperatorRefusal('Invalid bounded evidence inventory')
        payload=archive.read(name)
    if sha256(payload).hexdigest()!=request['mlb_payload_sha256']:raise OperatorRefusal('Official raw bytes differ')
    from datetime import date
    day=date.fromisoformat(request['target_date'])
    if day.isoformat()!=request['target_date']:raise OperatorRefusal('Canonical date required')
    games=extract_schedule_games(strict_json(payload),expected_date=day)
    selected=[g for g in games if g.get('gamePk')==request['game_pk']]
    if len(selected)!=1:raise OperatorRefusal('Exact authoritative event required')
    game=selected[0]
    if not confirmed_championship_game(game) or game['status'].get('detailedState')!='Final':
        raise OperatorRefusal('Final confirmed played event required')
    home=game['teams']['home']['team'];away=game['teams']['away']['team']
    oriented=[g for g in games if g['teams']['home']['team']['id']==home['id'] and g['teams']['away']['team']['id']==away['id']]
    if len(oriented)!=1 or game.get('doubleHeader')!='N' or game.get('gameNumber')!=1 or game.get('ifNecessary')!='N':
        raise OperatorRefusal('Unambiguous single nonconditional event required')
    if game['status'].get('startTimeTBD') is not False or game.get('officialDate')!=day.isoformat() or aware(game['gameDate'])!=aware(request['expected_start']):
        raise OperatorRefusal('Official date/start differs')
    if any('reschedul' in k.lower() or 'resum' in k.lower() for k in game):raise OperatorRefusal('Unresolved reschedule metadata')
    proof=dict(version=1,duplicate_proof_approved=True,publication_attribution_clear=True,gamePk=game['gamePk'],
        officialDate=game['officialDate'],gameDate=game['gameDate'],home_mlb_id=home['id'],away_mlb_id=away['id'],
        home_name=home['name'],away_name=away['name'],home_score=game['teams']['home']['score'],away_score=game['teams']['away']['score'],
        gameType=game['gameType'],status='Final',doubleHeader='N',gameNumber=1,ifNecessary='N',startTimeTBD=False,
        raw_payload_sha256=request['mlb_payload_sha256'],subject_start=aware(request['subject_start']).isoformat())
    case={k:request[k] for k in ('domain','subject_game_id','survivor_game_id','game_pk','category','policy_version',
          'evidence_reference','evidence_sha256','operator_identity','tool_identity','implementation_commit')}
    case.update(proof=proof,implementation_sha256=profile_fingerprint(),approved_preview_sha256='0'*64)
    return request,case


def preview_retirement(*,request_bytes,evidence_bytes,target,connection_factory):
    request,case=validate_request(request_bytes,evidence_bytes)
    connection=connection_factory()
    try:
        connection.set_session(readonly=True,isolation_level='REPEATABLE READ')
        guard=verify_target(connection,target,readonly=True)
        with connection.cursor() as cursor:
            cursor.execute('SELECT mlb_retirement_validate(jsonb_populate_record(NULL::mlb_legacy_identity_retirements,%s::jsonb),false)',(canonical_json(case),))
            state=load_identity_state(cursor)
            cursor.execute('SELECT mlb_retirement_pair_fingerprint(%s,%s)',(case['subject_game_id'],case['survivor_game_id']))
            pair=cursor.fetchone()[0]
        body=dict(format='MLB_LEGACY_RETIREMENT_PREVIEW_V1',version=1,request=request,case=case,
                  guard=guard,state=state,pair_fingerprint=pair,profile=profile_fingerprint())
        return dict(body,preview_sha256=digest(body))
    finally:connection.rollback();connection.close()


def execute_retirement(*,request_bytes,evidence_bytes,preview,approved_preview_sha256,target,connection_factory,acknowledge_writes=False):
    request,case=validate_request(request_bytes,evidence_bytes)
    if acknowledge_writes is not True or not isinstance(preview,dict):raise OperatorRefusal('Separate exact write authority required')
    body={k:v for k,v in preview.items() if k!='preview_sha256'}
    if (set(preview)!={'format','version','request','case','guard','state','pair_fingerprint','profile','preview_sha256'}
            or preview['format']!='MLB_LEGACY_RETIREMENT_PREVIEW_V1' or type(preview['version']) is not int or preview['version']!=1
            or digest(body)!=approved_preview_sha256 or preview['preview_sha256']!=approved_preview_sha256
            or preview['request']!=request or preview['case']!=case or preview['profile']!=profile_fingerprint()):
        raise OperatorRefusal('Exact evidence/code/preview approval differs')
    connection=connection_factory();committing=False
    try:
        connection.set_session(readonly=False,isolation_level='SERIALIZABLE')
        with connection.cursor() as cursor:
            cursor.execute('SELECT mlb_identity_gate(true)')
            guard=verify_target(connection,target,readonly=False)
            if guard!=preview['guard']:raise OperatorRefusal('Target/schema changed')
            case['approved_preview_sha256']=approved_preview_sha256
            activation=dict(case=case,expected_pair_sha256=preview['pair_fingerprint'],expected_state_sha256=preview['state']['fingerprint'])
            cursor.execute('SELECT mlb_retirement_activate(%s::jsonb)',(canonical_json(activation),))
            receipt=cursor.fetchone()[0]
        committing=True;connection.commit();committing=False
        return receipt
    except Exception:
        try:connection.rollback()
        except Exception:raise OperatorRefusal('UNKNOWN rollback/commit; receipt inspection only, no retry') from None
        if committing:raise OperatorRefusal('UNKNOWN commit acknowledgment; inspect receipt, no retry') from None
        raise
    finally:connection.close()


def inspect_receipt(*,approved_preview_sha256,target,connection_factory):
    if not isinstance(approved_preview_sha256,str) or not re.fullmatch('[0-9a-f]{64}',approved_preview_sha256):raise OperatorRefusal('Exact approval hash required')
    connection=connection_factory()
    try:
        connection.set_session(readonly=True,isolation_level='REPEATABLE READ');verify_target(connection,target,readonly=True)
        with connection.cursor() as cursor:
            cursor.execute('SELECT to_jsonb(r),e.receipt FROM mlb_legacy_identity_retirements r JOIN mlb_legacy_identity_retirement_events e USING(retirement_id) WHERE r.approved_preview_sha256=%s',(approved_preview_sha256,))
            row=cursor.fetchone()
            if row is None:return dict(status='NO_COMMITTED_RECEIPT_VISIBLE',retry_authorized=False)
            case,receipt=row
            cursor.execute('SELECT mlb_retirement_fingerprint(%s),mlb_retirement_pair_fingerprint(%s,%s)',(case['implementation_sha256'],case['subject_game_id'],case['survivor_game_id']))
            state,pair=cursor.fetchone()
        return dict(status='COMMITTED_RECEIPT_FOUND',receipt=receipt,current_postconditions_match=state==receipt['fingerprint'] and pair==receipt['pair_fingerprint'],
                    current_code_match=case['implementation_sha256']==profile_fingerprint(),retry_authorized=False)
    finally:connection.rollback();connection.close()
