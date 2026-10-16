"""Read-only and rollback-only probes for a prepared, isolated PG16 case.

This module never installs migrations, resets, commits, issues knowledge, or
executes correction/retirement. The integration owner must explicitly enable a
prepared fixture. Parameterized assertions are scenario *components*, not claims
that all adverse cases in a T/N scenario have been proved.
The prediction-insert regression seeds synthetic rows only within its rollback.
"""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
import json
import os
import subprocess
import threading
import time

import psycopg2
import pytest


ROOT = Path(__file__).resolve().parents[2]
IMAGE = 'sha256:4b7183ac05f8ef417db21fd72d71047a4238340c261d3cc3ddb6d579ab5071ae'
PRODUCTION_SYSTEM = '7679523717466862168'
DATABASE = 'sportsmodel_test_arbitration210_36'
# Each tuple is a centrally managed disposable container, not a user-supplied DSN.
TARGETS = {
    'sportsmodel-arbitration-210-20261012-36-b': 55572,
    'sportsmodel-arbitration-210-20261012-36-c': 55574,
    'sportsmodel-arbitration-210-20261012-36-d': 55576,
    'sportsmodel-arbitration-210-20261012-36-e': 55578,
    'sportsmodel-arbitration-210-20261012-36-f': 55580,
    'sportsmodel-arbitration-210-20261012-36-g': 55582,
    'sportsmodel-arbitration-210-20261012-36-j': 55588,
    'sportsmodel-arbitration-210-20261012-36-k': 55590,
    'sportsmodel-arbitration-210-20261012-36-l': 55592,
    'sportsmodel-arbitration-210-20261012-36-m': 55594,
    'sportsmodel-arbitration-210-20261012-36-n': 55596,
    'sportsmodel-arbitration-210-20261012-36-o': 55598,
    'sportsmodel-arbitration-210-20261012-36-p': 55600,
    'sportsmodel-arbitration-210-20261012-36-q': 55602,
    'sportsmodel-arbitration-210-20261012-36-r': 55604,
    'sportsmodel-arbitration-210-20261012-36-s': 55606,
    'sportsmodel-arbitration-210-20261012-36-w': 55614,
    'sportsmodel-arbitration-210-20261012-36-x': 55616,
    'sportsmodel-arbitration-210-20261012-36-z': 55622,
    'sportsmodel-arbitration-210-20261012-36-ab': 55626,
}
ENABLED = os.getenv('SPORTSMODEL_ARBITRATION_DISPOSABLE_CONTAINER')
PUBLIC_DEFINER_ACL_EVIDENCE = []
pytestmark = pytest.mark.skipif(
    ENABLED not in TARGETS,
    reason='requires integration-owner enabled, centrally prepared arbitration210 PG16',
)


class PreparedCase:
    def __init__(self, name, password):
        self.name = name
        self.port = TARGETS[name]
        self._password = password
        self.roles = {kind: 'arbitration210_' + kind
                      for kind in ('reader', 'knowledge', 'operator', 'raw')}

    @contextmanager
    def session(self, principal='admin', isolation='READ COMMITTED'):
        user = 'postgres' if principal == 'admin' else self.roles[principal]
        connection = psycopg2.connect(
            host='127.0.0.1', port=self.port, dbname=DATABASE, user=user,
            password=self._password, connect_timeout=5,
            options='-c lock_timeout=1500ms -c statement_timeout=15000ms',
        )
        try:
            connection.set_session(readonly=True, isolation_level=isolation)
            with connection.cursor() as cursor:
                cursor.execute("SELECT current_database(),current_setting('server_version_num'),"
                               "current_setting('transaction_read_only')")
                database, version, readonly = cursor.fetchone()
                assert database == DATABASE and int(version) // 10000 == 16
                assert readonly == 'on'
            yield connection
        finally:
            connection.rollback()
            connection.close()

    def rows(self, statement, args=None, principal='admin'):
        with self.session(principal) as connection, connection.cursor() as cursor:
            cursor.execute(statement, args)
            return cursor.fetchall()

    def denial(self, statement, args=None, principal='reader', isolation='READ COMMITTED',
               sqlstates=None, message=None):
        with self.session(principal, isolation) as connection:
            with pytest.raises(psycopg2.Error) as refused:
                with connection.cursor() as cursor:
                    cursor.execute(statement, args)
                    if cursor.description:
                        cursor.fetchall()
            if sqlstates is not None:
                assert refused.value.pgcode in sqlstates
            if message is not None:
                assert message in str(refused.value)
            # No commit is possible, including when an unexpected privilege exists.
            connection.rollback()


@pytest.fixture(scope='module')
def prepared_case():
    """Positive container/storage/endpoint/server checks precede all test access."""
    assert ENABLED in TARGETS
    inspected = subprocess.run(['docker', 'inspect', ENABLED], check=True,
                               capture_output=True, timeout=30)
    item = json.loads(inspected.stdout)[0]
    assert item['Name'] == '/' + ENABLED
    assert item['Image'] == IMAGE
    assert item['Config']['Labels']['sportsmodel.verification'] == 'arbitration210'
    assert item['Mounts'] == []
    assert item['HostConfig']['Tmpfs'] == {'/var/lib/postgresql/data': 'rw'}
    assert item['NetworkSettings']['Ports']['5432/tcp'] == [
        dict(HostIp='127.0.0.1', HostPort=str(TARGETS[ENABLED]))]
    password = next(value.split('=', 1)[1] for value in item['Config']['Env']
                    if value.startswith('POSTGRES_PASSWORD='))
    case = PreparedCase(ENABLED, password)
    rows = case.rows("SELECT (pg_control_system()).system_identifier::text,"
                     "current_setting('data_directory'),pg_is_in_recovery()")
    assert len(rows) == 1
    system, directory, recovery = rows[0]
    assert system != PRODUCTION_SYSTEM and directory == '/var/lib/postgresql/data'
    assert recovery is False
    assert case.rows('SELECT version FROM public.schema_migrations ORDER BY version') == [
        (version,) for version in range(1, 37)]
    migration = ROOT / 'database/migrations/036_create_mlb_canonical_time_arbitration.sql'
    assert case.rows('SELECT filename,checksum FROM public.schema_migrations WHERE version=36') == [
        (migration.name, sha256(migration.read_text(encoding='utf-8-sig').encode()).hexdigest())
    ], 'Prepared fixture must contain the exact integrated frozen migration036'
    yield case
    case._password = None


@pytest.fixture(scope='module')
def committed_proof(prepared_case):
    rows = prepared_case.rows("SELECT to_jsonb(r),clock_timestamp() "
                              "FROM mlb036_private.knowledge_receipts r "
                              "ORDER BY receipt_id DESC LIMIT 1")
    assert len(rows) == 1, 'Fixture must have centrally committed X then Y'
    receipt, cutoff = rows[0]
    available = datetime.fromisoformat(receipt['available_at'])
    assert available.tzinfo is not None and available <= cutoff
    assert receipt['referenced_audit_ids'], 'An empty-ledger fixture is not this case'
    return receipt, cutoff


def certify(case, receipt, cutoff, purpose, params):
    return case.rows('SELECT mlb036_private.certified_data(%s,%s,%s,%s::jsonb)',
                     (receipt['receipt_id'], cutoff, purpose, json.dumps(params)),
                     principal='reader')[0][0]


def test_T37_committed_current_proof_certifies_corrected_start(prepared_case, committed_proof):
    receipt, cutoff = committed_proof
    packet = certify(prepared_case, receipt, cutoff, 'game', {'id': 26})
    assert packet['certification'] == 'MLB036_CERTIFIED'
    assert packet['receipt_id'] == receipt['receipt_id']
    assert packet['receipt_body_sha256'] == receipt['receipt_body_sha256']
    assert datetime.fromisoformat(packet['cutoff_time']) == cutoff
    assert packet['state_fingerprint'] == receipt['correction_state_fingerprint']
    assert len(packet['rows']) == 1
    assert datetime.fromisoformat(packet['rows'][0]['game_date']) == datetime(
        2026, 7, 12, 17, 40, tzinfo=timezone.utc)


EMPTY_READERS = [
    ('game', {'id': 2147483647}), ('h1_team', {'ids': []}),
    ('h1_starter', {'ids': []}), ('team_stats', {'id': 2147483647, 'limit': 200}),
    ('starter_stats', {'id': 2147483647, 'limit': 50}),
    ('bullpen_stats', {'id': 2147483647}),
    ('markets', {'id': 2147483647, 'include_live': False}),
    ('slate', {'start': '1900-01-01T00:00:00Z', 'end': '1900-01-02T00:00:00Z'}),
    ('earliest_start', {'start': '1900-01-01T00:00:00Z', 'end': '1900-01-02T00:00:00Z'}),
    ('feature_audit', {'start': '1900-01-01T00:00:00Z', 'end': '1900-01-02T00:00:00Z'}),
]


@pytest.mark.parametrize('purpose,params', EMPTY_READERS)
def test_T53_N07_even_empty_reader_requires_committed_locator(prepared_case, committed_proof,
                                                            purpose, params):
    _, cutoff = committed_proof
    prepared_case.denial('SELECT mlb036_private.certified_data(%s,%s,%s,%s::jsonb)',
                        (9223372036854775807, cutoff, purpose, json.dumps(params)),
                        message='committed receipt required')


@pytest.mark.parametrize('purpose,params', EMPTY_READERS)
@pytest.mark.parametrize('cutoff', [datetime(2026, 7, 12, tzinfo=timezone.utc),
                                   datetime(2026, 8, 1, tzinfo=timezone.utc),
                                   datetime(2026, 10, 1, tzinfo=timezone.utc)])
def test_T35_historical_cutoff_refuses_even_empty_results(prepared_case, committed_proof,
                                                         purpose, params, cutoff):
    receipt, _ = committed_proof
    assert cutoff < datetime.fromisoformat(receipt['available_at'])
    prepared_case.denial('SELECT mlb036_private.certified_data(%s,%s,%s,%s::jsonb)',
                        (receipt['receipt_id'], cutoff, purpose, json.dumps(params)),
                        message='unavailable/stale/changed')


@pytest.mark.parametrize('isolation', ['REPEATABLE READ', 'SERIALIZABLE'])
@pytest.mark.parametrize('function,principal', [('validate_knowledge', 'reader'),
                                               ('certified_data', 'reader')])
def test_T38_N05_certified_read_isolation_refuses(prepared_case, committed_proof,
                                                 isolation, function, principal):
    receipt, cutoff = committed_proof
    if function == 'validate_knowledge':
        statement = 'SELECT mlb036_private.validate_knowledge(%s,%s)'
        args = (receipt['receipt_id'], cutoff)
    else:
        statement = "SELECT mlb036_private.certified_data(%s,%s,'game','{\"id\":26}')"
        args = (receipt['receipt_id'], cutoff)
    prepared_case.denial(statement, args, principal=principal, isolation=isolation,
                        message='RC transaction required')


@pytest.mark.parametrize('guc', ['sportsmodel.identity_knowledge',
                               'sportsmodel.retirement_knowledge',
                               'sportsmodel.canonical_time_knowledge'])
def test_T40_N06_forged_backdated_guc_not_authority(prepared_case, committed_proof, guc):
    receipt, _ = committed_proof
    forged = dict(version=2, fingerprint=receipt['correction_state_fingerprint'],
                  available_at='1900-01-01T00:00:00Z', cutoff_time='2026-07-12T00:00:00Z',
                  receipt_id=receipt['receipt_id'], receipt_body_sha256=receipt['receipt_body_sha256'])
    with prepared_case.session('reader') as connection:
        with connection.cursor() as cursor:
            cursor.execute('SELECT set_config(%s,%s,true)', (guc, json.dumps(forged)))
            with pytest.raises(psycopg2.Error, match='unavailable/stale/changed'):
                cursor.execute('SELECT mlb036_private.validate_knowledge(%s,%s)',
                               (receipt['receipt_id'], datetime(2026, 7, 12, tzinfo=timezone.utc)))


RAW_BYPASSES = [
    'SELECT game_date FROM public.games WHERE game_id=26',
    'SELECT game_date FROM public.games LIMIT 0',
    'WITH exposed AS (SELECT game_date FROM public.games) SELECT * FROM exposed LIMIT 0',
    'SELECT * FROM public.odds_market_snapshots_effective LIMIT 0',
    'SELECT * FROM public.mlb_active_retired_identities LIMIT 0',
    'SELECT * FROM mlb036_private.knowledge_receipts LIMIT 0',
    'SELECT mlb036_private.state()',
    'SELECT mlb036_private.data_rows(\'game\',\'{"id":26}\',clock_timestamp())',
    'SELECT mlb036_private.issue_knowledge()',
    'SELECT mlb036_private.operator_state()',
    'SELECT mlb036_private.describe_target()',
    'SELECT mlb036_private.lock_exact()',
    'SELECT public.mlb_retirement_effective_markets()',
]


@pytest.mark.parametrize('statement', RAW_BYPASSES)
def test_T34_N07_runtime_raw_and_definer_bypasses_denied(prepared_case, statement):
    prepared_case.denial(statement, sqlstates={'42501'})


@pytest.mark.parametrize('principal', ['reader', 'knowledge', 'operator', 'raw'])
@pytest.mark.parametrize('table', ['arbitrations', 'arbitration_events', 'knowledge_receipts', 'authority'])
def test_T34_N12_private_table_dml_privileges_absent(prepared_case, principal, table):
    role = prepared_case.roles[principal]
    for privilege in ('INSERT', 'UPDATE', 'DELETE', 'TRUNCATE'):
        assert prepared_case.rows('SELECT has_table_privilege(%s,%s,%s)',
                                  (role, 'mlb036_private.' + table, privilege)) == [(False,)]


@pytest.mark.parametrize('principal', ['reader', 'knowledge', 'operator', 'raw'])
def test_N08_owner_membership_and_shadow_privileges_absent(prepared_case, principal):
    role = prepared_case.roles[principal]
    assert prepared_case.rows("SELECT rolcanlogin,rolsuper,rolcreatedb,rolcreaterole,"
                              "rolreplication,rolbypassrls FROM pg_roles WHERE rolname=%s",
                              (role,)) == [(True, False, False, False, False, False)]
    assert prepared_case.rows("SELECT has_database_privilege(%s,current_database(),'CREATE'),"
                              "has_database_privilege(%s,current_database(),'TEMP'),"
                              "has_schema_privilege(%s,'public','CREATE'),"
                              "has_schema_privilege(%s,'mlb036_private','CREATE')",
                              (role, role, role, role)) == [(False, False, False, False)]
    owners = prepared_case.rows("SELECT DISTINCT r.rolname FROM pg_roles r JOIN pg_namespace n "
                                "ON n.nspowner=r.oid WHERE n.nspname='mlb036_private'")
    assert owners
    for owner, in owners:
        assert prepared_case.rows("SELECT pg_has_role(%s,%s,'MEMBER')", (role, owner)) == [(False,)]
        prepared_case.denial('SET ROLE ' + owner, principal=principal, sqlstates={'42501'})


@pytest.mark.parametrize('principal', ['reader', 'knowledge', 'operator', 'raw'])
def test_N18_runtime_table_column_view_materialized_graph_closed(prepared_case, principal):
    role = prepared_case.roles[principal]
    exposed = prepared_case.rows("SELECT n.nspname,c.relname,c.relkind FROM pg_class c "
                                 "JOIN pg_namespace n ON n.oid=c.relnamespace "
                                 "WHERE n.nspname IN('public','mlb036_private') "
                                 "AND c.relkind IN('r','p','v','m','f') "
                                 "AND (has_table_privilege(%s,c.oid,'SELECT') OR "
                                 "has_any_column_privilege(%s,c.oid,'SELECT')) ORDER BY 1,2",
                                 (role, role))
    assert exposed == [], 'Any raw relation/column route requires explicit rejection'


def test_T41_N18_runtime_callable_private_allowlist_exact(prepared_case):
    role = prepared_case.roles['reader']
    callable_rows = prepared_case.rows("SELECT p.proname,p.provolatile,p.proparallel,p.prosecdef,p.proconfig "
                                      "FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
                                      "WHERE n.nspname='mlb036_private' AND has_function_privilege(%s,p.oid,'EXECUTE') "
                                      "ORDER BY p.proname", (role,))
    assert [row[0] for row in callable_rows] == [
        'certified_data', 'finish_run', 'insert_prediction', 'reserve_run', 'validate_knowledge']
    for _, volatility, parallel, definer, settings in callable_rows:
        assert (volatility, parallel, definer) == ('v', 'u', True)
        assert 'search_path=pg_catalog, mlb036_private, public, pg_temp' in settings


@pytest.mark.parametrize('principal', ['reader', 'knowledge', 'operator', 'raw'])
def test_T41_N18_public_security_definer_effective_callable_denied(prepared_case, principal):
    role = prepared_case.roles[principal]
    # Frozen functions can retain PUBLIC EXECUTE without being callable by this new
    # principal: effective access also requires public-schema USAGE. Preserve both
    # facts instead of equating the bare function ACL with complete graph closure.
    assert prepared_case.rows("SELECT has_schema_privilege(%s,'public','USAGE')", (role,)) == [(False,)]
    bare = prepared_case.rows("SELECT p.oid::regprocedure::text FROM pg_proc p "
                              "JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='public' "
                              "AND p.prosecdef AND has_function_privilege(%s,p.oid,'EXECUTE') "
                              "ORDER BY 1", (role,))
    PUBLIC_DEFINER_ACL_EVIDENCE.extend(dict(principal=principal, function=function, bare_execute_permission=True,
                                           schema_usage=False, effective_callable=False)
                                     for function, in bare)
    assert prepared_case.rows("SELECT p.oid::regprocedure::text FROM pg_proc p "
                              "JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='public' "
                              "AND p.prosecdef AND has_schema_privilege(%s,n.oid,'USAGE') "
                              "AND has_function_privilege(%s,p.oid,'EXECUTE') "
                              "ORDER BY 1", (role, role)) == []
    prepared_case.denial('SELECT public.mlb_identity_touch_fence(26)', principal=principal, sqlstates={'42501'})


def test_T49_frozen_migration_bytes_and_registered_inventory(prepared_case):
    expected = {
        '034_create_mlb_identity_dispositions.sql': '82D7840198A88780E24D264F929EA78D3EE6CE0BCCA08060C8D8E3767CB432D9',
        '035_create_mlb_legacy_identity_retirements.sql': 'BF9A6FAD169FDB62441289DED2E9E5664244E91F4C4AE3EEB3B9D27DE5233A47',
    }
    for filename, raw_hash in expected.items():
        path = ROOT / 'database' / 'migrations' / filename
        assert sha256(path.read_bytes()).hexdigest().upper() == raw_hash
        installed = prepared_case.rows('SELECT filename,checksum FROM public.schema_migrations WHERE version=%s',
                                       (int(filename[:3]),))
        assert installed == [(filename, sha256(path.read_text(encoding='utf-8-sig').encode()).hexdigest())]


def test_T50_new_audit_registry_has_no_games_foreign_keys(prepared_case):
    assert prepared_case.rows("SELECT c.conname FROM pg_constraint c JOIN pg_class r ON r.oid=c.conrelid "
                              "JOIN pg_namespace n ON n.oid=r.relnamespace "
                              "WHERE n.nspname='mlb036_private' AND c.contype='f' "
                              "AND c.confrelid='public.games'::regclass") == []
    assert prepared_case.rows("SELECT relname FROM pg_class WHERE relnamespace='mlb036_private'::regnamespace "
                              "AND relkind IN('r','p') ORDER BY relname") == [
        ('arbitration_events',), ('arbitrations',), ('authority',), ('knowledge_receipts',)]


@pytest.mark.parametrize('cutoff_kind', ['before_availability', 'future', 'positive_infinity', 'negative_infinity'])
def test_N10_invalid_cutoff_chronology_refuses(prepared_case, committed_proof, cutoff_kind):
    receipt, cutoff = committed_proof
    value = {'before_availability': datetime.fromisoformat(receipt['available_at']) - timedelta(microseconds=1),
             'future': cutoff + timedelta(days=1), 'positive_infinity': 'infinity',
             'negative_infinity': '-infinity'}[cutoff_kind]
    prepared_case.denial('SELECT mlb036_private.validate_knowledge(%s,%s)',
                        (receipt['receipt_id'], value), sqlstates={'P0001'})


@pytest.mark.parametrize('locator', [None, 0, -1, 9223372036854775807])
def test_T39_T40_missing_malformed_or_forged_locator_refuses(prepared_case, committed_proof, locator):
    _, cutoff = committed_proof
    prepared_case.denial('SELECT mlb036_private.validate_knowledge(%s,%s)',
                        (locator, cutoff), sqlstates={'P0001'})


@pytest.mark.parametrize('value', [None, True, False, 0, -1, -(2**63), 2**63-1,
                                  '', 'A', 'é', [], {}, [1, 'a', None],
                                  {'z': 1, 'é': 2, 'a': 3}])
def test_N11_SQL_Python_json_codec_golden_equivalence(prepared_case, value):
    from sportsmodel.database.mlb_canonical_time_codec import encode
    sql_hex = prepared_case.rows("SELECT encode(mlb036_private.codec(%s::jsonb),'hex')",
                                 (json.dumps(value, ensure_ascii=False),))[0][0]
    assert sql_hex == encode(value).hex()


@pytest.mark.parametrize('value', [0, 2**63, 2**64-1])
def test_N11_SQL_Python_unsigned_codec_boundary(prepared_case, value):
    from sportsmodel.database.mlb_canonical_time_codec import encode, Unsigned64
    actual = prepared_case.rows("SELECT encode(mlb036_private.unsigned_frame(%s::xid8),'hex')",
                                (str(value),))[0][0]
    assert actual == encode(Unsigned64(value)).hex()


@pytest.mark.parametrize('value', [datetime(1970, 1, 1, tzinfo=timezone.utc),
                                  datetime(1969, 12, 31, 23, 59, 59, 999999, tzinfo=timezone.utc),
                                  datetime(2026, 7, 12, 17, 40, 0, 123456, tzinfo=timezone.utc)])
def test_N11_SQL_Python_timestamp_codec_boundary(prepared_case, value):
    from sportsmodel.database.mlb_canonical_time_codec import encode
    actual = prepared_case.rows("SELECT encode(mlb036_private.timestamp_frame(%s),'hex')", (value,))[0][0]
    assert actual == encode(value).hex()


@pytest.mark.parametrize('payload', ['1.5', '1.0', '9223372036854775808', '-9223372036854775809'])
def test_N11_SQL_invalid_numeric_codec_refuses(prepared_case, payload):
    prepared_case.denial('SELECT mlb036_private.codec(%s::jsonb)', (payload,),
                        principal='admin', sqlstates={'P0001', '22003'})


@pytest.mark.parametrize('value', ['infinity', '-infinity'])
def test_N11_SQL_infinite_timestamp_codec_refuses(prepared_case, value):
    prepared_case.denial('SELECT mlb036_private.timestamp_frame(%s::timestamptz)',
                        (value,), principal='admin', sqlstates={'P0001'})


def test_N11_SQL_explicit_duplicate_object_keys_refuse(prepared_case):
    prepared_case.denial("SELECT mlb036_private.object_frame(ARRAY['a','a'],"
                        "ARRAY[mlb036_private.codec('1'),mlb036_private.codec('2')])",
                        principal='admin', sqlstates={'P0001'}, message='unique object fields')


def test_N11_SQL_nested_body_depth_refuses(prepared_case):
    prepared_case.denial('SELECT mlb036_private.codec(%s::jsonb)',
                        ('[' * 34 + '0' + ']' * 34,), principal='admin', sqlstates={'P0001'})


@pytest.mark.parametrize('purpose,params', [
    ('game', {'id': True}), ('game', {'id': '26'}), ('game', {'id': 0}),
    ('game', {'id': None}), ('game', {'id': 26, 'sql': 'SELECT 1'}),
    ('h1_team', {'ids': [26, 26]}), ('h1_team', {'ids': list(range(1, 34))}),
    ('h1_starter', {'ids': [True]}), ('team_stats', {'id': 1, 'limit': 201}),
    ('starter_stats', {'id': 1, 'limit': 51}), ('starter_stats', {'id': 1, 'limit': 0}),
    ('markets', {'id': 26, 'include_live': 'false'}),
    ('slate', {'start': '2026-07-12T00:00:00', 'end': '2026-07-13T00:00:00Z'}),
    ('slate', {'start': '2026-07-12T00:00:00Z', 'end': '2026-07-15T00:00:00Z'}),
    ('arbitrary_sql', {'sql': 'SELECT 1'}),
])
def test_T53_typed_reader_rejects_coercion_unknown_fields_and_unbounded_windows(
        prepared_case, committed_proof, purpose, params):
    receipt, cutoff = committed_proof
    prepared_case.denial('SELECT mlb036_private.certified_data(%s,%s,%s,%s::jsonb)',
                        (receipt['receipt_id'], cutoff, purpose, json.dumps(params)),
                        sqlstates={'P0001'})


@pytest.mark.parametrize('principal', ['reader', 'knowledge', 'operator', 'raw'])
def test_N12_runtime_private_sequences_have_no_privileges(prepared_case, principal):
    role = prepared_case.roles[principal]
    assert prepared_case.rows("SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                              "WHERE n.nspname='mlb036_private' AND c.relkind='S' "
                              "AND CASE WHEN c.relkind='S' "
                              "THEN has_sequence_privilege(%s,c.oid,'USAGE,SELECT,UPDATE') "
                              "ELSE false END", (role,)) == []


@pytest.mark.parametrize('principal', ['raw', 'knowledge'])
def test_T53_N18_raw_or_issuer_cannot_certify_time(prepared_case, committed_proof, principal):
    receipt, cutoff = committed_proof
    prepared_case.denial("SELECT mlb036_private.certified_data(%s,%s,'game','{\"id\":26}')",
                        (receipt['receipt_id'], cutoff), principal=principal, sqlstates={'42501'})


def test_T23_T41_exact_integrated_function_capabilities(prepared_case):
    from sportsmodel.database.mlb_canonical_time_repository import verify_capabilities
    with prepared_case.session() as connection, connection.cursor() as cursor:
        assert verify_capabilities(cursor) is True


def test_N08_security_definer_owner_and_public_default_privilege_closure(prepared_case):
    functions = prepared_case.rows("SELECT p.proname,r.rolcanlogin,r.rolsuper,r.rolbypassrls,p.proconfig "
                                    "FROM pg_proc p JOIN pg_roles r ON r.oid=p.proowner "
                                    "WHERE p.pronamespace='mlb036_private'::regnamespace AND p.prosecdef")
    assert functions
    for _, login, superuser, bypass, settings in functions:
        assert (login, superuser, bypass) == (False, False, False)
        assert 'search_path=pg_catalog, mlb036_private, public, pg_temp' in settings
    assert prepared_case.rows("SELECT p.proname FROM pg_proc p CROSS JOIN LATERAL "
                              "aclexplode(coalesce(p.proacl,acldefault('f',p.proowner))) acl "
                              "WHERE p.pronamespace='mlb036_private'::regnamespace "
                              "AND acl.grantee=0 AND acl.privilege_type='EXECUTE'") == []
    assert prepared_case.rows("SELECT d.defaclobjtype FROM pg_default_acl d CROSS JOIN LATERAL "
                              "aclexplode(d.defaclacl) acl WHERE d.defaclnamespace='mlb036_private'::regnamespace "
                              "AND d.defaclobjtype='f' AND acl.grantee=0 AND acl.privilege_type='EXECUTE'") == []


@pytest.mark.parametrize('raw', ['{"a":1,"a":2}', '{"x":{"a":1,"a":2}}',
                                '[{"a":1,"a":2}]', '{"a":1,"\\u0061":2}',
                                '1e0', '1E0', '1.0', '-1.0', '1.5'])
def test_N11_raw_codec_rejects_duplicate_keys_and_numeric_normalization(prepared_case, raw):
    prepared_case.denial('SELECT mlb036_private.codec_text(%s)', (raw,),
                        principal='admin', sqlstates={'P0001'})


@pytest.mark.parametrize('raw,value', [
    ('null', None), ('{"z":1,"a":2}', {'a': 2, 'z': 1}),
    ('{"é":"é","e":"e"}', {'é': 'é', 'e': 'e'}),
    ('[true,false,-9223372036854775808]', [True, False, -(2**63)]),
])
def test_N11_raw_codec_preserves_typed_order_and_unicode(prepared_case, raw, value):
    from sportsmodel.database.mlb_canonical_time_codec import encode
    actual = prepared_case.rows("SELECT encode(mlb036_private.codec_text(%s),'hex')", (raw,))[0][0]
    assert actual == encode(value).hex()


SEMANTIC_VECTORS = [
    {'old_start': '2026-07-12T17:41:00Z', 'new_start': '2026-07-12T17:40:00Z',
     'subject_start': '2026-07-12T17:40:00+00:00', 'officialDate': '2026-07-12',
     'delta_seconds': -60},
    {'writer_xid8': '18446744073709551615', 'issuer_xid8': 9223372036854775808,
     'available_at': '1969-12-31T23:59:59.999999Z', 'postmaster_started_at': '1970-01-01T00:00:00Z'},
    {'profile': '0' * 64, 'request_sha256': '1' * 64, 'identity034_digest': 'a' * 64,
     'artifact_sha256': 'f' * 64, 'audit_bytes': '000102ff'},
    {'policy': {'subject': 584, 'survivor': 26, 'game_pk': 900584, 'date': '2026-07-12'},
     'events': [{'event_id': 1, 'writer_xid8': '18446744073709551615',
                 'recorded_at': '2026-10-12T12:00:00.123456+00:00'}],
     'audits': ['000102ff', 'aabbcc'], 'fences': [{'game_id': 26, 'epoch': 12}],
     'target': {'available_at': None, 'system_identifier': '12345', 'name': 'é'}},
]


@pytest.mark.parametrize('value', SEMANTIC_VECTORS)
def test_N11_semantic_macro_SQL_Python_frame_equivalence(prepared_case, value):
    from sportsmodel.database.mlb_canonical_time_codec import encode, semantic_value
    actual = prepared_case.rows("SELECT encode(mlb036_private.semantic_frame(%s::jsonb),'hex')",
                                (json.dumps(value, ensure_ascii=False),))[0][0]
    assert actual == encode(semantic_value(value)).hex()


@pytest.mark.parametrize('value', [
    {'old_start': '2026-07-12T17:40:00'}, {'new_start': 'infinity'},
    {'available_at': '2026-07-12T24:00:00Z'}, {'recorded_at': '2026-07-12T17:40:00.1234567Z'},
    {'officialDate': '2026-02-30'}, {'writer_xid8': '-1'},
    {'issuer_xid8': '18446744073709551616'}, {'issuer_xid8': True},
    {'profile': 'A' * 64}, {'profile': '0' * 63}, {'projection_digest': 0},
    {'request_sha256': 'g' * 64}, {'audit_bytes': '0'}, {'audits': ['not-hex']},
])
def test_N11_semantic_macro_malformed_typed_fields_refuse(prepared_case, value):
    from sportsmodel.database.mlb_canonical_time_codec import CodecRefusal, encode, semantic_value
    with pytest.raises(CodecRefusal):
        encode(semantic_value(value))
    prepared_case.denial('SELECT mlb036_private.semantic_frame(%s::jsonb)',
                        (json.dumps(value),), principal='admin',
                        sqlstates={'P0001', '22003', '22P02', '22008'})


def test_N11_complete_current_state_macro_hash_independently_matches_python(prepared_case):
    from sportsmodel.database.mlb_canonical_time_codec import fingerprint, semantic_value
    state, sql_hash = prepared_case.rows('SELECT s,mlb036_private.state_fingerprint(s) '
                                         'FROM (SELECT mlb036_private.state() s) input')[0]
    expected = fingerprint('SPORTSMODEL:MLB036:CORRECTION_STATE:v1', semantic_value(state))
    assert sql_hash == expected


def test_N11_complete_committed_receipt_body_macro_hash_matches_python(prepared_case, committed_proof):
    from sportsmodel.database.mlb_canonical_time_codec import fingerprint, semantic_value
    receipt, _ = committed_proof
    body = {key: value for key, value in receipt.items() if key != 'receipt_body_sha256'}
    expected = fingerprint('SPORTSMODEL:MLB036:KNOWLEDGE_RECEIPT:v1', semantic_value(body))
    assert expected == receipt['receipt_body_sha256']
    assert prepared_case.rows('SELECT mlb036_private.receipt_hash(r) '
                              'FROM mlb036_private.knowledge_receipts r WHERE receipt_id=%s',
                              (receipt['receipt_id'],)) == [(expected,)]


@pytest.mark.parametrize('change', ['missing_field', 'unknown_field'])
def test_N11_current_state_macro_exact_field_schema(prepared_case, change):
    state = prepared_case.rows('SELECT mlb036_private.state()')[0][0]
    if change == 'missing_field':
        state.pop('audit_ids')
    else:
        state['unreviewed_field'] = 1
    prepared_case.denial('SELECT mlb036_private.state_fingerprint(%s::jsonb)',
                        (json.dumps(state),), principal='admin', sqlstates={'P0001'},
                        message='exact correction state fields')


@pytest.mark.parametrize('isolation', ['READ COMMITTED', 'REPEATABLE READ', 'SERIALIZABLE'])
def test_N05_run_reservation_and_completion_refuse_read_only_session(prepared_case,
                                                                  committed_proof, isolation):
    receipt, cutoff = committed_proof
    prepared_case.denial('SELECT mlb036_private.reserve_run(%s,%s,%s::jsonb)',
                        (receipt['receipt_id'], cutoff, '{}'), isolation=isolation,
                        message='reservation write transaction')
    prepared_case.denial('SELECT mlb036_private.finish_run(%s,%s,%s,%s,%s,%s::jsonb,%s)',
                        (receipt['receipt_id'], cutoff, '0' * 64, 2147483647, 'completed', '{}', None), isolation=isolation,
                        message='completion principal/transaction')
    prepared_case.denial('SELECT mlb036_private.insert_prediction(%s,%s,%s::jsonb)',
                        (receipt['receipt_id'], cutoff, '{}'),
                        isolation=isolation, message='dedicated certified prediction transaction')


@pytest.mark.parametrize('principal', ['raw', 'knowledge', 'operator'])
def test_N18_non_runtime_principals_cannot_reserve_or_complete_certified_runs(
        prepared_case, committed_proof, principal):
    receipt, cutoff = committed_proof
    prepared_case.denial('SELECT mlb036_private.reserve_run(%s,%s,%s::jsonb)',
                        (receipt['receipt_id'], cutoff, '{}'), principal=principal, sqlstates={'42501'})
    prepared_case.denial('SELECT mlb036_private.finish_run(%s,%s,%s,%s,%s,%s::jsonb,%s)',
                        (receipt['receipt_id'], cutoff, '0' * 64, 2147483647, 'completed', '{}', None),
                        principal=principal, sqlstates={'42501'})
    prepared_case.denial('SELECT mlb036_private.insert_prediction(%s,%s,%s::jsonb)',
                        (receipt['receipt_id'], cutoff, '{}'),
                        principal=principal, sqlstates={'42501'})


@pytest.mark.parametrize('container', ['list', 'object'])
def test_N11_raw_codec_cardinality_over_limit_refuses(prepared_case, container):
    if container == 'list':
        raw = '[' + ','.join('0' for _ in range(100001)) + ']'
    else:
        raw = '{' + ','.join('"k' + str(index) + '":0' for index in range(100001)) + '}'
    prepared_case.denial('SELECT mlb036_private.codec_text(%s)', (raw,),
                        principal='admin', sqlstates={'P0001'})


@pytest.mark.parametrize('kind', ['string', 'bytes'])
def test_N11_complete_frame_limit_includes_nine_byte_header(prepared_case, kind):
    from sportsmodel.database.mlb_canonical_time_codec import CodecRefusal, MAX_BODY, encode
    payload_size = MAX_BODY - 8  # Payload alone fits, but the complete frame does not.
    value = 'x' * payload_size if kind == 'string' else b'x' * payload_size
    with pytest.raises(CodecRefusal):
        encode(value)
    if kind == 'string':
        prepared_case.denial('SELECT mlb036_private.codec_text(%s)', ('"' + value + '"',),
                            principal='admin', sqlstates={'P0001'})
    else:
        prepared_case.denial('SELECT mlb036_private.frame(4,%s::bytea)', (value,),
                            principal='admin', sqlstates={'P0001'})


@pytest.mark.parametrize('keys,values', [(['a'], []), (['a', None], ['00', '00']),
                                        (['a'], [None])])
def test_N11_object_frame_mismatched_or_null_fields_refuse(prepared_case, keys, values):
    prepared_case.denial("SELECT mlb036_private.object_frame(%s::text[],"
                        "ARRAY(SELECT decode(v,'hex') FROM unnest(%s::text[]) v))",
                        (keys, values), principal='admin', sqlstates={'P0001'})


def test_N11_complete_audit_semantic_frame_independently_matches_python(prepared_case):
    from sportsmodel.database.mlb_canonical_time_codec import encode, semantic_value
    rows = prepared_case.rows("SELECT to_jsonb(a),encode(mlb036_private.audit_frame(a),'hex') "
                              "FROM mlb036_private.arbitrations a ORDER BY audit_id")
    assert rows, 'Requires a centrally committed synthetic correction audit'
    for audit, sql_hex in rows:
        # Mirror the reviewed noncircular semantic rule, without serializing metrics
        # as lossy numbers. Complete business snapshots remain stored and immutable;
        # the independently computed pre-business digest is a primary audit fact.
        primary = {key: value for key, value in audit.items()
                   if key not in ('post_state', 'post_business_sha256', 'pre_state')}
        primary['pre_state'] = audit['pre_state']['state']
        assert sql_hex == encode(semantic_value(primary)).hex()


@pytest.fixture(scope='module')
def protected_owners(prepared_case):
    schema_owner, read_owner, write_owner = prepared_case.rows(
        "SELECT n.nspowner::regrole::text,reader.proowner::regrole::text,writer.proowner::regrole::text "
        "FROM pg_namespace n CROSS JOIN pg_proc reader CROSS JOIN pg_proc writer "
        "WHERE n.nspname='mlb036_private' "
        "AND reader.oid='mlb036_private.certified_data(bigint,timestamptz,text,jsonb)'::regprocedure "
        "AND writer.oid='mlb036_private.correct_exact(jsonb,jsonb,text)'::regprocedure"
    )[0]
    assert len({schema_owner, read_owner, write_owner}) == 3
    for owner in (schema_owner, read_owner, write_owner):
        assert prepared_case.rows("SELECT rolcanlogin,rolsuper,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls "
                                  "FROM pg_roles WHERE rolname=%s", (owner,)) == [
            (False, False, False, False, False, False)]
    return dict(schema=schema_owner, reader=read_owner, writer=write_owner)


def test_N18_three_distinct_nonlogin_owner_responsibilities(prepared_case, protected_owners):
    read_owner = protected_owners['reader']
    write_owner = protected_owners['writer']
    readers = prepared_case.rows("SELECT p.proname,p.proowner::regrole::text FROM pg_proc p "
                                 "WHERE p.pronamespace='mlb036_private'::regnamespace "
                                 "AND p.proname IN('context','validate_knowledge','certified_data','post_correction_preview','inspect_knowledge','raw_case_snapshot') "
                                 "ORDER BY p.proname")
    assert len(readers) == 6 and all(owner == read_owner for _, owner in readers)
    writers = prepared_case.rows("SELECT p.proname,p.proowner::regrole::text FROM pg_proc p "
                                 "WHERE p.pronamespace='mlb036_private'::regnamespace "
                                 "AND p.proname IN('issue_knowledge','correct_exact','reserve_run','finish_run','insert_prediction','acquire_exact_gate') "
                                 "ORDER BY p.proname")
    assert len(writers) == 6 and all(owner == write_owner for _, owner in writers)


@pytest.mark.parametrize('principal', ['reader', 'knowledge', 'operator', 'raw'])
def test_N08_runtime_cannot_inherit_any_of_three_protected_owners(prepared_case, protected_owners, principal):
    role = prepared_case.roles[principal]
    for owner in protected_owners.values():
        assert prepared_case.rows("SELECT pg_has_role(%s,%s,'MEMBER')", (role, owner)) == [(False,)]
        prepared_case.denial('SET ROLE ' + owner, principal=principal, sqlstates={'42501'})


def test_N18_read_owner_has_no_table_or_column_dml(prepared_case, protected_owners):
    role = protected_owners['reader']
    assert prepared_case.rows("SELECT n.nspname,c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                              "WHERE n.nspname IN('public','mlb036_private') "
                              "AND CASE WHEN c.relkind IN('r','p','v','m','f') THEN "
                              "(has_table_privilege(%s,c.oid,'INSERT,UPDATE,DELETE,TRUNCATE') "
                              "OR has_any_column_privilege(%s,c.oid,'INSERT,UPDATE')) ELSE false END "
                              "ORDER BY 1,2", (role, role)) == []


def test_N18_write_owner_only_game_date_update_not_broad_game_dml(prepared_case, protected_owners):
    role = protected_owners['writer']
    assert prepared_case.rows("SELECT has_table_privilege(%s,'public.games','INSERT,DELETE,TRUNCATE'),"
                              "has_table_privilege(%s,'public.games','UPDATE'),"
                              "has_column_privilege(%s,'public.games','game_date','UPDATE')",
                              (role, role, role)) == [(False, False, True)]
    assert prepared_case.rows("SELECT a.attname FROM pg_attribute a "
                              "WHERE a.attrelid='public.games'::regclass AND a.attnum>0 AND NOT a.attisdropped "
                              "AND a.attname<>'game_date' AND has_column_privilege(%s,a.attrelid,a.attnum,'UPDATE') "
                              "ORDER BY a.attname", (role,)) == []


@pytest.mark.parametrize('principal,expected', [
    ('raw', ['raw_case_snapshot']),
    ('knowledge', ['inspect_knowledge', 'issue_knowledge']),
    ('operator', ['acquire_exact_gate', 'correct_exact', 'describe_target', 'lock_exact',
                  'operator_state', 'post_correction_preview']),
])
def test_N18_nonruntime_private_callable_allowlist_exact(prepared_case, principal, expected):
    assert prepared_case.rows("SELECT p.proname FROM pg_proc p "
                              "WHERE p.pronamespace='mlb036_private'::regnamespace "
                              "AND has_function_privilege(%s,p.oid,'EXECUTE') ORDER BY p.proname",
                              (prepared_case.roles[principal],)) == [(name,) for name in expected]


def test_T53_N18_raw_case_scope_is_explicitly_uncertified(prepared_case):
    result = prepared_case.rows('SELECT mlb036_private.raw_case_snapshot()', principal='raw')[0][0]
    assert result['label'] == 'RAW_FORENSIC'
    assert result['historically_certified'] is False
    assert isinstance(result['business'], dict)


def test_N14_readonly_knowledge_inspection_resolves_current_committed_receipt(prepared_case, committed_proof):
    receipt, _ = committed_proof
    result = prepared_case.rows('SELECT mlb036_private.inspect_knowledge()', principal='knowledge')[0][0]
    assert result['status'] == 'CURRENT_COMMITTED_RECEIPT'
    assert result['retry_authorized'] is False
    assert result['receipt']['receipt_id'] == receipt['receipt_id']
    assert result['receipt']['receipt_body_sha256'] == receipt['receipt_body_sha256']


def test_N11_complete_business_digests_are_independent_framed_values(prepared_case):
    from sportsmodel.database.mlb_canonical_time_codec import business_value, fingerprint
    rows = prepared_case.rows("SELECT pre_state->'business',pre_business_sha256,post_business_sha256 "
                              "FROM mlb036_private.arbitrations ORDER BY audit_id")
    assert len(rows) == 1
    before, before_sha, after_sha = rows[0]
    after = prepared_case.rows('SELECT mlb036_private.business_snapshot()')[0][0]
    assert fingerprint('SPORTSMODEL:MLB036:BUSINESS_STATE:v1', business_value(before)) == before_sha
    assert fingerprint('SPORTSMODEL:MLB036:BUSINESS_STATE:v1', business_value(after)) == after_sha
    assert before_sha != after_sha


@pytest.mark.parametrize('change', ['missing', 'unknown', 'wrong-history-type'])
def test_N11_business_snapshot_exact_top_schema_refuses(prepared_case, change):
    value = prepared_case.rows('SELECT mlb036_private.business_snapshot()')[0][0]
    if change == 'missing':
        del value['sportsbooks']
    elif change == 'unknown':
        value['unknown'] = []
    else:
        value['history'] = {}
    prepared_case.denial('SELECT mlb036_private.business_hash(%s::jsonb)',
                         (json.dumps(value),), principal='admin')


@pytest.mark.parametrize('principal', ['reader', 'knowledge', 'operator', 'raw'])
def test_N18_non_catalog_auxiliary_namespaces_and_unsafe_builtins_unavailable(prepared_case, principal):
    role = prepared_case.roles[principal]
    assert prepared_case.rows("SELECT n.nspname FROM pg_namespace n "
        "WHERE n.nspname NOT IN('pg_catalog','information_schema','mlb036_private') "
        "AND n.nspname NOT LIKE 'pg_temp_%%' AND n.nspname NOT LIKE 'pg_toast%%' "
        "AND has_schema_privilege(%s,n.oid,'USAGE')", (role,)) == []
    assert prepared_case.rows("SELECT p.oid::regprocedure::text FROM pg_proc p "
        "JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='pg_catalog' "
        "AND has_function_privilege(%s,p.oid,'EXECUTE') "
        "AND NOT EXISTS(SELECT 1 FROM aclexplode(coalesce(p.proacl,acldefault('f',p.proowner))) acl "
        "WHERE acl.grantee=0 AND acl.privilege_type='EXECUTE')", (role,)) == []
    assert prepared_case.rows("SELECT r.rolname FROM pg_roles r WHERE r.rolname<>%s "
        "AND pg_has_role(%s,r.oid,'MEMBER')", (role, role)) == []


@pytest.mark.parametrize('mlb_game_id', [9200100, 9200101])
def test_prediction_insert_varchar_source_array_matches_exact_text_identity(
        prepared_case, committed_proof, mlb_game_id):
    """Exercise the real guard, not a mock/static assertion of the SQL cast."""
    before = prepared_case.rows(
        'SELECT (SELECT count(*) FROM public.moneyline_prediction_runs),'
        '(SELECT count(*) FROM public.moneyline_game_predictions),'
        '(SELECT count(*) FROM public.games WHERE game_id=900100)')
    connection = psycopg2.connect(
        host='127.0.0.1', port=prepared_case.port, dbname=DATABASE,
        user='postgres', password=prepared_case._password, connect_timeout=5,
        options='-c lock_timeout=1500ms -c statement_timeout=15000ms')
    connection.set_session(readonly=False, isolation_level='READ COMMITTED')
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT home_team_id,away_team_id FROM public.games WHERE game_id=26')
            home, away = cursor.fetchone()
            cursor.execute("SELECT clock_timestamp()+interval'1 hour'")
            start = cursor.fetchone()[0]
            cursor.execute("INSERT INTO public.games(game_id,game_date,home_team_id,away_team_id,doubleheader_status,game_number) VALUES(900100,%s,%s,%s,'single',1)", (start, home, away))
            cursor.execute("INSERT INTO public.game_sources(game_source_id,game_id,source_name,external_game_id) VALUES(900100,900100,'mlb_stats','9200100')")
            cursor.execute("SELECT pg_typeof(array_agg(external_game_id))::text FROM public.game_sources WHERE game_id=900100")
            assert cursor.fetchone() == ('character varying[]',)
            cursor.execute("SELECT clock_timestamp(),(%s::timestamptz AT TIME ZONE 'America/Los_Angeles')::date", (start,))
            cutoff, target_date = cursor.fetchone()
            receipt, _ = committed_proof
            cursor.execute('SET SESSION AUTHORIZATION arbitration210_reader')
            request = dict(target_date=str(target_date), run_type='preview',
                model_version='SYNTHETIC_GUARD_ONLY', feature_schema_version='SYNTHETIC',
                model_artifact_sha256='0' * 64, model_training_cutoff=None)
            cursor.execute('SELECT mlb036_private.reserve_run(%s,%s,%s::jsonb)',
                           (receipt['receipt_id'], cutoff, json.dumps(request)))
            run_id = cursor.fetchone()[0]
            prediction = dict(moneyline_prediction_run_id=run_id, game_id=900100,
                mlb_game_id=mlb_game_id, game_start_time=start.isoformat(),
                prediction_time=cutoff.isoformat(), home_team_id=home, away_team_id=away,
                home_starting_pitcher_id=None, away_starting_pitcher_id=None,
                home_starting_pitcher_mlb_id=None, away_starting_pitcher_mlb_id=None,
                home_starter_features_available=False, away_starter_features_available=False,
                starter_coverage='none', missing_raw_value_count=0, home_win_probability=0.6,
                away_win_probability=0.4, predicted_team_id=home, predicted_probability=0.6)
            statement = 'SELECT mlb036_private.insert_prediction(%s,%s,%s::jsonb)'
            args = (receipt['receipt_id'], cutoff, json.dumps(prediction))
            if mlb_game_id == 9200100:
                cursor.execute(statement, args)
                assert cursor.fetchone()[0] > 0
                cursor.execute('SET CONSTRAINTS ALL IMMEDIATE')
            else:
                with pytest.raises(psycopg2.Error) as refused:
                    cursor.execute(statement, args)
                assert refused.value.pgcode == 'P0001'
                assert 'exact canonical prediction identity/cutoff required' in str(refused.value)
    finally:
        connection.rollback()
        connection.close()
    assert prepared_case.rows(
        'SELECT (SELECT count(*) FROM public.moneyline_prediction_runs),'
        '(SELECT count(*) FROM public.moneyline_game_predictions),'
        '(SELECT count(*) FROM public.games WHERE game_id=900100)') == before


@pytest.mark.parametrize('case', ['bound', 'cross_date_empty', 'empty_zero',
    'wrong_game_same_date', 'late_target', 'bound_start_mismatch', 'bound_source_mismatch',
    'deferred_unbound', 'post_finalize_attach'])
def test_prediction_requires_preexisting_immutable_run_slate_member(
        prepared_case, committed_proof, case):
    before = prepared_case.rows(
        'SELECT (SELECT count(*) FROM public.moneyline_prediction_runs),'
        '(SELECT count(*) FROM public.moneyline_game_predictions),'
        '(SELECT count(*) FROM public.games WHERE game_id=900100)')
    connection = psycopg2.connect(host='127.0.0.1', port=prepared_case.port,
        dbname=DATABASE, user='postgres', password=prepared_case._password,
        connect_timeout=5, options='-c lock_timeout=1500ms -c statement_timeout=15000ms')
    connection.set_session(readonly=False, isolation_level='READ COMMITTED')
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT home_team_id,away_team_id FROM public.games WHERE game_id=26')
            home, away = cursor.fetchone()
            cursor.execute("SELECT clock_timestamp()+interval'1 hour'")
            start = cursor.fetchone()[0]
            def seed(gid, game_start, pk):
                cursor.execute("INSERT INTO public.games(game_id,game_date,home_team_id,away_team_id,doubleheader_status,game_number) VALUES(%s,%s,%s,%s,'single',1)", (gid, game_start, home, away))
                cursor.execute("INSERT INTO public.game_sources(game_source_id,game_id,source_name,external_game_id) VALUES(%s,%s,'mlb_stats',%s)", (gid, gid, str(pk)))
            if case != 'late_target':
                seed(900100, start, 9200100)
            cursor.execute("SELECT clock_timestamp(),(%s::timestamptz AT TIME ZONE 'America/Los_Angeles')::date", (start,))
            cutoff, target_date = cursor.fetchone()
            if case in ('cross_date_empty', 'empty_zero', 'deferred_unbound', 'post_finalize_attach'):
                target_date -= timedelta(days=1)
            receipt, _ = committed_proof
            cursor.execute('SET SESSION AUTHORIZATION arbitration210_reader')
            request = dict(target_date=str(target_date), run_type='preview',
                model_version='SYNTHETIC_GUARD_ONLY', feature_schema_version='SYNTHETIC',
                model_artifact_sha256='0' * 64, model_training_cutoff=None)
            cursor.execute('SELECT mlb036_private.reserve_run(%s,%s,%s::jsonb)',
                (receipt['receipt_id'], cutoff, json.dumps(request)))
            run_id = cursor.fetchone()[0]
            cursor.execute('RESET SESSION AUTHORIZATION')
            cursor.execute('SELECT to_jsonb(r),(SELECT count(*) FROM mlb036_private.knowledge_receipts) FROM public.moneyline_prediction_runs r WHERE moneyline_prediction_run_id=%s', (run_id,))
            admitted, receipt_count = cursor.fetchone()
            gid, pk = 900100, 9200100
            if case == 'late_target':
                assert admitted['canonical_time_knowledge']['target_state'] == []
                seed(gid, start, pk)
            elif case == 'wrong_game_same_date':
                gid, pk = 900101, 9200101
                seed(gid, start, pk)
            prediction = dict(moneyline_prediction_run_id=run_id, game_id=gid,
                mlb_game_id=pk, game_start_time=start.isoformat(), prediction_time=cutoff.isoformat(),
                home_team_id=home, away_team_id=away, home_starting_pitcher_id=None,
                away_starting_pitcher_id=None, home_starting_pitcher_mlb_id=None,
                away_starting_pitcher_mlb_id=None, home_starter_features_available=False,
                away_starter_features_available=False, starter_coverage='none', missing_raw_value_count=0,
                home_win_probability=0.6, away_win_probability=0.4, predicted_team_id=home, predicted_probability=0.6)
            if case == 'bound_start_mismatch':
                prediction['game_start_time'] = (start + timedelta(seconds=1)).isoformat()
            elif case == 'bound_source_mismatch':
                prediction['mlb_game_id'] += 1
            cursor.execute('SET SESSION AUTHORIZATION arbitration210_reader')
            def finish_zero():
                cursor.execute('SELECT mlb036_private.finish_run(%s,%s,%s,%s,\'completed\',%s::jsonb,NULL)',
                    (receipt['receipt_id'], cutoff, receipt['receipt_body_sha256'], run_id,
                     json.dumps(dict(games_received=0, predictions_created=0, games_skipped=0))))
            if case in ('empty_zero', 'post_finalize_attach'):
                assert admitted['canonical_time_knowledge']['target_state'] == []
                finish_zero()
            if case != 'empty_zero':
                if case == 'deferred_unbound':
                    cursor.execute('SET CONSTRAINTS ALL DEFERRED')
                cursor.execute('SAVEPOINT prediction_attempt')
                statement = 'SELECT mlb036_private.insert_prediction(%s,%s,%s::jsonb)'
                args = (receipt['receipt_id'], cutoff, json.dumps(prediction))
                if case == 'bound':
                    cursor.execute(statement, args)
                    assert cursor.fetchone()[0] > 0
                else:
                    with pytest.raises(psycopg2.Error) as refused:
                        cursor.execute(statement, args)
                    assert refused.value.pgcode == 'P0001'
                    if case in ('cross_date_empty', 'wrong_game_same_date', 'late_target', 'deferred_unbound'):
                        assert 'prediction target outside immutable admitted slate' in str(refused.value)
                    cursor.execute('ROLLBACK TO SAVEPOINT prediction_attempt')
            cursor.execute('RESET SESSION AUTHORIZATION')
            cursor.execute('SET CONSTRAINTS ALL IMMEDIATE')
            cursor.execute('SELECT to_jsonb(r),(SELECT count(*) FROM public.moneyline_game_predictions p WHERE p.moneyline_prediction_run_id=%s),(SELECT count(*) FROM mlb036_private.knowledge_receipts) FROM public.moneyline_prediction_runs r WHERE r.moneyline_prediction_run_id=%s', (run_id, run_id))
            after, predictions, after_receipts = cursor.fetchone()
            assert after_receipts == receipt_count
            assert after['canonical_time_knowledge'] == admitted['canonical_time_knowledge']
            assert predictions == (1 if case == 'bound' else 0)
            if case not in ('empty_zero', 'post_finalize_attach'):
                assert after == admitted
            else:
                assert after['status'] == 'completed'
    finally:
        connection.rollback()
        connection.close()
    assert prepared_case.rows(
        'SELECT (SELECT count(*) FROM public.moneyline_prediction_runs),'
        '(SELECT count(*) FROM public.moneyline_game_predictions),'
        '(SELECT count(*) FROM public.games WHERE game_id=900100)') == before


@pytest.mark.parametrize('change', ['unchanged', 'retime', 'restore', 'fence',
    'stale_receipt', 'topology', 'source', 'orientation', 'cutoff_swap', 'receipt_swap',
    'runtime_direct_finalize', 'owner_direct_finalize'])
def test_run_completion_preserves_original_target_and_monotonic_fence(
        prepared_case, committed_proof, change):
    """Real admission/completion; all rows remain synthetic and rollback-only."""
    connection = psycopg2.connect(host='127.0.0.1', port=prepared_case.port,
        dbname=DATABASE, user='postgres', password=prepared_case._password,
        connect_timeout=5, options='-c lock_timeout=1500ms -c statement_timeout=15000ms')
    connection.set_session(readonly=False, isolation_level='READ COMMITTED')
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT home_team_id,away_team_id FROM public.games WHERE game_id=26')
            home, away = cursor.fetchone()
            cursor.execute("SELECT clock_timestamp()+interval'1 hour'")
            start = cursor.fetchone()[0]
            cursor.execute("INSERT INTO public.games(game_id,game_date,home_team_id,away_team_id,doubleheader_status,game_number) VALUES(900100,%s,%s,%s,'single',1)", (start, home, away))
            cursor.execute("INSERT INTO public.game_sources(game_source_id,game_id,source_name,external_game_id) VALUES(900100,900100,'mlb_stats','9200100')")
            cursor.execute("SELECT clock_timestamp(),(%s::timestamptz AT TIME ZONE 'America/Los_Angeles')::date", (start,))
            cutoff, target_date = cursor.fetchone()
            receipt, _ = committed_proof
            cursor.execute('SET SESSION AUTHORIZATION arbitration210_reader')
            request = dict(target_date=str(target_date), run_type='preview',
                model_version='SYNTHETIC_GUARD_ONLY', feature_schema_version='SYNTHETIC',
                model_artifact_sha256='0' * 64, model_training_cutoff=None)
            cursor.execute('SELECT mlb036_private.reserve_run(%s,%s,%s::jsonb)',
                (receipt['receipt_id'], cutoff, json.dumps(request)))
            run_id = cursor.fetchone()[0]
            prediction = dict(moneyline_prediction_run_id=run_id, game_id=900100,
                mlb_game_id=9200100, game_start_time=start.isoformat(), prediction_time=cutoff.isoformat(),
                home_team_id=home, away_team_id=away, home_starting_pitcher_id=None,
                away_starting_pitcher_id=None, home_starting_pitcher_mlb_id=None,
                away_starting_pitcher_mlb_id=None, home_starter_features_available=False,
                away_starter_features_available=False, starter_coverage='none', missing_raw_value_count=0,
                home_win_probability=0.6, away_win_probability=0.4, predicted_team_id=home, predicted_probability=0.6)
            cursor.execute('SELECT mlb036_private.insert_prediction(%s,%s,%s::jsonb)',
                (receipt['receipt_id'], cutoff, json.dumps(prediction)))
            prediction_id = cursor.fetchone()[0]
            cursor.execute('RESET SESSION AUTHORIZATION')
            def retained():
                cursor.execute('SELECT to_jsonb(r),to_jsonb(p),(SELECT count(*) FROM mlb036_private.knowledge_receipts) FROM public.moneyline_prediction_runs r JOIN public.moneyline_game_predictions p USING(moneyline_prediction_run_id) WHERE p.moneyline_game_prediction_id=%s', (prediction_id,))
                return cursor.fetchone()
            original = retained()
            cursor.execute('SELECT epoch FROM public.mlb_game_identity_write_fences WHERE game_id=900100')
            assert cursor.fetchone() == (2,)
            if change in ('retime', 'restore'):
                cursor.execute("UPDATE public.games SET game_date=game_date+interval'60 seconds' WHERE game_id=900100")
                if change == 'restore':
                    cursor.execute('UPDATE public.games SET game_date=%s WHERE game_id=900100', (start,))
                cursor.execute('SELECT epoch FROM public.mlb_game_identity_write_fences WHERE game_id=900100')
                assert cursor.fetchone() == ((4 if change == 'restore' else 3),)
            elif change in ('fence', 'stale_receipt'):
                cursor.execute('UPDATE public.mlb_game_identity_write_fences SET epoch=epoch+1 WHERE game_id=%s', (26 if change == 'stale_receipt' else 900100,))
            elif change == 'topology':
                cursor.execute('UPDATE public.mlb_identity_topology_fence SET epoch=epoch+1 WHERE singleton')
            elif change == 'source':
                cursor.execute("UPDATE public.game_sources SET external_game_id='9200101' WHERE game_id=900100 AND source_name='mlb_stats'")
            elif change == 'orientation':
                cursor.execute('UPDATE public.games SET home_team_id=away_team_id,away_team_id=home_team_id WHERE game_id=900100')
            cursor.execute('SET SESSION AUTHORIZATION arbitration210_reader')
            statement = 'SELECT mlb036_private.finish_run(%s,%s,%s,%s,\'completed\',%s::jsonb,NULL)'
            args = (receipt['receipt_id'] + (1 if change == 'receipt_swap' else 0),
                cutoff + (timedelta(microseconds=1) if change == 'cutoff_swap' else timedelta()),
                receipt['receipt_body_sha256'], run_id,
                json.dumps(dict(games_received=1, predictions_created=1, games_skipped=0)))
            if change in ('runtime_direct_finalize', 'owner_direct_finalize'):
                if change == 'owner_direct_finalize':
                    cursor.execute('RESET SESSION AUTHORIZATION')
                statement = "UPDATE public.moneyline_prediction_runs SET status='completed',completed_at=clock_timestamp(),games_received=1,predictions_created=1 WHERE moneyline_prediction_run_id=%s"
                args = (run_id,)
            cursor.execute('SAVEPOINT completion_attempt')
            if change == 'unchanged':
                cursor.execute(statement, args)
            else:
                with pytest.raises(psycopg2.Error) as refused:
                    cursor.execute(statement, args)
                assert refused.value.pgcode == ('42501' if change == 'runtime_direct_finalize' else 'P0001')
                cursor.execute('ROLLBACK TO SAVEPOINT completion_attempt')
            cursor.execute('RESET SESSION AUTHORIZATION')
            cursor.execute('SET CONSTRAINTS ALL IMMEDIATE')
            after = retained()
            if change == 'unchanged':
                assert after[0]['status'] == 'completed'
                assert after[0]['canonical_time_knowledge'] == original[0]['canonical_time_knowledge']
                assert after[1:] == original[1:]
            else:
                assert after == original, 'Refusal or deferred checking changed admission evidence'
    finally:
        connection.rollback()
        connection.close()


@pytest.mark.parametrize('order', ['finish_commits', 'finish_aborts', 'insert_commits', 'insert_aborts'])
def test_terminal_run_admission_serializes_with_completion(prepared_case, committed_proof, order):
    """Actual server lock barrier; synthetic controls retained, no blind retry."""
    def connect(principal='reader', tag='ARBITRATION210_RUN_RACE'):
        connection = psycopg2.connect(host='127.0.0.1', port=prepared_case.port,
            dbname=DATABASE, user='postgres' if principal == 'admin' else prepared_case.roles[principal],
            password=prepared_case._password, application_name=tag, connect_timeout=5,
            options='-c lock_timeout=8000ms -c statement_timeout=15000ms')
        connection.set_session(readonly=False, isolation_level='READ COMMITTED')
        return connection
    def committed_call(sql, args):
        connection = connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(sql, args)
                value = cursor.fetchone()[0]
            connection.commit()
            return value
        finally:
            connection.rollback()
            connection.close()
    maximum = prepared_case.rows('SELECT coalesce(max(game_id),0) FROM public.games')[0][0]
    base = max(900300, maximum + 10)
    assert base < 1900000
    target_date = datetime(2030, 1, 3, 20, tzinfo=timezone.utc) + timedelta(days=(base - 900300) // 10)
    home, away = prepared_case.rows('SELECT home_team_id,away_team_id FROM public.games WHERE game_id=26')[0]
    setup = connect('admin')
    try:
        with setup.cursor() as cursor:
            for gid in (base, base + 1):
                cursor.execute("INSERT INTO public.games(game_id,game_date,home_team_id,away_team_id,doubleheader_status,game_number) VALUES(%s,%s,%s,%s,'single',1)", (gid, target_date, home, away))
                cursor.execute("INSERT INTO public.game_sources(game_source_id,game_id,source_name,external_game_id) VALUES(%s,%s,'mlb_stats',%s)", (gid, gid, str(gid + 1000000)))
        setup.commit()
    finally:
        setup.rollback()
        setup.close()
    receipt, _ = committed_proof
    cutoff = prepared_case.rows('SELECT clock_timestamp()')[0][0]
    request = dict(target_date=str(target_date.date()), run_type='preview',
        model_version='SYNTHETIC_GUARD_ONLY', feature_schema_version='SYNTHETIC',
        model_artifact_sha256='0' * 64, model_training_cutoff=None)
    run_id = committed_call('SELECT mlb036_private.reserve_run(%s,%s,%s::jsonb)',
        (receipt['receipt_id'], cutoff, json.dumps(request)))
    def prediction(gid):
        return dict(moneyline_prediction_run_id=run_id, game_id=gid, mlb_game_id=gid + 1000000,
            game_start_time=target_date.isoformat(), prediction_time=cutoff.isoformat(),
            home_team_id=home, away_team_id=away, home_starting_pitcher_id=None,
            away_starting_pitcher_id=None, home_starting_pitcher_mlb_id=None,
            away_starting_pitcher_mlb_id=None, home_starter_features_available=False,
            away_starter_features_available=False, starter_coverage='none', missing_raw_value_count=0,
            home_win_probability=.6, away_win_probability=.4, predicted_team_id=home, predicted_probability=.6)
    insert_sql = 'SELECT mlb036_private.insert_prediction(%s,%s,%s::jsonb)'
    committed_call(insert_sql, (receipt['receipt_id'], cutoff, json.dumps(prediction(base))))
    original = prepared_case.rows('SELECT canonical_time_knowledge FROM public.moneyline_prediction_runs WHERE moneyline_prediction_run_id=%s', (run_id,))[0][0]
    second_args = (receipt['receipt_id'], cutoff, json.dumps(prediction(base + 1)))
    finish_sql = 'SELECT mlb036_private.finish_run(%s,%s,%s,%s,\'completed\',%s::jsonb,NULL)'
    def finish_args(predictions):
        return (receipt['receipt_id'], cutoff, receipt['receipt_body_sha256'], run_id,
                json.dumps(dict(games_received=2, predictions_created=predictions, games_skipped=2-predictions)))
    main = connect(tag='ARBITRATION210_RACE_HOLDER')
    done = threading.Event()
    result = {}
    thread = None
    finishing_first = order.startswith('finish')
    def waiting_mutation():
        connection = connect(tag='ARBITRATION210_RACE_WAITER')
        try:
            with connection.cursor() as cursor:
                cursor.execute(insert_sql if finishing_first else finish_sql,
                    second_args if finishing_first else finish_args(2 if order == 'insert_commits' else 1))
                cursor.fetchone()
                cursor.execute('SET CONSTRAINTS ALL IMMEDIATE')
            if not finishing_first:
                connection.commit()
            result['status'] = 'ADMITTED'
        except psycopg2.Error as error:
            result.update(status='REFUSED', sqlstate=error.pgcode, message=str(error).splitlines()[0])
        finally:
            connection.rollback()
            connection.close()
            done.set()
    try:
        with main.cursor() as cursor:
            cursor.execute('SELECT pg_backend_pid()')
            holder_pid = cursor.fetchone()[0]
            cursor.execute(finish_sql if finishing_first else insert_sql,
                finish_args(1) if finishing_first else second_args)
            cursor.fetchone()
        thread = threading.Thread(target=waiting_mutation, daemon=True)
        thread.start()
        deadline = time.monotonic() + 5
        barrier = None
        while time.monotonic() < deadline and not done.is_set():
            observed = prepared_case.rows("SELECT pid,wait_event_type,pg_blocking_pids(pid) FROM pg_stat_activity WHERE application_name='ARBITRATION210_RACE_WAITER'")
            if observed and observed[0][1] == 'Lock' and holder_pid in observed[0][2]:
                barrier = observed[0]
                break
            done.wait(.01)
        assert barrier is not None, 'Require PostgreSQL lock evidence, not a guessed delay'
        if order.endswith('commits'):
            main.commit()
        else:
            main.rollback()
        assert done.wait(10)
        thread.join(1)
        if order == 'finish_commits':
            assert result['status'] == 'REFUSED'
            assert result['sqlstate'] == 'P0001'
            assert 'certified running reservation required' in result['message']
        else:
            assert result['status'] == 'ADMITTED', result
        status, count, total, companion = prepared_case.rows('SELECT r.status,r.predictions_created,(SELECT count(*) FROM public.moneyline_game_predictions p WHERE p.moneyline_prediction_run_id=r.moneyline_prediction_run_id),r.canonical_time_knowledge FROM public.moneyline_prediction_runs r WHERE moneyline_prediction_run_id=%s', (run_id,))[0]
        expected = ('running', 0, 1) if order == 'finish_aborts' else ('completed', 2, 2) if order == 'insert_commits' else ('completed', 1, 1)
        assert (status, count, total) == expected
        assert companion == original
    finally:
        main.rollback()
        main.close()
        if thread is not None:
            thread.join(10)
