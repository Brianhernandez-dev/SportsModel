"""Pinned-payload, existing-identity-only MLB historical recovery.

No provider work occurs in execution. Planning uses read-only DB sessions and
never calls the ordinary create/synchronize ingestion helpers.
"""

from dataclasses import asdict, dataclass
from datetime import date, datetime
from enum import Enum
from hashlib import sha256
import json
from pathlib import Path
import re
from zoneinfo import ZoneInfo

from sportsmodel.database.connection import get_connection
from sportsmodel.database import mlb_recovery_repository as repository
from sportsmodel.ingest.boxscore_parser import (
    parse_boxscore, parse_pitcher_statistics, parse_team_statistics,
)
from sportsmodel.ingest.mlb_players import normalize_mlb_player
from sportsmodel.ingest.mlb_stats import save_historical_result, _parse_finalized_schedule_game


VERSION = 1
CONTRACT = 'final-regular-or-explicit-exclusion-v1'
MUTATIONS = ['historical_games', 'team_game_statistics',
             'player_game_pitching_statistics', 'games.result_metadata',
             'baseball_players.missing_only', 'baseball_player_sources.missing_only']


def _json_default(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    raise TypeError(type(value).__name__)


def canonical_json(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      allow_nan=False, default=_json_default)


def digest(value) -> str:
    return sha256(canonical_json(value).encode('utf-8')).hexdigest()


def implementation_hash():
    root = Path(__file__).parents[1]
    paths = ['ingest/mlb_recovery.py', 'database/mlb_recovery_repository.py',
             'ingest/mlb_recovery_cli.py', 'database/connection.py',
             'ingest/boxscore_parser.py', 'ingest/mlb_players.py', 'ingest/mlb_stats.py',
             'database/boxscore_repository.py', 'models/parsed_boxscore.py',
             'models/team_game_statistics.py', 'models/player_game_pitching_statistics.py']
    return digest({p: sha256((root / p).read_bytes()).hexdigest() for p in paths})


def _positive(value):
    if type(value) is not int or value <= 0:
        raise ValueError('gamePk/participant IDs must be positive integers')
    return value


def _aware(value):
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('Timezone-aware observation/start timestamp required')
    return parsed


@dataclass(frozen=True)
class RecoverySpecification:
    schedule_date: date
    game_pks: tuple[int, ...]
    code_revision: str
    format_version: int = VERSION
    eligibility_contract: str = CONTRACT

    def __post_init__(self):
        if type(self.schedule_date) is not date:
            raise ValueError('An explicit ISO schedule date is required')
        if not self.game_pks or len(set(self.game_pks)) != len(self.game_pks):
            raise ValueError('Allowlist must be nonempty and unique')
        for pk in self.game_pks:
            _positive(pk)
        if type(self.format_version) is not int or self.format_version != VERSION or self.eligibility_contract != CONTRACT:
            raise ValueError('Unsupported manifest/eligibility version')
        if not re.fullmatch(r'[0-9a-f]{40}', self.code_revision):
            raise ValueError('Expected a full Git revision')
        object.__setattr__(self, 'game_pks', tuple(sorted(self.game_pks)))

    @classmethod
    def from_dict(cls, value):
        return cls(date.fromisoformat(value['schedule_date']), tuple(value['game_pks']),
                   value['code_revision'], value['format_version'], value['eligibility_contract'])


@dataclass(frozen=True)
class ApprovedRecoverySpecification:
    recovery: RecoverySpecification
    manifest_sha256: str

    def __post_init__(self):
        if not isinstance(self.recovery, RecoverySpecification) or not re.fullmatch(r'[0-9a-f]{64}', self.manifest_sha256):
            raise ValueError('An exact approved SHA-256 recovery specification is required')


def _events(spec, bundle):
    events = []
    blocks = bundle['schedule']['dates']
    for block in blocks:
        if block['date'] != spec.schedule_date.isoformat():
            raise ValueError('Schedule response date differs from requested date')
        events.extend(block['games'])
    pks = [_positive(e['gamePk']) for e in events]
    if len(set(pks)) != len(pks):
        raise ValueError('Duplicate returned gamePk')
    if set(spec.game_pks) - set(pks):
        raise ValueError('Missing allowlisted event; absence is not exclusion')
    for event in events:
        if event['gamePk'] not in spec.game_pks and _disposition(event) == 'eligible':
            raise ValueError('Eligible out-of-allowlist event')
    return sorted(events, key=lambda e: e['gamePk'])


def _disposition(event):
    status = event['status']
    if event['gameType'] not in ('R', 'S', 'F', 'D', 'L', 'W', 'C', 'A', 'E'):
        raise ValueError('Unknown game type cannot silently become an exclusion')
    if event['gameType'] != 'R':
        return 'excluded-ineligible-game-type'
    if status.get('abstractGameState') == 'Final' or status.get('detailedState') == 'Final':
        if _parse_finalized_schedule_game(event) is None:
            raise ValueError('Malformed finalized schedule event')
        return 'eligible'
    if status.get('detailedState') in ('Postponed', 'Suspended'):
        return 'excluded-' + status['detailedState'].lower()
    if status.get('abstractGameState') in ('Preview', 'Live'):
        return 'excluded-nonfinal'
    raise ValueError('Unknown status cannot silently become an exclusion')


def _participants(event):
    return {side: _positive(event['teams'][side]['team']['id']) for side in ('home', 'away')}


def _player_ids(box):
    return sorted({_positive(p['person']['id']) for side in ('home', 'away')
                   for p in box['teams'][side]['players'].values()})


def _recovery_boxscore_projection(box):
    """Return only boxscore values that can affect a recovery mutation."""
    team_ids = {int(box['teams'][side]['team']['id']):
                int(box['teams'][side]['team']['id'])
                for side in ('away', 'home')}
    player_ids = {player_id: player_id for player_id in _player_ids(box)}
    identities = {}
    for side in ('away', 'home'):
        section = box['teams'][side]
        identities[side] = dict(
            team_id=section['team']['id'],
            players={key: player['person']['id']
                     for key, player in sorted(section['players'].items())},
            pitchers=list(section['pitchers']),
        )
    return dict(
        identities=identities,
        team_statistics=[asdict(value) for value in parse_team_statistics(
            box, game_id=1, team_ids_by_mlb_id=team_ids)],
        pitcher_statistics=[asdict(value) for value in parse_pitcher_statistics(
            box, game_id=1, team_ids_by_mlb_id=team_ids,
            player_ids_by_mlb_id=player_ids)],
    )


def read_snapshot(cursor, spec, bundle, *, lock=False):
    events = _events(spec, bundle)
    snapshot = dict(games={}, teams={}, players={})
    for event in events:
        pk = event['gamePk']
        if pk not in spec.game_pks:
            continue
        teams = _participants(event)
        for external in teams.values():
            snapshot['teams'][str(external)] = repository.resolve_mlb_team(cursor, external, lock=lock)
        snapshot['games'][str(pk)] = repository.resolve_existing_mlb_game(
            cursor, pk, home_team_id=snapshot['teams'][str(teams['home'])],
            away_team_id=snapshot['teams'][str(teams['away'])], lock=lock)
        identity = snapshot['games'][str(pk)]
        if identity['mlb_game_id'] is not None and identity['mlb_game_id'] != pk:
            raise ValueError('Legacy MLB identity conflicts with authoritative mapping')
        if sum(row['game_id'] == identity['game_id'] for row in snapshot['games'].values()) != 1:
            raise ValueError('Distinct allowlisted MLB identities share one canonical game')
        if _disposition(event) == 'eligible':
            for player in _player_ids(bundle['games'][str(pk)]['boxscore']):
                row = repository.resolve_mlb_player(cursor, player, lock=lock)
                snapshot['players'][str(player)] = list(row) if row else None
    return json.loads(canonical_json(snapshot))


def _validate_box(event, pinned):
    pk = event['gamePk']
    feed, box = pinned['feed'], pinned['boxscore']
    # Standalone MLB boxscores have no native gamePk. Bind the request ID and
    # require agreement with the boxscore embedded in the identified live feed.
    if feed['gamePk'] != pk or pinned['game_pk'] != pk or box.get('gamePk', pk) != pk:
        raise ValueError('Pinned boxscore request identity mismatch')
    try:
        standalone_projection = _recovery_boxscore_projection(box)
        feed_projection = _recovery_boxscore_projection(feed['liveData']['boxscore'])
    except (AttributeError, KeyError, TypeError):
        raise ValueError('Standalone/feed boxscore disagreement') from None
    if canonical_json(standalone_projection) != canonical_json(feed_projection):
        raise ValueError('Standalone/feed boxscore disagreement')
    if feed['gameData']['game']['type'] != event['gameType']:
        raise ValueError('Feed game type mismatch')
    metadata = feed['gameData']['game']
    _positive(metadata['gameNumber'])
    if metadata['doubleHeader'] not in ('N', 'Y'):
        raise ValueError('Unsupported doubleheader metadata contract')
    for key in ('gameNumber', 'doubleHeader'):
        if key in event and event[key] != metadata[key]:
            raise ValueError('Schedule/feed game metadata disagreement')
    if feed['gameData']['status']['abstractGameState'] != 'Final':
        raise ValueError('Feed is not final')
    if _aware(event['gameDate']) != _aware(feed['gameData']['datetime']['dateTime']):
        raise ValueError('Schedule/feed start mismatch')
    if date.fromisoformat(feed['gameData']['datetime']['officialDate']) != date.fromisoformat(pinned['schedule_date']):
        raise ValueError('Feed official date mismatch')
    for side, external in _participants(event).items():
        if feed['gameData']['teams'][side]['id'] != external or box['teams'][side]['team']['id'] != external:
            raise ValueError('Schedule/feed/boxscore participant mismatch')
        section = box['teams'][side]
        pitchers = section['pitchers']
        if not pitchers or len(set(pitchers)) != len(pitchers):
            raise ValueError('Missing/duplicate pitcher appearance identity')
        for player in pitchers:
            _positive(player)
            if section['players'][f'ID{player}']['person']['id'] != player:
                raise ValueError('Pitcher identity mismatch')
        score = event['teams'][side]['score']
        if section['teamStats']['batting']['runs'] != score or feed['liveData']['linescore']['teams'][side]['runs'] != score:
            raise ValueError('Schedule/feed/boxscore score mismatch')


def build_manifest(spec, bundle, snapshot, *, protected_references=None):
    """Pure validation/planning over pinned observations and a read-only snapshot."""
    bundle = json.loads(canonical_json(bundle))
    _aware(bundle['observed_at'])
    records, excluded, outside, eligible = [], [], [], []
    events = _events(spec, bundle)
    for event in events:
        pk, disposition = event['gamePk'], _disposition(event)
        if pk not in spec.game_pks:
            outside.append(dict(game_pk=pk, disposition=disposition,
                                game_type=event['gameType'], status=event['status']))
            continue
        identity = snapshot['games'][str(pk)]
        if _aware(identity['start']).astimezone(ZoneInfo('America/Los_Angeles')).date() != spec.schedule_date:
            raise ValueError('Canonical game is outside the approved schedule date')
        participants = _participants(event)
        teams = {k: snapshot['teams'][str(v)] for k, v in participants.items()}
        if (identity['home_team_id'], identity['away_team_id']) != (teams['home'], teams['away']):
            raise ValueError('Authoritative participant orientation mismatch')
        record = dict(game_pk=pk, identity=identity, disposition=disposition,
                      game_type=event['gameType'], status=event['status'],
                      participants=participants, schedule_start=event['gameDate'])
        _aware(event['gameDate'])
        if disposition != 'eligible':
            excluded.append(dict(game_pk=pk, reason=disposition))
        else:
            eligible.append(pk)
            pinned = bundle['games'][str(pk)]
            if pinned['schedule_date'] != spec.schedule_date.isoformat():
                raise ValueError('Pinned schedule date mismatch')
            _validate_box(event, pinned)
            # Parse using MLB person IDs as transport IDs, then label them explicitly.
            # They are NEVER written as canonical baseball_player_id values.
            parsed = parse_boxscore(game_id=identity['game_id'], game_pk=pk,
                                   live_feed=pinned['feed'], boxscore=pinned['boxscore'],
                                   team_ids_by_mlb_id={participants[s]: teams[s] for s in teams},
                                   player_ids_by_mlb_id={p: p for p in _player_ids(pinned['boxscore'])})
            data = json.loads(canonical_json(asdict(parsed)))
            for row in data['pitcher_statistics']:
                row['mlb_player_id'] = row.pop('baseball_player_id')
            starters = [row['mlb_player_id'] for row in data['pitcher_statistics'] if row['is_starter']]
            appearances = [r['mlb_player_id'] for r in data['pitcher_statistics']]
            if len(set(appearances)) != len(appearances):
                raise ValueError('Duplicate pitcher identity across oriented teams')
            if len(starters) != 2 or {r['team_id'] for r in data['pitcher_statistics'] if r['is_starter']} != set(teams.values()):
                raise ValueError('Exactly one starter per oriented team required')
            for row in data['team_statistics']:
                other_side = 'away' if row['is_home'] else 'home'
                if row['runs_allowed'] != event['teams'][other_side]['score'] or sum(p['pitching_outs'] for p in data['pitcher_statistics'] if p['team_id'] == row['team_id']) != row['pitching_outs']:
                    raise ValueError('Team/pitcher totals disagree with final results')
            record.update(boxscore=data, starters=starters, result=dict(
                game_id=identity['game_id'], mlb_game_id=pk,
                game_date=spec.schedule_date.isoformat(),
                home_team=event['teams']['home']['team']['name'],
                away_team=event['teams']['away']['team']['name'],
                home_score=event['teams']['home']['score'], away_score=event['teams']['away']['score']),
                game_metadata=dict(game_number=parsed.game_number,
                                   doubleheader_status='doubleheader' if parsed.double_header else 'single'))
        records.append(record)
    missing = sorted(int(p) for p, row in snapshot['players'].items() if row is None)
    people = {str(_positive(p['id'])): p for p in bundle.get('people', [])}
    if len(people) != len(bundle.get('people', [])) or set(people) != {str(p) for p in missing}:
        raise ValueError('People payloads must exactly enumerate missing player synchronization')
    sync = [json.loads(canonical_json(asdict(normalize_mlb_player(people[str(p)])))) for p in missing]
    for player in sync:
        if len(player['full_name']) > 150 or (player['active_from'] and player['active_through'] and player['active_from'] > player['active_through']):
            raise ValueError('Player metadata is incompatible with maintained constraints')
    body = dict(format_version=VERSION, specification=json.loads(canonical_json(asdict(spec))),
                implementation_hash=implementation_hash(),
                scope_hash=digest(asdict(spec)), source_payload_hash=digest(bundle),
                source_payload_hashes={k: digest(v) for k, v in bundle.items() if k != 'observed_at'},
                source_observation_timestamps={'bundle': bundle['observed_at']},
                observed_at=bundle['observed_at'], pinned_payloads=bundle, snapshot=snapshot,
                requested_game_pks=list(spec.game_pks), returned_game_pks=[e['gamePk'] for e in events],
                eligible_game_pks=eligible, excluded=excluded, outside_allowlist=outside,
                missing_allowlisted_events=[], missing_player_ids=missing, player_sync=sync,
                mutation_classes=MUTATIONS, games=records,
                protected_references=protected_references or {})
    body['manifest_sha256'] = digest(body)
    return body


def plan_recovery(spec, bundle, *, connection_factory=get_connection, protected_references=None):
    connection = connection_factory()
    try:
        connection.set_session(readonly=True, isolation_level='REPEATABLE READ')
        with connection.cursor() as cursor:
            snapshot = read_snapshot(cursor, spec, bundle)
        return build_manifest(spec, bundle, snapshot, protected_references=protected_references)
    finally:
        connection.close()


def _revalidate(cursor, manifest, *, lock=False):
    spec = RecoverySpecification.from_dict(manifest['specification'])
    current = read_snapshot(cursor, spec, manifest['pinned_payloads'], lock=lock)
    old = manifest['snapshot']
    if current['games'] != old['games'] or current['teams'] != old['teams']:
        raise ValueError('Canonical/source/team identity changed after approval')
    for p, expected in old['players'].items():
        actual = current['players'][p]
        if expected is not None and (actual is None or actual[0] != expected[0]):
            raise ValueError('Existing player mapping changed after approval')
        if expected is None and actual is not None:
            proposed = next(v for v in manifest['player_sync'] if v['external_player_id'] == p)
            if actual[1:] != [proposed[k] for k in ('full_name','bats','throws','primary_position','active_from','active_through','is_active')]:
                raise ValueError('Missing player acquired conflicting metadata after approval')
    return current


def execute_recovery(manifest, approved_hash, *, code_revision,
                     acknowledge_writes=False, connection_factory=get_connection):
    """Date results then per-game player/boxscore commits; never whole-run atomic."""
    outcome = dict(status='failed-before-write', manifest_hash=approved_hash,
                   committed_results=[], committed_boxscores=[], synchronized_players=[],
                   failed_games=[], failure_phase='approval', error=None,
                   uncertain_commits=[])
    connection = None
    phase, active = 'approval', []
    committing = False
    try:
        if not acknowledge_writes:
            raise ValueError('Explicit independent production-write authorization required')
        body = {k: v for k, v in manifest.items() if k != 'manifest_sha256'}
        if digest(body) != approved_hash or manifest['manifest_sha256'] != approved_hash:
            raise ValueError('Approved manifest hash mismatch')
        spec = RecoverySpecification.from_dict(manifest['specification'])
        ApprovedRecoverySpecification(spec, approved_hash)
        if code_revision != spec.code_revision or manifest['format_version'] != VERSION:
            raise ValueError('Code/manifest revision mismatch')
        rebuilt = build_manifest(spec, manifest['pinned_payloads'], manifest['snapshot'],
                                 protected_references=manifest['protected_references'])
        if canonical_json(rebuilt) != canonical_json(manifest):
            raise ValueError('Pinned payload/plan differs from approved manifest')
        phase = 'preflight'
        active = list(manifest['eligible_game_pks'])
        connection = connection_factory()
        # Protect absent result-key predicates too: concurrent conflicting
        # inserts must serialize/fail, never silently redirect the normal upsert.
        connection.set_session(isolation_level='SERIALIZABLE')
        with connection.cursor() as cursor:
            _revalidate(cursor, manifest, lock=True)
            for game in manifest['games']:
                if game['disposition'] == 'eligible':
                    repository.validate_result_scope(cursor, game['identity']['game_id'],
                                                     game['game_pk'], spec.schedule_date)
            phase = 'results'
            active = manifest['eligible_game_pks']
            for game in manifest['games']:
                if game['disposition'] == 'eligible':
                    result = dict(game['result'])
                    result['game_date'] = date.fromisoformat(result['game_date'])
                    save_historical_result(cursor=cursor, **result)
        committing = True
        connection.commit()
        committing = False
        outcome['committed_results'] = list(active)
        for game in manifest['games']:
            if game['disposition'] != 'eligible':
                continue
            active, phase = [game['game_pk']], 'boxscore'
            synchronized = []
            with connection.cursor() as cursor:
                current = _revalidate(cursor, manifest, lock=True)
                pinned = manifest['pinned_payloads']['games'][str(game['game_pk'])]
                player_map = {}
                for p in _player_ids(pinned['boxscore']):
                    row = current['players'][str(p)]
                    if row is None:
                        phase = 'player-sync'
                        payload = next(v for v in manifest['pinned_payloads']['people'] if v['id'] == p)
                        player_map[p] = repository.insert_missing_mlb_player(cursor, payload, manifest['observed_at'])
                        synchronized.append(p)
                    else:
                        player_map[p] = row[0]
                phase = 'boxscore'
                parsed = parse_boxscore(game_id=game['identity']['game_id'], game_pk=game['game_pk'],
                                       live_feed=pinned['feed'], boxscore=pinned['boxscore'],
                                       team_ids_by_mlb_id={int(k): v for k, v in current['teams'].items()},
                                       player_ids_by_mlb_id=player_map)
                repository.save_recovery_boxscore(cursor, parsed)
            committing = True
            connection.commit()
            committing = False
            outcome['committed_boxscores'].extend(active)
            outcome['synchronized_players'].extend(synchronized)
        outcome.update(status='complete', failure_phase=None)
    except Exception as error:
        if connection is not None:
            try:
                connection.rollback()
            except Exception:
                pass
        if committing:
            outcome['uncertain_commits'].append(dict(phase=phase, game_pks=list(active)))
        outcome.update(status='partial' if outcome['committed_results'] or committing else 'failed-before-write',
                       failure_phase=phase, failed_games=list(active),
                       error=f'{type(error).__name__}: {error}')
    finally:
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass
    return outcome
