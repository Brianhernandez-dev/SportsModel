"""Explicit provider-preview and separately acknowledged pinned-plan execution."""

import argparse
from datetime import date, datetime, timezone
import json
from pathlib import Path
import subprocess

from sportsmodel.database.connection import get_connection
from sportsmodel.database.mlb_recovery_repository import load_mlb_identity
from sportsmodel.ingest.mlb_boxscore import fetch_live_feed, fetch_boxscore
from sportsmodel.ingest.mlb_players import fetch_mlb_players
from sportsmodel.ingest.mlb_stats import fetch_schedule_for_date
from sportsmodel.ingest.mlb_recovery import (
    RecoverySpecification, _events, _disposition, read_snapshot,
    plan_recovery, execute_recovery, canonical_json,
)


def current_revision():
    root = Path(__file__).parents[3]
    return subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()


def acquire_preview(spec):
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
        bundle = dict(observed_at=datetime.now(timezone.utc).isoformat(),
                      schedule=fetch_schedule_for_date(spec.schedule_date), games={}, people=[])
        for event in _events(spec, bundle):
            pk = event['gamePk']
            if pk in spec.game_pks and _disposition(event) == 'eligible':
                bundle['games'][str(pk)] = dict(game_pk=pk, schedule_date=spec.schedule_date.isoformat(),
                                              feed=fetch_live_feed(pk), boxscore=fetch_boxscore(pk))
        with connection.cursor() as cursor:
            snapshot = read_snapshot(cursor, spec, bundle)
        missing = sorted(int(p) for p, row in snapshot['players'].items() if row is None)
        bundle['people'] = fetch_mlb_players(missing) if missing else []
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
    preview.add_argument('--acknowledge-provider-access', action='store_true', required=True)
    execute = modes.add_parser('execute', help='Write only a separately approved retained manifest')
    execute.add_argument('--manifest', required=True, type=Path)
    execute.add_argument('--approved-manifest-sha256', required=True)
    execute.add_argument('--acknowledge-production-writes', action='store_true', required=True)
    args = parser.parse_args(argv)
    try:
        revision = current_revision()
        if args.mode == 'preview':
            spec = RecoverySpecification(args.date, tuple(args.game_pks), revision)
            if args.output.exists() or not args.output.parent.is_dir():
                raise ValueError('Preview output must be a new file in an existing directory')
            manifest = plan_recovery(spec, acquire_preview(spec))
            # Never silently overwrite a retained approval artifact.
            with args.output.open('x', encoding='utf-8', newline='\n') as stream:
                stream.write(canonical_json(manifest) + '\n')
            print(manifest['manifest_sha256'])
            return 0
        manifest = json.loads(args.manifest.read_text(encoding='utf-8'))
        result = execute_recovery(manifest, args.approved_manifest_sha256,
                                  code_revision=revision, acknowledge_writes=args.acknowledge_production_writes)
        print(canonical_json(result))
        return 0 if result['status'] == 'complete' else 1
    except Exception as error:
        # Provider/DB exceptions can contain connection URLs or credentials.
        print(canonical_json(dict(status='failed-before-write', failure_phase='cli',
                                  error=type(error).__name__)))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
