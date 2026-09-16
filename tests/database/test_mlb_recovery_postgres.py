"""Recovery against the established, explicitly gated disposable PostgreSQL."""

from datetime import date
from copy import deepcopy
import json
import os
from pathlib import Path

import psycopg2
from psycopg2.extensions import parse_dsn
import pytest

from sportsmodel.ingest import mlb_recovery as recovery
from sportsmodel.database import mlb_recovery_repository as repository


REVISION = 'a' * 40
FIXTURE = Path(__file__).parents[1] / 'fixtures/mlb_recovery/synthetic.json'
PROTECTED = ('teams', 'games', 'game_sources', 'baseball_team_sources',
             'baseball_player_team_assignments', 'moneyline_daily_workflow_runs',
             'moneyline_prediction_runs', 'moneyline_game_predictions',
             'moneyline_prediction_market_evaluations', 'moneyline_paper_candidate_settlements',
             'odds_ingestion_runs', 'odds_market_snapshots')


@pytest.fixture
def recovery_database(request):
    url = os.getenv('SPORTSMODEL_TEST_DATABASE_URL')
    if not url or os.getenv('SPORTSMODEL_ALLOW_DESTRUCTIVE_TEST_DB') != '1':
        pytest.skip('requires explicitly authorized disposable PostgreSQL')
    target = parse_dsn(url)
    assert target.get('host') == '127.0.0.1'
    assert target.get('port') == '55432'
    assert target.get('dbname') == 'sportsmodel_test'
    assert target.get('user') == 'sportsmodel_test'
    # The positive target guard runs BEFORE the destructive shared fixture.
    url = request.getfixturevalue('initialized_nfl_test_database')
    connection = psycopg2.connect(url)
    with connection.cursor() as cursor:
        cursor.execute("INSERT INTO teams(team_name) VALUES('Synthetic Home'),('Synthetic Away') RETURNING team_id")
        home, away = [r[0] for r in cursor.fetchall()]
        cursor.execute("INSERT INTO games(game_date,home_team_id,away_team_id) VALUES('2025-08-01T19:00:00Z',%s,%s),('2025-08-01T19:01:00Z',%s,%s) RETURNING game_id", (home,away,home,away))
        canonical, odds = [r[0] for r in cursor.fetchall()]
        cursor.execute("INSERT INTO game_sources(game_id,source_name,external_game_id) VALUES(%s,'mlb_stats','800'),(%s,'odds_api','retained-odds')", (canonical,odds))
        cursor.execute("INSERT INTO baseball_team_sources(team_id,source_name,external_team_id) VALUES(%s,'mlb_stats','10'),(%s,'mlb_stats','20')", (home,away))
        cursor.execute("INSERT INTO moneyline_daily_workflow_runs(target_date,status,current_stage,error_message) VALUES('2025-08-01','failed','schedule_sync','Protected historical failure')")
        cursor.execute("INSERT INTO moneyline_prediction_runs(target_date,model_version,feature_schema_version,model_artifact_sha256,status,completed_at,run_type) VALUES('2025-08-02','synthetic','1',%s,'completed',now(),'official')", ('b'*64,))
    connection.commit(); connection.close()
    return url, canonical, odds


def plan(url):
    return recovery.plan_recovery(
        recovery.RecoverySpecification(date(2025,8,1),(800,),REVISION),
        json.loads(FIXTURE.read_text()), connection_factory=lambda: psycopg2.connect(url))


def execute(url, manifest):
    return recovery.execute_recovery(manifest, manifest['manifest_sha256'],
                                     code_revision=REVISION, acknowledge_writes=True,
                                     connection_factory=lambda: psycopg2.connect(url))


def evidence(url, allowed_game_id=None):
    connection = psycopg2.connect(url)
    try:
        with connection.cursor() as cursor:
            captured = {}
            for table in PROTECTED:
                cursor.execute(f'SELECT row_to_json(t) FROM {table} t')
                rows = [r[0] for r in cursor.fetchall()]
                if table == 'games':
                    for row in rows:
                        if row['game_id'] == allowed_game_id:
                            row.pop('game_number'); row.pop('doubleheader_status')
                captured[table] = sorted(recovery.canonical_json(r) for r in rows)
            return captured
    finally:
        connection.close()


def counts(url, canonical):
    connection = psycopg2.connect(url)
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT (SELECT count(*) FROM historical_games WHERE game_id=%s),(SELECT count(*) FROM team_game_statistics WHERE game_id=%s),(SELECT count(*) FROM player_game_pitching_statistics WHERE game_id=%s),(SELECT count(*) FROM player_game_pitching_statistics WHERE game_id=%s AND is_starter)', (canonical,)*4)
            return cursor.fetchone()
    finally:
        connection.close()


def test_preview_and_execution_preserve_identity_and_betting_evidence(recovery_database):
    url, canonical, odds = recovery_database
    protected = evidence(url, canonical)
    manifest = plan(url)
    assert evidence(url, canonical) == protected
    assert counts(url,canonical) == (0,0,0,0)
    result = execute(url,manifest)
    assert result['status'] == 'complete', result
    assert result['committed_results'] == result['committed_boxscores'] == [800]
    assert result['synchronized_players'] == [100,200]
    assert counts(url,canonical) == (1,2,2,2)
    assert evidence(url, canonical) == protected
    assert execute(url,manifest)['status'] == 'complete'
    assert counts(url,canonical) == (1,2,2,2)
    connection = psycopg2.connect(url)
    with connection.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM baseball_player_sources WHERE source_name='mlb_stats' AND external_player_id IN('100','200')")
        assert cursor.fetchone()[0] == 2
    connection.close()


@pytest.mark.parametrize('drift', ['mapping','orientation','source','team','player'])
def test_drift_after_preview_refused_before_write(recovery_database, drift):
    url, canonical, odds = recovery_database
    manifest = plan(url)
    connection = psycopg2.connect(url)
    with connection.cursor() as cursor:
        if drift == 'mapping':
            cursor.execute("UPDATE game_sources SET game_id=%s WHERE source_name='mlb_stats' AND external_game_id='800'", (odds,))
        elif drift == 'orientation':
            cursor.execute('UPDATE games SET home_team_id=away_team_id,away_team_id=home_team_id WHERE game_id=%s', (canonical,))
        elif drift == 'source':
            cursor.execute("INSERT INTO game_sources(game_id,source_name,external_game_id) VALUES(%s,'odds_api','unexpected')", (canonical,))
        elif drift == 'team':
            cursor.execute("UPDATE baseball_team_sources SET external_team_id='11' WHERE external_team_id='10'")
        else:
            cursor.execute("INSERT INTO baseball_players(full_name) VALUES('Conflicting person') RETURNING baseball_player_id")
            cursor.execute("INSERT INTO baseball_player_sources(baseball_player_id,source_name,external_player_id) VALUES(%s,'mlb_stats','100')", (cursor.fetchone()[0],))
    connection.commit();connection.close()
    result = execute(url,manifest)
    assert result['status'] == 'failed-before-write', result
    assert result['failure_phase'] == 'preflight'
    assert result['failed_games'] == [800]
    assert counts(url,canonical) == (0,0,0,0)


def test_boxscore_failure_reports_partial_and_rolls_back_players(recovery_database, monkeypatch):
    url, canonical, odds = recovery_database
    manifest = plan(url)
    def fail(cursor, parsed):
        raise RuntimeError('Synthetic boxscore failure')
    monkeypatch.setattr(repository,'save_recovery_boxscore',fail)
    result = execute(url,manifest)
    assert result['status'] == 'partial'
    assert result['committed_results'] == [800]
    assert result['committed_boxscores'] == result['synchronized_players'] == []
    assert result['failed_games'] == [800] and result['failure_phase'] == 'boxscore'
    assert counts(url,canonical) == (1,0,0,0)


def test_missing_mapping_preview_refused(recovery_database):
    url,canonical,odds = recovery_database
    connection = psycopg2.connect(url)
    with connection.cursor() as cursor:
        cursor.execute("DELETE FROM game_sources WHERE source_name='mlb_stats' AND external_game_id='800'")
    connection.commit();connection.close()
    with pytest.raises(ValueError):
        plan(url)
    assert counts(url,canonical) == (0,0,0,0)


def test_identity_row_lock_blocks_concurrent_mutation(recovery_database):
    url,canonical,odds = recovery_database
    connection = psycopg2.connect(url); concurrent = psycopg2.connect(url)
    try:
        with connection.cursor() as cursor:
            repository.load_mlb_identity(cursor,800,lock=True)
        with concurrent.cursor() as cursor:
            cursor.execute("SET LOCAL lock_timeout='100ms'")
            with pytest.raises(psycopg2.errors.LockNotAvailable):
                cursor.execute('UPDATE games SET home_team_id=away_team_id WHERE game_id=%s', (canonical,))
    finally:
        connection.rollback();concurrent.rollback();connection.close();concurrent.close()


@pytest.mark.parametrize('conflict', ['other_game', 'other_date', 'other_mlb_id'])
def test_existing_result_identity_conflict_cannot_be_redirected(recovery_database, conflict):
    url, canonical, odds = recovery_database
    manifest = plan(url)
    connection = psycopg2.connect(url)
    try:
        with connection.cursor() as cursor:
            recovery.save_historical_result(cursor, odds if conflict == 'other_game' else canonical,
                801 if conflict == 'other_mlb_id' else 800,
                date(2025, 8, 2) if conflict == 'other_date' else date(2025, 8, 1),
                'Protected Home', 'Protected Away', 2, 1)
        connection.commit()
        result = execute(url, manifest)
        assert result['status'] == 'failed-before-write', result
        assert result['failure_phase'] == 'preflight'
        with connection.cursor() as cursor:
            cursor.execute('SELECT game_id,mlb_game_id,home_team FROM historical_games')
            assert cursor.fetchall() == [(odds if conflict == 'other_game' else canonical,
                                          801 if conflict == 'other_mlb_id' else 800, 'Protected Home')]
    finally:
        connection.close()


def test_second_game_failure_reports_first_committed_boxscore(recovery_database, monkeypatch):
    url, canonical, second = recovery_database
    connection = psycopg2.connect(url)
    with connection.cursor() as cursor:
        cursor.execute("INSERT INTO game_sources(game_id,source_name,external_game_id) VALUES(%s,'mlb_stats','801')", (second,))
    connection.commit(); connection.close()
    payload = json.loads(FIXTURE.read_text())
    event = deepcopy(payload['schedule']['dates'][0]['games'][0])
    event.update(gamePk=801)
    payload['schedule']['dates'][0]['games'].append(event)
    pinned = deepcopy(payload['games']['800'])
    pinned['game_pk'] = pinned['feed']['gamePk'] = 801
    payload['games']['801'] = pinned
    manifest = recovery.plan_recovery(
        recovery.RecoverySpecification(date(2025,8,1),(800,801),REVISION), payload,
        connection_factory=lambda: psycopg2.connect(url))
    original = repository.save_recovery_boxscore
    def fail_second(cursor, parsed):
        if parsed.game_id == second:
            raise RuntimeError('Synthetic second-game failure')
        original(cursor, parsed)
    monkeypatch.setattr(repository, 'save_recovery_boxscore', fail_second)
    result = execute(url, manifest)
    assert result['status'] == 'partial', result
    assert result['committed_results'] == [800,801]
    assert result['committed_boxscores'] == [800]
    assert result['synchronized_players'] == [100,200]
    assert result['failed_games'] == [801]
    assert counts(url, canonical) == (1,2,2,2)
    assert counts(url, second) == (1,0,0,0)


def test_conflicting_legacy_mlb_identity_preview_refused(recovery_database):
    url, canonical, odds = recovery_database
    connection = psycopg2.connect(url)
    with connection.cursor() as cursor:
        cursor.execute('UPDATE games SET mlb_game_id=801 WHERE game_id=%s', (canonical,))
    connection.commit(); connection.close()
    payload = json.loads(FIXTURE.read_text())
    with pytest.raises(ValueError):
        recovery.plan_recovery(
            recovery.RecoverySpecification(date(2025,8,1),(800,),REVISION),
            payload, connection_factory=lambda: psycopg2.connect(url))
    assert counts(url, canonical) == (0,0,0,0)


def test_identity_drift_after_result_commit_refused_by_boxscore_revalidation(recovery_database):
    url, canonical, odds = recovery_database
    manifest = plan(url)
    protected_before = evidence(url)
    protected_after_injection = []
    player_stat_tables = ('baseball_players', 'baseball_player_sources',
                          'team_game_statistics', 'player_game_pitching_statistics')
    def player_stat_evidence():
        connection = psycopg2.connect(url)
        try:
            with connection.cursor() as cursor:
                captured = {}
                for table in player_stat_tables:
                    cursor.execute(f'SELECT row_to_json(t) FROM {table} t')
                    captured[table] = sorted(recovery.canonical_json(r[0]) for r in cursor.fetchall())
                return captured
        finally:
            connection.close()
    players_stats_before = player_stat_evidence()

    class DriftAfterResultsCommit:
        def __init__(self):
            self.connection = psycopg2.connect(url)
            self.commits = 0

        def __getattr__(self, name):
            return getattr(self.connection, name)

        def commit(self):
            self.connection.commit()  # Actual maintained result txn commits first.
            self.commits += 1
            assert self.commits == 1, 'Boxscore transaction unexpectedly committed'
            # A separate connection proves the result is committed and that
            # released locks allow the controlled test-only identity drift.
            assert counts(url, canonical) == (1,0,0,0)
            assert evidence(url) == protected_before
            concurrent = psycopg2.connect(url)
            try:
                with concurrent.cursor() as cursor:
                    cursor.execute("SET LOCAL lock_timeout='1s'")
                    cursor.execute("UPDATE games SET game_date=game_date+interval '1 minute' WHERE game_id=%s", (canonical,))
                    assert cursor.rowcount == 1
                concurrent.commit()
            finally:
                concurrent.close()
            protected_after_injection.append(evidence(url))

    result = recovery.execute_recovery(manifest, manifest['manifest_sha256'],
        code_revision=REVISION, acknowledge_writes=True, connection_factory=DriftAfterResultsCommit)
    assert len(protected_after_injection) == 1
    assert result['status'] == 'partial', result
    assert result['committed_results'] == [800]
    assert result['committed_boxscores'] == result['synchronized_players'] == []
    assert result['failed_games'] == [800]
    assert result['failure_phase'] == 'boxscore'
    assert result['manifest_hash'] == manifest['manifest_sha256']
    assert result['uncertain_commits'] == []
    assert 'Canonical/source/team identity changed after approval' in result['error']
    assert counts(url, canonical) == (1,0,0,0)
    assert counts(url, odds) == (0,0,0,0)
    assert player_stat_evidence() == players_stats_before
    # The deliberate test drift is not a recovery mutation. All protected
    # evidence must remain byte-equivalent to the post-injection baseline.
    assert evidence(url) == protected_after_injection[0]
    for table in PROTECTED:
        if table != 'games':
            assert protected_after_injection[0][table] == protected_before[table]
