"""Bounded, evidence-pinned MLB event disposition. No providers or redirection.

Production authority is never inferred from a design, preview or evidence hash.
Caller must separately approve the exact executable preview and optional anchor.
"""
from hashlib import sha256
from pathlib import Path
import re
import zipfile
import subprocess

from sportsmodel.database.mlb_operator_guard import (
    OperatorRefusal, aware, canonical_json, digest, positive, strict_json,
    verify_target, load_mlb_teams,
)
from sportsmodel.database.mlb_identity_disposition_repository import load_identity_state
from sportsmodel.ingest.mlb_game_policy import extract_schedule_games, confirmed_championship_game

FORMAT = 'MLB_IDENTITY_DISPOSITION_EXECUTABLE_V1'
VERSION = 1
ALLOWED_ACTIONS = ('ACTIVATE', 'REVOKE')
KEYS = {'format', 'version', 'domain', 'action', 'subject_game_id', 'survivor_game_id',
        'game_pk', 'target_date', 'expected_start', 'home_team_id', 'away_team_id',
        'reason', 'policy_version', 'evidence_reference', 'evidence_sha256',
        'mlb_payload_entry', 'mlb_payload_sha256', 'operator_identity', 'tool_identity',
        'implementation_commit', 'expected_sources', 'expected_observation_ids',
        'expected_snapshot_ids', 'allow_survivor_anchor'}
IDENTITY_FILES = [
    'operations/mlb_identity_disposition.py', 'database/mlb_identity_disposition_repository.py',
    'operations/mlb_identity_disposition_cli.py',
    'database/mlb_operator_guard.py', 'operations/mlb_reconcile.py', 'operations/mlb_history_check.py',
    'ingest/game_matching.py', 'ingest/mlb_schedule.py', 'ingest/mlb_stats.py', 'ingest/mlb_recovery.py',
    'database/mlb_recovery_repository.py', 'database/mlb_completeness_repository.py',
    'database/team_statistics_repository.py', 'database/pitcher_statistics_repository.py',
    'database/bullpen_statistics_repository.py', 'database/scheduled_execution_repository.py',
    'database/game_repository.py', 'database/boxscore_repository.py',
    'database/moneyline_prediction_repository.py', 'database/moneyline_market_evaluation_repository.py',
    'database/moneyline_paper_settlement_repository.py', 'predictions/moneyline_service.py',
    'ingest/odds_api.py',
    'ingest/boxscore_ingestion.py',
    'database/boxscore_status_repository.py','database/completed_game_repository.py',
    'database/repository.py','ingest/mlb_game_policy.py','ingest/team_identity.py',
    'orchestration/moneyline_daily.py','ingest/mlb_recovery_cli.py',
]


def current_commit():
    root=Path(__file__).resolve().parents[3]
    result=subprocess.run(['git','--no-optional-locks','-c','safe.directory='+root.as_posix(),
                           '-C',str(root),'rev-parse','HEAD'],capture_output=True,timeout=5)
    value=result.stdout.decode().strip()
    if result.returncode or not re.fullmatch('[0-9a-f]{40}',value):
        raise OperatorRefusal('Current implementation base commit could not be verified')
    return value


def fingerprint():
    root = Path(__file__).resolve().parents[1]
    files = {name: sha256((root / name).read_bytes()).hexdigest() for name in IDENTITY_FILES}
    migration = root.parents[1] / 'database/migrations/034_create_mlb_identity_dispositions.sql'
    files['migration034'] = sha256(migration.read_bytes()).hexdigest()
    files['current_base_commit'] = current_commit()
    return digest(files)


def _hash(value):
    if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{64}', value):
        raise OperatorRefusal('Exact lowercase SHA256 required')


def validate_request(raw, evidence_bytes):
    if len(raw) > 128_000 or len(evidence_bytes) > 10_000_000:
        raise OperatorRefusal('Identity evidence exceeds bounded input')
    request = strict_json(raw)
    if not isinstance(request, dict) or set(request) != KEYS:
        raise OperatorRefusal('Exact executable identity request fields required; DESIGN_ONLY refused')
    if request['format'] != FORMAT or type(request['version']) is not int or request['version'] != VERSION:
        raise OperatorRefusal('Wrong executable identity format')
    if request['domain'] != 'MLB' or request['action'] not in ALLOWED_ACTIONS or request['policy_version'] != '1.0.0':
        raise OperatorRefusal('Unsupported identity action/domain/policy')
    for key in ('subject_game_id', 'survivor_game_id', 'game_pk', 'home_team_id', 'away_team_id'):
        positive(request[key])
    if request['subject_game_id'] == request['survivor_game_id'] or request['home_team_id'] == request['away_team_id']:
        raise OperatorRefusal('Distinct positive oriented identities required')
    if type(request['allow_survivor_anchor']) is not bool:
        raise OperatorRefusal('Explicit anchor policy required')
    if request['action'] == 'REVOKE' and request['allow_survivor_anchor']:
        raise OperatorRefusal('Reversal cannot add an MLB anchor')
    for key in ('reason', 'evidence_reference', 'operator_identity', 'tool_identity'):
        if not isinstance(request[key], str) or not request[key].strip() or len(request[key]) > 1000:
            raise OperatorRefusal('Bounded audit identity/reason required')
    if not isinstance(request['implementation_commit'], str) or not re.fullmatch('[0-9a-f]{40}', request['implementation_commit']):
        raise OperatorRefusal('Reviewed base commit identity required')
    if request['implementation_commit']!=current_commit():
        raise OperatorRefusal('Requested/current implementation base commit differs')
    for key in ('evidence_sha256', 'mlb_payload_sha256'):
        _hash(request[key])
    if sha256(evidence_bytes).hexdigest() != request['evidence_sha256']:
        raise OperatorRefusal('Evidence package differs')
    for key in ('expected_observation_ids', 'expected_snapshot_ids'):
        values = request[key]
        if not isinstance(values, list) or not 1 <= len(values) <= 4000:
            raise OperatorRefusal('Bounded nonempty raw identity set required')
        if values != sorted(set(positive(v) for v in values)):
            raise OperatorRefusal('Raw identity set must be unique/sorted')
    sources = request['expected_sources']
    if not isinstance(sources, list) or not 1 <= len(sources) <= 16:
        raise OperatorRefusal('Exact bounded source-state list required')
    for source in sources:
        if not isinstance(source, dict) or set(source) != {'game_source_id', 'game_id', 'source_name', 'external_game_id'}:
            raise OperatorRefusal('Source fields differ')
        positive(source['game_source_id'])
        positive(source['game_id'])
        if source['game_id'] not in (request['subject_game_id'], request['survivor_game_id']):
            raise OperatorRefusal('Source scope differs')
        if source['source_name'] not in ('odds_api', 'mlb_stats') or not isinstance(source['external_game_id'], str) or not source['external_game_id']:
            raise OperatorRefusal('Source identity differs')
    if len({source['game_source_id'] for source in sources}) != len(sources):
        raise OperatorRefusal('Duplicate source row')
    entry = request['mlb_payload_entry']
    if not isinstance(entry, str) or not re.fullmatch(r'[A-Za-z0-9_.-]+\.json', entry):
        raise OperatorRefusal('One safe evidence entry required')
    from io import BytesIO
    with zipfile.ZipFile(BytesIO(evidence_bytes)) as archive:
        if (len(archive.namelist()) > 100 or len(set(archive.namelist())) != len(archive.namelist())
                or any(info.file_size > 2_000_000 for info in archive.infolist())
                or sum(info.file_size for info in archive.infolist()) > 20_000_000
                or archive.testzip() is not None):
            raise OperatorRefusal('Invalid evidence inventory')
        info = archive.getinfo(entry)
        if info.file_size > 2_000_000:
            raise OperatorRefusal('Raw MLB entry exceeds bound')
        payload_bytes = archive.read(entry)
    if sha256(payload_bytes).hexdigest() != request['mlb_payload_sha256']:
        raise OperatorRefusal('Raw MLB bytes differ')
    from datetime import date
    day = date.fromisoformat(request['target_date'])
    if day.isoformat() != request['target_date']:
        raise OperatorRefusal('Canonical ISO date required')
    games = extract_schedule_games(strict_json(payload_bytes), expected_date=day)
    if len(games) != 1 or games[0]['gamePk'] != request['game_pk'] or not confirmed_championship_game(games[0]):
        raise OperatorRefusal('Exact single confirmed real MLB event required')
    game = games[0]
    from zoneinfo import ZoneInfo
    if aware(request['expected_start']).astimezone(ZoneInfo('America/Los_Angeles')).date() != day:
        raise OperatorRefusal('Requested survivor is outside the approved Pacific date')
    if (aware(game['gameDate']) != aware(request['expected_start']) or game.get('doubleHeader') != 'N'
            or game.get('gameNumber') != 1 or game.get('officialDate') != day.isoformat()):
        raise OperatorRefusal('Unresolved start/date/doubleheader evidence')
    return request, game


def _rows(cursor, table, where, params):
    if not re.fullmatch('[a-z_]+', table):
        raise OperatorRefusal('Untrusted relation identifier')
    cursor.execute(f"SELECT to_jsonb(t)::text FROM public.{table} t WHERE {where} ORDER BY to_jsonb(t)::text LIMIT 5001", params)
    values = [row[0] for row in cursor.fetchall()]
    if len(values) > 5000:
        raise OperatorRefusal('Dependency closure exceeds bounded review scope')
    return values


def read_snapshot(cursor, request, game):
    ids = [request['subject_game_id'], request['survivor_game_id']]
    cursor.execute("""SELECT c.conname,ch.relname,array_agg(a.attname ORDER BY k.ord),pg_get_constraintdef(c.oid)
        FROM pg_constraint c JOIN pg_class ch ON ch.oid=c.conrelid
        CROSS JOIN LATERAL unnest(c.conkey) WITH ORDINALITY k(att,ord)
        JOIN pg_attribute a ON a.attrelid=ch.oid AND a.attnum=k.att
        WHERE c.contype='f' AND c.confrelid='public.games'::regclass
        GROUP BY c.oid,ch.relname ORDER BY ch.relname,c.conname""")
    inventory = cursor.fetchall()
    known = {'game_sources', 'historical_games', 'game_results', 'model_predictions',
             'moneyline_game_predictions', 'moneyline_paper_candidate_settlements', 'nfl_games',
             'odds_market_snapshots', 'odds_snapshots', 'player_game_pitching_statistics',
             'team_game_statistics', 'odds_provider_event_canonical_corrections',
             'game_identity_dispositions', 'mlb_game_identity_write_fences', 'nfl_odds_provider_event_mappings'}
    if any(row[1] not in known or (len(row[2]) != 1 and not (
            row[1]=='nfl_odds_provider_event_mappings'
            and row[2]==['game_id','canonical_home_team_id','canonical_away_team_id'])) for row in inventory):
        raise OperatorRefusal('Unexpected canonical dependency inventory')
    snapshot = {'foreign_keys': inventory, 'ledger': load_identity_state(cursor), 'tables': {}}
    tables = snapshot['tables']
    tables['games'] = _rows(cursor, 'games', 'game_id=ANY(%s)', (ids,))
    roots = [strict_json(row) for row in tables['games']]
    if len(roots) != 2:
        raise OperatorRefusal('Exact pair missing')
    for root in roots:
        if (root['home_team_id'], root['away_team_id']) != (request['home_team_id'], request['away_team_id']):
            raise OperatorRefusal('Canonical orientation differs')
    clubs = load_mlb_teams(cursor, (request['home_team_id'], request['away_team_id']))
    for side in ('home', 'away'):
        club = clubs[request[side+'_team_id']]
        provider = game['teams'][side]['team']
        if club['name'] != provider['name'] or club['mlb_team_id'] != provider['id']:
            raise OperatorRefusal('MLB canonical team identity differs')
    survivor = next(root for root in roots if root['game_id'] == request['survivor_game_id'])
    if aware(survivor['game_date']) != aware(request['expected_start']):
        raise OperatorRefusal('Survivor start differs from authoritative event')
    snapshot['teams'] = clubs
    tables['physical_competitors'] = _rows(cursor, 'games',
        "home_team_id=%s AND away_team_id=%s AND (game_date AT TIME ZONE 'America/Los_Angeles')::date=%s",
        (request['home_team_id'],request['away_team_id'],request['target_date']))
    for text in tables['physical_competitors']:
        competitor = strict_json(text)['game_id']
        if competitor not in ids:
            disposition = snapshot['ledger']['active'].get(competitor)
            if disposition is None or disposition['case']['survivor_game_id'] != request['survivor_game_id']:
                raise OperatorRefusal('Unreviewed same-date identity/doubleheader competitor')
    tables['teams'] = _rows(cursor,'teams','team_id=ANY(%s)',([request['home_team_id'],request['away_team_id']],))
    tables['baseball_team_sources'] = _rows(cursor,'baseball_team_sources','team_id=ANY(%s)',([request['home_team_id'],request['away_team_id']],))
    tables['game_sources'] = _rows(cursor, 'game_sources', "game_id=ANY(%s) OR (source_name='mlb_stats' AND external_game_id=%s)", (ids, str(request['game_pk'])))
    sources = [strict_json(row) for row in tables['game_sources']]
    fields = {'game_source_id','game_id','source_name','external_game_id'}
    if sorted(({key: row[key] for key in fields} for row in sources), key=lambda row: row['game_source_id']) != sorted(request['expected_sources'], key=lambda row: row['game_source_id']):
        raise OperatorRefusal('Exact source state differs')
    if any(row['source_name'] != 'odds_api' for row in sources if row['game_id'] == ids[0]):
        raise OperatorRefusal('Subject is not market-only')
    external = [row['external_game_id'] for row in sources if row['source_name'] == 'odds_api']
    tables['odds_provider_event_observations'] = _rows(cursor, 'odds_provider_event_observations',
        "source_name='odds_api' AND external_event_id=ANY(%s)", (external,))
    observations = [strict_json(row) for row in tables['odds_provider_event_observations']]
    if sorted(row['odds_provider_event_observation_id'] for row in observations) != request['expected_observation_ids']:
        raise OperatorRefusal('Exact observation set differs')
    obs = request['expected_observation_ids']
    tables['odds_market_snapshots'] = _rows(cursor, 'odds_market_snapshots',
        'game_id=ANY(%s) OR odds_provider_event_observation_id=ANY(%s)', (ids, obs))
    markets = [strict_json(row) for row in tables['odds_market_snapshots']]
    if sorted(row['odds_market_snapshot_id'] for row in markets) != request['expected_snapshot_ids']:
        raise OperatorRefusal('Exact full price-inclusive snapshot set differs')
    for _, table, columns, _ in inventory:
        if table in {'game_sources','odds_market_snapshots','game_identity_dispositions','mlb_game_identity_write_fences'}:
            continue
        # FK inventory supplies validated identifiers, never operator SQL.
        column = columns[0]
        if not re.fullmatch('[a-z_]+', column):
            raise OperatorRefusal('Unexpected FK column')
        values = _rows(cursor, table, column+'=ANY(%s)', (ids,))
        tables[table+':'+column] = values
    market_ids = request['expected_snapshot_ids']
    tables['market_analysis'] = _rows(cursor, 'market_analysis', 'odds_market_snapshot_id=ANY(%s)', (market_ids,))
    tables['moneyline_prediction_market_evaluations'] = _rows(cursor, 'moneyline_prediction_market_evaluations',
        'odds_market_snapshot_id=ANY(%s) OR moneyline_game_prediction_id IN (SELECT moneyline_game_prediction_id FROM moneyline_game_predictions WHERE game_id=ANY(%s))', (market_ids, ids))
    tables['fences'] = _rows(cursor, 'mlb_game_identity_write_fences', 'game_id=ANY(%s)', (ids,))
    runs = sorted({row['odds_ingestion_run_id'] for row in observations})
    tables['odds_ingestion_runs'] = _rows(cursor, 'odds_ingestion_runs', 'odds_ingestion_run_id=ANY(%s)', (runs,))
    books = sorted({row['sportsbook_id'] for row in markets})
    providers = sorted({row['sportsbook_provider_identity_id'] for row in markets if row['sportsbook_provider_identity_id'] is not None})
    tables['sportsbooks'] = _rows(cursor,'sportsbooks','sportsbook_id=ANY(%s)',(books,))
    tables['sportsbook_provider_identities'] = _rows(cursor,'sportsbook_provider_identities','sportsbook_provider_identity_id=ANY(%s)',(providers,))
    cursor.execute('SELECT mlb_identity_forbidden_dependencies(%s)', (ids[0],))
    if cursor.fetchone() != ({},):
        raise OperatorRefusal('Subject history/betting dependencies prohibit disposition')
    if request['action'] == 'REVOKE':
        cursor.execute("SELECT mlb_identity_forbidden_dependencies(%s)-'non_odds_sources'", (ids[1],))
        if cursor.fetchone() != ({},):
            raise OperatorRefusal('Survivor gained history/decisions; reversal refuses')
    return strict_json(canonical_json(snapshot))


def preview_disposition(*, request_bytes, evidence_bytes, target, connection_factory):
    request, game = validate_request(request_bytes, evidence_bytes)
    connection = connection_factory()
    try:
        connection.set_session(readonly=True, isolation_level='REPEATABLE READ')
        guard = verify_target(connection, target, readonly=True)
        with connection.cursor() as cursor:
            snapshot = read_snapshot(cursor, request, game)
        body = dict(format=FORMAT, version=VERSION, request=request, target=target.artifact(),
                    guard=guard, implementation_sha256=fingerprint(), snapshot=snapshot)
        body['preview_sha256'] = digest(body)
        return body
    finally:
        connection.rollback()
        connection.close()


def execute_disposition(*, request_bytes, evidence_bytes, preview, approved_preview_sha256,
                        target, connection_factory, acknowledge_writes=False,
                        acknowledge_survivor_anchor=False):
    request, game = validate_request(request_bytes, evidence_bytes)
    if acknowledge_writes is not True or not isinstance(preview, dict) or set(preview) != {
            'format','version','request','target','guard','implementation_sha256','snapshot','preview_sha256'}:
        raise OperatorRefusal('Exact independent executable preview/write authority required')
    body = {key:value for key,value in preview.items() if key != 'preview_sha256'}
    if (preview['format'] != FORMAT or type(preview['version']) is not int or preview['version'] != VERSION
            or digest(body) != approved_preview_sha256 or preview['preview_sha256'] != approved_preview_sha256
            or preview['request'] != request or preview['target'] != target.artifact()
            or preview['implementation_sha256'] != fingerprint()):
        raise OperatorRefusal('Preview/evidence/code/target approval mismatch')
    if request['allow_survivor_anchor'] and acknowledge_survivor_anchor is not True:
        raise OperatorRefusal('Separate exact survivor-anchor authorization required')
    connection = connection_factory()
    committing = False
    try:
        connection.set_session(readonly=False, isolation_level='SERIALIZABLE')
        with connection.cursor() as cursor:
            # Snapshot can precede a wait at SERIALIZABLE: changed fences below
            # force serialization failure instead of certifying the old ledger.
            cursor.execute('SELECT mlb_identity_gate(true)')
            guard = verify_target(connection, target, readonly=False)
            ids = sorted((request['subject_game_id'], request['survivor_game_id']))
            cursor.execute('SELECT game_id FROM games WHERE game_id=ANY(%s) ORDER BY game_id FOR UPDATE', (ids,))
            cursor.execute('SELECT game_id,epoch FROM mlb_game_identity_write_fences WHERE game_id=ANY(%s) ORDER BY game_id FOR UPDATE', (ids,))
            cursor.execute('SELECT receipt FROM game_identity_disposition_events WHERE approved_manifest_sha256=%s', (approved_preview_sha256,))
            existing = cursor.fetchone()
            if existing:
                cursor.execute('SELECT mlb_identity_ledger_fingerprint()')
                if cursor.fetchone()[0] != existing[0]['ledger_fingerprint']:
                    raise OperatorRefusal('Receipt state subsequently changed')
                cursor.execute('SELECT mlb_identity_pair_fingerprint(%s,%s)',
                               (request['subject_game_id'],request['survivor_game_id']))
                if cursor.fetchone()[0] != existing[0]['pair_fingerprint']:
                    raise OperatorRefusal('Receipt postconditions subsequently changed')
                connection.rollback()
                return dict(existing[0], replay=True)
            snapshot = read_snapshot(cursor, request, game)
            if snapshot != preview['snapshot'] or guard != preview['guard'] or fingerprint() != preview['implementation_sha256']:
                raise OperatorRefusal('Dependency/ledger/fence/schema/source state changed since preview')
            sources = [strict_json(row) for row in snapshot['tables']['game_sources']]
            anchored = [row for row in sources if row['source_name']=='mlb_stats']
            if anchored:
                if len(anchored)!=1 or anchored[0]['game_id']!=request['survivor_game_id'] or anchored[0]['external_game_id']!=str(request['game_pk']):
                    raise OperatorRefusal('Survivor MLB anchor conflicts')
            elif request['allow_survivor_anchor']:
                cursor.execute("INSERT INTO game_sources(game_id,source_name,external_game_id) VALUES(%s,'mlb_stats',%s)", (request['survivor_game_id'],str(request['game_pk'])))
            else:
                raise OperatorRefusal('Survivor MLB identity is absent')
            cursor.execute('SELECT disposition_id,survivor_game_id FROM game_identity_dispositions WHERE subject_game_id=%s', (request['subject_game_id'],))
            case = cursor.fetchone()
            if case and case[1] != request['survivor_game_id']:
                raise OperatorRefusal('Fixed survivor cannot be retargeted')
            audit = tuple(request[key] for key in ('reason','evidence_reference','evidence_sha256','operator_identity','tool_identity','implementation_commit')) + (preview['implementation_sha256'],)
            if case is None:
                if request['action']!='ACTIVATE':
                    raise OperatorRefusal('Cannot revoke an absent case')
                cursor.execute("""INSERT INTO game_identity_dispositions(domain,subject_game_id,survivor_game_id,
                    disposition_type,policy_version,reason,evidence_reference,evidence_sha256,operator_identity,
                    tool_identity,implementation_commit,implementation_sha256,initial_manifest_sha256)
                    VALUES('MLB',%s,%s,'STALE_MARKET_ONLY_DUPLICATE','1.0.0',%s,%s,%s,%s,%s,%s,%s,%s)
                    RETURNING disposition_id""", (request['subject_game_id'],request['survivor_game_id'])+audit+(approved_preview_sha256,))
                case = cursor.fetchone()
            case_id = case[0]
            cursor.execute('SELECT event_id,sequence FROM game_identity_disposition_events WHERE disposition_id=%s ORDER BY sequence DESC LIMIT 1', (case_id,))
            previous = cursor.fetchone()
            sequence = previous[1]+1 if previous else 1
            # Receipt excludes its own ledger fingerprint to avoid a hash cycle;
            # outcome includes a separately computed committed-state fingerprint.
            receipt = dict(status='COMMITTED', approved_manifest_sha256=approved_preview_sha256,
                           subject_game_id=request['subject_game_id'],survivor_game_id=request['survivor_game_id'],
                           action=request['action'],sequence=sequence,request_sha256=digest(request),
                           replay=False)
            cursor.execute("""INSERT INTO game_identity_disposition_events(disposition_id,sequence,previous_event_id,action,
                reason,evidence_reference,evidence_sha256,operator_identity,tool_identity,implementation_commit,
                implementation_sha256,approved_manifest_sha256,pre_state_sha256,post_state_sha256,receipt)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb) RETURNING receipt""",
                (case_id,sequence,previous[0] if previous else None,request['action'])+audit+
                (approved_preview_sha256,digest(snapshot),digest(dict(subject=request['subject_game_id'],
                 survivor=request['survivor_game_id'],action=request['action'],sequence=sequence)),canonical_json(receipt)))
            receipt = cursor.fetchone()[0]
        committing = True
        connection.commit()
        committing = False
        return receipt
    except Exception:
        try:
            connection.rollback()
        except Exception:
            raise OperatorRefusal('UNKNOWN commit/rollback; read-only receipt inspection required, no retry') from None
        if committing:
            raise OperatorRefusal('UNKNOWN commit acknowledgement; inspect exact receipt, no retry') from None
        raise
    finally:
        connection.close()


def inspect_receipt(*, approved_manifest_sha256, target, connection_factory):
    """Read-only uncertainty resolution; no implicit retry or fresh authority."""
    _hash(approved_manifest_sha256)
    connection = connection_factory()
    try:
        connection.set_session(readonly=True,isolation_level='REPEATABLE READ')
        verify_target(connection,target,readonly=True)
        with connection.cursor() as cursor:
            cursor.execute('SELECT receipt FROM game_identity_disposition_events WHERE approved_manifest_sha256=%s', (approved_manifest_sha256,))
            row = cursor.fetchone()
            if row is None:
                return dict(status='NO_COMMITTED_RECEIPT_VISIBLE',retry_authorized=False)
            receipt = row[0]
            cursor.execute('SELECT mlb_identity_ledger_fingerprint(),mlb_identity_pair_fingerprint(%s,%s)',
                           (receipt['subject_game_id'],receipt['survivor_game_id']))
            ledger,pair = cursor.fetchone()
        return dict(status='COMMITTED_RECEIPT_FOUND',receipt=receipt,
                    current_postconditions_match=(ledger==receipt['ledger_fingerprint'] and pair==receipt['pair_fingerprint']),
                    retry_authorized=False)
    finally:
        connection.rollback()
        connection.close()
