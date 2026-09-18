"""Explicit provider-preview and separately acknowledged pinned-plan execution."""

import argparse
import ast
from datetime import date, datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import tokenize
import traceback

from sportsmodel.database.connection import get_connection
from sportsmodel.database.mlb_recovery_repository import load_mlb_identity
from sportsmodel.ingest.mlb_boxscore import fetch_live_feed, fetch_boxscore
from sportsmodel.ingest.mlb_players import fetch_mlb_players
from sportsmodel.ingest.mlb_stats import fetch_schedule_for_date
from sportsmodel.ingest.mlb_recovery import (
    RecoverySpecification, _events, _disposition, read_snapshot,
    plan_recovery, execute_recovery, canonical_json, digest,
)


def current_revision():
    root = Path(__file__).parents[3]
    return subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()


TRUSTED_VALUE_ERROR_PHASES = frozenset((
    'spec-validation', 'preview-output-precheck', 'evidence-output-precheck',
    'preview-acquisition', 'preview-planning', 'manifest-write',
))

EVIDENCE_FORMAT_VERSION = 1
DIAGNOSTIC_VALUE_LIMIT = 512


def _utc_now():
    return datetime.now(timezone.utc).isoformat()


def _atomic_json_write(path, value):
    temporary = path.with_name(f'.{path.name}.tmp')
    with temporary.open('w', encoding='utf-8', newline='\n') as stream:
        stream.write(canonical_json(value) + '\n')
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def _exclusive_json_write(path, value):
    with path.open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(canonical_json(value) + '\n')
        stream.flush()
        os.fsync(stream.fileno())


def _outside_repository(path):
    root = Path(__file__).resolve().parents[3]
    resolved = path.resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        return resolved
    raise ValueError('Provider evidence directory must be outside the repository')


class PreviewEvidence:
    """Durable, provider-only preview evidence with no request-object capture."""

    def __init__(self, path, spec):
        self.path = _outside_repository(path)
        self.path.mkdir(parents=True, exist_ok=False)
        (self.path / 'games').mkdir()
        self._requests = []
        self._metadata = dict(
            format_version=EVIDENCE_FORMAT_VERSION,
            status='acquisition-in-progress',
            started_at=_utc_now(),
            completed_at=None,
            schedule_date=spec.schedule_date.isoformat(),
            requested_game_pks=list(spec.game_pks),
            requests=self._requests,
        )
        self._write_metadata()
        self.mark_status('acquisition-in-progress')

    def _write_metadata(self):
        _atomic_json_write(self.path / 'acquisition_metadata.json', self._metadata)

    def mark_status(self, status, **details):
        value = dict(format_version=EVIDENCE_FORMAT_VERSION, status=status,
                     observed_at=_utc_now())
        value.update(details)
        _atomic_json_write(self.path / 'preview_status.json', value)

    def _record(self, *, relative_path, payload, source, endpoint_path,
                game_pk=None, query_parameters=None):
        target = self.path / Path(relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        _exclusive_json_write(target, payload)
        record = dict(
            source=source,
            endpoint_path=endpoint_path,
            filename=Path(relative_path).as_posix(),
            game_pk=game_pk,
            query_parameters=query_parameters or {},
            observation_timestamp=_utc_now(),
            payload_sha256=digest(payload),
        )
        self._requests.append(record)
        self._write_metadata()
        return payload

    def schedule(self, payload, schedule_date):
        return self._record(
            relative_path='schedule.json', payload=payload, source='schedule',
            endpoint_path='/api/v1/schedule',
            query_parameters={'sportId': 1, 'date': schedule_date.isoformat()},
        )

    def feed(self, payload, game_pk):
        return self._record(
            relative_path=f'games/{game_pk}/feed.json', payload=payload,
            source='live-feed', endpoint_path=f'/api/v1.1/game/{game_pk}/feed/live',
            game_pk=game_pk,
        )

    def boxscore(self, payload, game_pk):
        return self._record(
            relative_path=f'games/{game_pk}/boxscore.json', payload=payload,
            source='standalone-boxscore',
            endpoint_path=f'/api/v1/game/{game_pk}/boxscore', game_pk=game_pk,
        )

    def people(self, payload, player_ids):
        return self._record(
            relative_path='people.json', payload=payload, source='people',
            endpoint_path='/api/v1/people',
            query_parameters={'personIds': ','.join(str(value) for value in player_ids),
                              'hydrate': 'currentTeam'},
        )

    def complete(self):
        hashes = [dict(source=row['source'], game_pk=row['game_pk'],
                       filename=row['filename'], payload_sha256=row['payload_sha256'])
                  for row in self._requests]
        hash_document = dict(format_version=EVIDENCE_FORMAT_VERSION,
                             payloads=hashes, bundle_sha256=digest(hashes))
        _exclusive_json_write(self.path / 'payload_hashes.json', hash_document)
        self._metadata.update(status='complete', completed_at=_utc_now())
        self._write_metadata()
        self.mark_status('acquisition-complete')
        _exclusive_json_write(
            self.path / 'acquisition_complete.json',
            dict(format_version=EVIDENCE_FORMAT_VERSION,
                 bundle_sha256=hash_document['bundle_sha256']),
        )

    def acquisition_complete(self):
        return (self.path / 'acquisition_complete.json').is_file()

    def fail_acquisition(self):
        self._metadata.update(status='acquisition-failed', completed_at=_utc_now())
        self._write_metadata()
        self.mark_status('acquisition-failed')


def _safe_mark_status(evidence, status, **details):
    try:
        evidence.mark_status(status, **details)
    except BaseException:
        pass


def _pointer(path):
    return '/' + '/'.join(str(value).replace('~', '~0').replace('/', '~1')
                          for value in path)


def _diagnostic_value(value):
    serialized = canonical_json(value)
    if len(serialized) <= DIAGNOSTIC_VALUE_LIMIT:
        return value
    return dict(truncated=True, serialized_length=len(serialized),
                sha256=digest(value), preview=serialized[:DIAGNOSTIC_VALUE_LIMIT])


def field_differences(feed_value, standalone_value):
    """Compare without normalization or mutation and return deterministic paths."""
    differences = []

    def compare(feed, standalone, path):
        if isinstance(feed, dict) and isinstance(standalone, dict):
            for key in sorted(set(feed) | set(standalone)):
                if key not in feed or key not in standalone:
                    differences.append(dict(
                        path=_pointer((*path, key)), feed_present=key in feed,
                        standalone_present=key in standalone,
                        feed=_diagnostic_value(feed[key]) if key in feed else None,
                        standalone=_diagnostic_value(standalone[key]) if key in standalone else None,
                    ))
                else:
                    compare(feed[key], standalone[key], (*path, key))
            return
        if isinstance(feed, list) and isinstance(standalone, list):
            for index in range(max(len(feed), len(standalone))):
                if index >= len(feed) or index >= len(standalone):
                    differences.append(dict(
                        path=_pointer((*path, index)), feed_present=index < len(feed),
                        standalone_present=index < len(standalone),
                        feed=_diagnostic_value(feed[index]) if index < len(feed) else None,
                        standalone=_diagnostic_value(standalone[index]) if index < len(standalone) else None,
                    ))
                else:
                    compare(feed[index], standalone[index], (*path, index))
            return
        if type(feed) is not type(standalone) or feed != standalone:
            differences.append(dict(
                path=_pointer(path), feed_present=True, standalone_present=True,
                feed=_diagnostic_value(feed), standalone=_diagnostic_value(standalone),
            ))

    compare(feed_value, standalone_value, ())
    return differences


def diagnose_evidence(path):
    root = Path(path).resolve()
    metadata = json.loads((root / 'acquisition_metadata.json').read_text(encoding='utf-8'))
    reports = []
    game_pks = sorted({row['game_pk'] for row in metadata['requests']
                       if row.get('game_pk') is not None})
    for game_pk in game_pks:
        game = root / 'games' / str(game_pk)
        feed = json.loads((game / 'feed.json').read_text(encoding='utf-8'))
        standalone = json.loads((game / 'boxscore.json').read_text(encoding='utf-8'))
        feed_boxscore = feed['liveData']['boxscore']
        differences = field_differences(feed_boxscore, standalone)
        reports.append(dict(game_pk=game_pk, equal=not differences,
                            differences=differences))
    return dict(evidence_path=str(root), games=reports)


def _literal_value_error_at(source, line_number):
    """Return the literal only for an exact, unchained ValueError literal raise."""
    try:
        with tokenize.open(source) as stream:
            tree = ast.parse(stream.read(), filename=str(source))
    except (OSError, SyntaxError, UnicodeError):
        return None
    raises = [node for node in ast.walk(tree)
              if isinstance(node, ast.Raise) and node.lineno == line_number]
    if len(raises) != 1:
        return None
    node = raises[0]
    call = node.exc
    if (node.cause is None and isinstance(call, ast.Call)
            and isinstance(call.func, ast.Name) and call.func.id == 'ValueError'
            and len(call.args) == 1 and not call.keywords
            and isinstance(call.args[0], ast.Constant)
            and isinstance(call.args[0].value, str)):
        return call.args[0].value
    return None


def _trusted_value_error_details(error, application_root=None):
    """Return diagnostics only for structurally verified application literals."""
    frames = traceback.extract_tb(error.__traceback__)
    if not frames:
        return None
    frame = frames[-1]
    if application_root is None:
        root = Path(__file__).resolve().parents[3]
        application_root = root / 'src' / 'sportsmodel'
    else:
        application_root = Path(application_root).resolve()
        root = application_root.parents[1]
    source = Path(frame.filename).resolve()
    try:
        source.relative_to(application_root)
        relative_source = source.relative_to(root).as_posix()
    except ValueError:
        return None
    literal = _literal_value_error_at(source, frame.lineno)
    if literal is None or str(error) != literal:
        return None
    return dict(safe_message=literal, source_function=frame.name,
                source_file=relative_source, source_line=frame.lineno)


def _failure_payload(error, failure_phase, application_root=None):
    payload = dict(status='failed-before-write', failure_phase=failure_phase,
                   error=type(error).__name__, safe_message='redacted',
                   source_function=None, source_file=None, source_line=None)
    if isinstance(error, ValueError) and failure_phase in TRUSTED_VALUE_ERROR_PHASES:
        try:
            details = _trusted_value_error_details(error, application_root)
        except BaseException:
            details = None
        if details is not None:
            payload.update(details)
    return payload


def acquire_preview(spec, evidence=None):
    # Capabilities and every raw mapping are verified before any provider request.
    connection = get_connection()
    try:
        connection.set_session(readonly=True)
        with connection.cursor() as cursor:
            cursor.execute('SELECT game_id,mlb_game_id FROM historical_games LIMIT 0')
            cursor.execute('SELECT game_id,team_id,is_home FROM team_game_statistics LIMIT 0')
            cursor.execute('SELECT game_id,baseball_player_id,is_starter FROM player_game_pitching_statistics LIMIT 0')
            cursor.execute('SELECT baseball_player_id,full_name FROM baseball_players LIMIT 0')
            cursor.execute('SELECT external_team_id FROM baseball_team_sources LIMIT 0')
            cursor.execute('SELECT external_player_id FROM baseball_player_sources LIMIT 0')
            for pk in spec.game_pks:
                load_mlb_identity(cursor, pk)
        schedule = fetch_schedule_for_date(spec.schedule_date)
        if evidence is not None:
            evidence.schedule(schedule, spec.schedule_date)
        bundle = dict(observed_at=datetime.now(timezone.utc).isoformat(),
                      schedule=schedule, games={}, people=[])
        for event in _events(spec, bundle):
            pk = event['gamePk']
            if pk in spec.game_pks and _disposition(event) == 'eligible':
                feed = fetch_live_feed(pk)
                if evidence is not None:
                    evidence.feed(feed, pk)
                boxscore = fetch_boxscore(pk)
                if evidence is not None:
                    evidence.boxscore(boxscore, pk)
                bundle['games'][str(pk)] = dict(game_pk=pk, schedule_date=spec.schedule_date.isoformat(),
                                              feed=feed, boxscore=boxscore)
        with connection.cursor() as cursor:
            snapshot = read_snapshot(cursor, spec, bundle)
        missing = sorted(int(p) for p, row in snapshot['players'].items() if row is None)
        if missing:
            people = fetch_mlb_players(missing)
            if evidence is not None:
                evidence.people(people, missing)
            bundle['people'] = people
        if evidence is not None:
            evidence.complete()
        return bundle
    finally:
        connection.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_subparsers(dest='mode', required=True)
    preview = modes.add_parser('preview', help='Read-only DB/provider planning; never execute')
    preview.add_argument('--date', required=True, type=date.fromisoformat)
    preview.add_argument('--game-pks', required=True, type=int, nargs='+')
    preview.add_argument('--output', required=True, type=Path)
    preview.add_argument('--evidence-output', required=True, type=Path)
    preview.add_argument('--acknowledge-provider-access', action='store_true', required=True)
    execute = modes.add_parser('execute', help='Write only a separately approved retained manifest')
    execute.add_argument('--manifest', required=True, type=Path)
    execute.add_argument('--approved-manifest-sha256', required=True)
    execute.add_argument('--acknowledge-production-writes', action='store_true', required=True)
    diagnose = modes.add_parser('diagnose-evidence', help='Compare retained provider boxscores')
    diagnose.add_argument('--evidence', required=True, type=Path)
    args = parser.parse_args(argv)
    failure_phase = 'cli'
    evidence = None
    try:
        if args.mode == 'diagnose-evidence':
            print(canonical_json(diagnose_evidence(args.evidence)))
            return 0
        revision = current_revision()
        if args.mode == 'preview':
            failure_phase = 'spec-validation'
            spec = RecoverySpecification(args.date, tuple(args.game_pks), revision)
            failure_phase = 'preview-output-precheck'
            if args.output.exists() or not args.output.parent.is_dir():
                raise ValueError('Preview output must be a new file in an existing directory')
            failure_phase = 'evidence-output-precheck'
            manifest_path = args.output.resolve()
            evidence_path = args.evidence_output.resolve()
            if (manifest_path == evidence_path or manifest_path in evidence_path.parents
                    or evidence_path in manifest_path.parents):
                raise ValueError('Manifest and provider evidence paths must be distinct')
            evidence = PreviewEvidence(args.evidence_output, spec)
            failure_phase = 'preview-acquisition'
            bundle = acquire_preview(spec, evidence=evidence)
            failure_phase = 'preview-planning'
            try:
                manifest = plan_recovery(spec, bundle)
            except BaseException:
                _safe_mark_status(evidence, 'planning-failed')
                raise
            evidence.mark_status('planning-complete')
            failure_phase = 'manifest-write'
            # Never silently overwrite a retained approval artifact.
            stream = args.output.open('x', encoding='utf-8', newline='\n')
            try:
                with stream:
                    stream.write(canonical_json(manifest) + '\n')
            except BaseException:
                args.output.unlink(missing_ok=True)
                _safe_mark_status(evidence, 'manifest-write-failed')
                raise
            evidence.mark_status('success', manifest_sha256=manifest['manifest_sha256'])
            print(manifest['manifest_sha256'])
            return 0
        manifest = json.loads(args.manifest.read_text(encoding='utf-8'))
        result = execute_recovery(manifest, args.approved_manifest_sha256,
                                  code_revision=revision, acknowledge_writes=args.acknowledge_production_writes)
        print(canonical_json(result))
        return 0 if result['status'] == 'complete' else 1
    except Exception as error:
        # Provider/DB exceptions can contain connection URLs or credentials.
        if evidence is not None and failure_phase == 'preview-acquisition':
            try:
                evidence.fail_acquisition()
            except BaseException:
                pass
        failure = _failure_payload(error, failure_phase)
        if evidence is not None:
            try:
                failure.update(
                    evidence_path=str(evidence.path),
                    evidence_status=('complete' if evidence.acquisition_complete()
                                     else 'incomplete'),
                )
            except BaseException:
                pass
        print(canonical_json(failure))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
