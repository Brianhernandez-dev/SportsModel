"""Offline admission closure diagnostics; never stand-ins for PostgreSQL proof.

In particular T07-T16/T18 need real subject/survivor dependencies and transactional
rollback on an isolated target. These tests exercise request/evidence and client
admission surfaces only, and deliberately retain any unresolved requirement as a
normal failing test rather than xfail, skip, or inferred acceptance.
"""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from io import BytesIO
import zipfile
import json
import re
from types import SimpleNamespace

import pytest

from sportsmodel.database import mlb_canonical_time_repository as repository
from sportsmodel.database.mlb_operator_guard import OperatorRefusal
from tests.operations.test_mlb_canonical_time_arbitration import (
    PROFILE, archive, bundle, event, operator, protocol, target,
)


INPUT_REFUSALS = (ValueError, KeyError, TypeError)
ROOT = Path(__file__).resolve().parents[2]


def _refuses_before_connection(operator, target, raw, evidence):
    calls = []
    def factory():
        calls.append('unexpected connection')
        raise AssertionError('Invalid admission must refuse before database access')
    with pytest.raises(INPUT_REFUSALS):
        operator.preview_arbitration(request_bytes=raw, evidence_bytes=evidence,
                                    target=target, connection_factory=factory)
    assert calls == []


def test_T17_missing_real_origin_attestation_is_not_replaced_by_a_public_hash(operator, target):
    """A03 requires actual origin/acquisition lineage, not merely 64 hex digits.

    No attestation schema is invented here. The negative input lacks any origin
    record whatsoever; its arbitrary public hash must not supply that record.
    """
    raw, evidence = bundle(operator, changes={'origin_attestation_sha256': '9' * 64})
    with zipfile.ZipFile(BytesIO(evidence)) as source:
        evidence = archive([(name, source.read(name)) for name in source.namelist()
                            if name != operator.ORIGIN_METADATA_ENTRY])
    request = json.loads(raw)
    request['evidence_sha256'] = sha256(evidence).hexdigest()
    raw = operator.canonical_json(request).encode()
    _refuses_before_connection(operator, target, raw, evidence)


@pytest.mark.parametrize('change', ['raw_hash', 'url', 'final_url', 'http_status', 'http_bool',
    'payload_hash', 'payload_size', 'size_bool', 'requests', 'requests_bool', 'anonymous',
    'paid_odds', 'content_type', 'server_date', 'before_event', 'timestamp_precision',
    'missing_chain', 'missing_manifest', 'wrong_manifest_hash', 'unlisted_chain_member'])
def test_T17_origin_bytes_endpoint_acquisition_and_chain_fail_closed(operator, target, change):
    raw, evidence = bundle(operator)
    request = json.loads(raw)
    with zipfile.ZipFile(BytesIO(evidence)) as source:
        entries = {name: source.read(name) for name in source.namelist()}
    metadata = json.loads(entries[operator.ORIGIN_METADATA_ENTRY])
    alterations = {'url': ('url', 'https://example.invalid/schedule'),
        'final_url': ('final_url', 'https://example.invalid/schedule'),
        'http_status': ('http_status', 500), 'http_bool': ('http_status', True),
        'payload_hash': ('sha256', '0' * 64), 'payload_size': ('bytes', 1),
        'size_bool': ('bytes', True), 'requests': ('requests', 2), 'requests_bool': ('requests', True),
        'anonymous': ('anonymous', False), 'paid_odds': ('paid_Odds_API', True),
        'content_type': ('content_type', 'text/plain'), 'server_date': ('server_date', 'not a date'),
        'before_event': ('observed_utc', '2026-07-11T00:00:00Z'),
        'timestamp_precision': ('observed_utc', '2026-10-12T00:00:00.0000001Z')}
    if change in alterations:
        field, value = alterations[change]
        metadata[field] = value
        origin = operator.canonical_json(metadata).encode()
        entries[operator.ORIGIN_METADATA_ENTRY] = origin
        request['origin_attestation_sha256'] = sha256(origin).hexdigest()
        chain_members = [('synthetic_schedule.json', entries[request['payload_entry']]),
                         ('origin_metadata.json', origin)]
        manifest = '| Entry | Bytes | SHA-256 |\n' + ''.join(
            f'| {name} | {len(value)} | {sha256(value).hexdigest()} |\n' for name, value in chain_members)
        entries[operator.SOURCE_CHAIN_ENTRY] = archive(chain_members + [('REVIEW_MANIFEST.md', manifest.encode())])
    elif change == 'raw_hash':
        request['origin_attestation_sha256'] = '0' * 64
    elif change == 'missing_chain':
        entries.pop(operator.SOURCE_CHAIN_ENTRY)
    else:
        with zipfile.ZipFile(BytesIO(entries[operator.SOURCE_CHAIN_ENTRY])) as chain:
            chain_members = [(name, chain.read(name)) for name in chain.namelist()]
        if change == 'missing_manifest':
            chain_members = [(name, value) for name, value in chain_members if name != 'REVIEW_MANIFEST.md']
        elif change == 'wrong_manifest_hash':
            chain_members = [(name, value.replace(request['payload_sha256'].encode(), b'0' * 64)
                              if name == 'REVIEW_MANIFEST.md' else value) for name, value in chain_members]
        else:
            chain_members.append(('unlisted.txt', b'SYNTHETIC_ONLY'))
        entries[operator.SOURCE_CHAIN_ENTRY] = archive(chain_members)
    evidence = archive(list(entries.items()))
    request['evidence_sha256'] = sha256(evidence).hexdigest()
    _refuses_before_connection(operator, target, operator.canonical_json(request).encode(), evidence)


def _native_retained_case(operator):
    chain = (ROOT / 'tests/fixtures/database/mlb_canonical_time_origin_chain.zip').read_bytes()
    assert sha256(chain).hexdigest() == operator.NATIVE_RETAINED_CHAIN_SHA256
    with zipfile.ZipFile(BytesIO(chain)) as source:
        payload = source.read('MLB_STATS_PAYLOADS/mlb_schedule_2026-07-12.json')
        metadata = source.read('MLB_STATS_REQUEST_METADATA.json')
    evidence = archive([('schedule.json', payload), (operator.ORIGIN_METADATA_ENTRY, metadata),
                        (operator.SOURCE_CHAIN_ENTRY, chain)])
    raw, _ = bundle(operator)
    request = json.loads(raw)
    request.update(game_pk=823842, payload_entry='schedule.json',
        evidence_sha256=sha256(evidence).hexdigest(), payload_sha256=sha256(payload).hexdigest(),
        origin_attestation_sha256=sha256(metadata).hexdigest())
    native = operator.OperatorTarget(host='127.0.0.1', port=5432, database='sportsmodel',
        server_address='127.0.0.1', server_port=5432,
        postmaster_started_at='2026-10-12T00:00:00Z', identity_kind='native')
    return native, request, evidence


def test_T17_reviewed_native_chain_byte_identity_passes_offline_parser_only(operator):
    native, request, evidence = _native_retained_case(operator)
    validated, derived = operator.validate_request(operator.canonical_json(request).encode(), evidence, native)
    assert validated['payload_sha256'] == operator.NATIVE_RETAINED_PAYLOAD_SHA256
    assert derived['origin_provenance']['metadata_raw_sha256'] == operator.NATIVE_RETAINED_ORIGIN_SHA256
    assert derived['origin_provenance']['chain_sha256'] == operator.NATIVE_RETAINED_CHAIN_SHA256
    assert 'synthetic' not in derived['origin_provenance']['metadata']


@pytest.mark.parametrize('changes', [
    {'game_pk': 900584}, {'game_pk': 823843},
    {'subject': 585}, {'survivor': 27}, {'subject': 26, 'survivor': 584},
])
def test_T05_native_policy_wrong_pk_or_pair_refuses_before_any_connection(operator, changes):
    native, request, evidence = _native_retained_case(operator)
    request.update(changes)
    # Same correct raw MLB participants/timestamp/acquisition chain, wrong fixed
    # policy identity. This is pure parsing, not native authorization/execution.
    _refuses_before_connection(operator, native, operator.canonical_json(request).encode(), evidence)


@pytest.mark.parametrize('game_type', ['S', 'E', 'A', 'I'])
def test_T17_well_formed_nonmodel_surrounding_records_keep_deliberate_exclusion(operator, target, game_type):
    other = event()
    other.update(gamePk=900585, gameType=game_type)
    other['teams']['home']['team'] = dict(id=159, name='American League All-Stars')
    other['teams']['away']['team'] = dict(id=160, name='National League All-Stars')
    raw, evidence = bundle(operator, payload=dict(dates=[dict(date='2026-07-12', games=[event(), other])]))
    _, derived = operator.validate_request(raw, evidence, target)
    assert derived['retirement_case']['proof']['gamePk'] == 900584


@pytest.mark.parametrize('alteration', ['missing_game_type', 'unknown_game_type', 'invalid_timestamp',
                                      'missing_official_date', 'invalid_status', 'invalid_game_number',
                                      'invalid_home_score', 'untyped_home_id'])
def test_T17_nonselected_surrounding_records_must_not_escape_semantic_validation(operator, target, alteration):
    other = event()
    other['gamePk'] = 900585
    other['teams']['home']['team'] = {'id': 147, 'name': 'New York Yankees'}
    other['teams']['away']['team'] = {'id': 133, 'name': 'Athletics'}
    if alteration == 'missing_game_type':
        other.pop('gameType')
    elif alteration == 'unknown_game_type':
        other['gameType'] = 'UNREVIEWED'
    elif alteration == 'invalid_timestamp':
        other['gameDate'] = 'not-a-time'
    elif alteration == 'missing_official_date':
        other.pop('officialDate')
    elif alteration == 'invalid_status':
        other['status'] = []
    elif alteration == 'invalid_game_number':
        other['gameNumber'] = True
    elif alteration == 'invalid_home_score':
        other['teams']['home']['score'] = '3'
    else:
        other['teams']['home']['team']['id'] = '147'
    raw, evidence = bundle(operator, payload={'dates': [{'date': '2026-07-12', 'games': [event(), other]}]})
    _refuses_before_connection(operator, target, raw, evidence)


@pytest.mark.parametrize('field', ['old_start', 'new_start'])
@pytest.mark.parametrize('suffix', ['.0000001Z', '.0000009Z', '.0000001+00:00'])
def test_T03_T04_T17_submicrosecond_request_values_cannot_be_truncated_into_exact_policy(operator, target, field, suffix):
    base = '2026-07-12T17:41:00' if field == 'old_start' else '2026-07-12T17:40:00'
    raw, evidence = bundle(operator, changes={field: base+suffix})
    _refuses_before_connection(operator, target, raw, evidence)


@pytest.mark.parametrize('alteration', ['missing_status', 'missing_tbd', 'wrong_abstract_state',
                                      'wrong_official_format', 'wrong_home_score_native', 'wrong_away_score_native'])
def test_T04_T06_T17_selected_authority_complete_and_native_scores_fixed(operator, target, alteration):
    selected = event()
    if alteration == 'missing_status':
        selected.pop('status')
    elif alteration == 'missing_tbd':
        selected['status'].pop('startTimeTBD')
    elif alteration == 'wrong_abstract_state':
        selected['status']['abstractGameState'] = 'Preview'
    elif alteration == 'wrong_official_format':
        selected['officialDate'] = '20260712'
    else:
        target = operator.OperatorTarget(host='127.0.0.1', port=5432, database='sportsmodel',
            server_address='127.0.0.1', server_port=5432, postmaster_started_at='2026-10-12T00:00:00Z',
            identity_kind='native')
        selected['gamePk'] = 823842
        selected['teams']['home']['score'], selected['teams']['away']['score'] = 2, 5
        selected['teams']['home' if alteration == 'wrong_home_score_native' else 'away']['score'] += 1
    raw, evidence = bundle(operator, payload={'dates': [{'date': '2026-07-12', 'games': [selected]}]},
                           changes={'game_pk': 823842} if target.identity_kind == 'native' else None)
    _refuses_before_connection(operator, target, raw, evidence)


@pytest.mark.parametrize('field', ['origin_attestation_sha256', 'payload_sha256', 'evidence_sha256'])
@pytest.mark.parametrize('value', [True, 1, [], {}, 'f'*65, '\ud800'])
def test_T17_attested_identity_hashes_require_exact_utf8_lowerhex_strings(operator, target, field, value):
    raw, evidence = bundle(operator)
    decoded = json.loads(raw)
    decoded[field] = value
    # ensure_ascii permits the invalid Unicode sentinel to reach strict JSON parsing.
    raw = json.dumps(decoded, ensure_ascii=True, separators=(',', ':')).encode()
    _refuses_before_connection(operator, target, raw, evidence)


@pytest.mark.parametrize('database', ['sportsmodel_test', 'sportsmodel_test_arbitration210_x',
                                    'sportsmodel_test_arbitration210_999_extra'])
def test_T05_T52_isolated_target_cannot_select_unapproved_synthetic_profile(operator, target, database):
    target = operator.OperatorTarget(**dict(target.artifact(), database=database))
    raw, evidence = bundle(operator)
    _refuses_before_connection(operator, target, raw, evidence)


class _IdentityCursor:
    def __init__(self, connection):
        self.connection = connection

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def execute(self, sql, params=None):
        self.connection.queries.append((sql, params))
        assert sql == 'SELECT mlb036_private.describe_target()'

    def fetchone(self):
        return (deepcopy(self.connection.identity),)


def _identity_connection(target, migrations):
    identity = dict(database=target.database, address=target.server_address, port=target.server_port,
                    started=target.postmaster_started_at, backend=901, version='160000', readonly='on',
                    isolation='repeatable read', system_identifier=target.system_identifier,
                    migrations=migrations)
    connection = SimpleNamespace(info=SimpleNamespace(host=target.host, port=target.port, dbname=target.database),
                                 identity=identity, queries=[])
    connection.cursor = lambda: _IdentityCursor(connection)
    return connection


@pytest.fixture
def client_identity(target, monkeypatch):
    reference = tuple((number, f'{number:03d}_synthetic.sql', str(number)*2) for number in range(1, 37))
    calls = []
    monkeypatch.setattr(repository, 'migration_reference', lambda: reference)
    monkeypatch.setattr(repository, 'profile_fingerprint', lambda: PROFILE)
    monkeypatch.setattr(repository, 'verify_capabilities', lambda cursor: calls.append('capabilities'))
    return SimpleNamespace(reference=reference, capabilities=calls,
                           connection=_identity_connection(target, reference))


@pytest.mark.parametrize('boundary', [33, 34, 35, 37])
def test_T52_successor_client_requires_exact_schema_not_maximum_version(target, client_identity, boundary):
    client_identity.connection.identity['migrations'] = (client_identity.reference[:boundary] if boundary < 36 else
        client_identity.reference+((37, '037_unapproved.sql', 'unapproved'),))
    with pytest.raises(OperatorRefusal, match='exact migration checksums differ'):
        repository.verify_target(client_identity.connection, target, readonly=True)
    assert client_identity.capabilities == []
    assert client_identity.connection.queries == [('SELECT mlb036_private.describe_target()', None)]


@pytest.mark.parametrize('alteration', ['gap_with_max36', 'duplicate', 'reordered', 'filename', 'checksum'])
def test_T23_T52_exact_inventory_field_identity_refuses_before_capability_or_write(target, client_identity, alteration):
    observed = list(client_identity.reference)
    if alteration == 'gap_with_max36':
        observed = [entry for entry in observed if entry[0] != 34]
    elif alteration == 'duplicate':
        observed.insert(1, observed[1])
    elif alteration == 'reordered':
        observed[0], observed[1] = observed[1], observed[0]
    elif alteration == 'filename':
        observed[-1] = (36, '036_wrong.sql', observed[-1][2])
    else:
        observed[-1] = (36, observed[-1][1], 'wrong-checksum')
    client_identity.connection.identity['migrations'] = observed
    with pytest.raises(OperatorRefusal, match='exact migration checksums differ'):
        repository.verify_target(client_identity.connection, target, readonly=True)
    assert client_identity.capabilities == []


def test_T52_exact036_client_boundary_reaches_capabilities_without_effects(target, client_identity):
    guard = repository.verify_target(client_identity.connection, target, readonly=True)
    assert guard == {'target': target.artifact(), 'profile': PROFILE}
    assert client_identity.capabilities == ['capabilities']
    assert client_identity.connection.queries == [('SELECT mlb036_private.describe_target()', None)]


@pytest.mark.parametrize('field,value', [('address', '127.0.0.2'), ('port', 5433),
    ('started', '2026-10-12T00:00:01Z'), ('database', 'sportsmodel_test_arbitration210_998'),
    ('system_identifier', '987654321'), ('version', '150000'), ('readonly', 'off'), ('isolation', 'serializable')])
def test_T23_T52_actual_endpoint_epoch_isolation_and_engine_are_bound_before_capability(target, client_identity, field, value):
    client_identity.connection.identity[field] = value
    with pytest.raises(OperatorRefusal):
        repository.verify_target(client_identity.connection, target, readonly=True)
    assert client_identity.capabilities == []


class _CapabilityCursor:
    """Synthetic metadata rows: tests validator control flow, never actual ACLs."""
    def __init__(self):
        source = (ROOT/'database/migrations'/repository.MIGRATION).read_text(encoding='utf-8-sig')
        self.functions = []
        for name, attrs, body in re.findall(r'CREATE FUNCTION mlb036_private\.([a-z_]+)\b(.*?)\bAS\s+\$\$(.*?)\$\$;', source, re.S):
            self.functions.append((name, body.strip(), 'i' if 'IMMUTABLE' in attrs else 's' if 'STABLE' in attrs else 'v',
                                   'SECURITY DEFINER' in attrs, 's' if 'PARALLEL SAFE' in attrs else 'u'))
        self.registry = ['arbitration_events', 'arbitrations', 'authority', 'knowledge_receipts']
        self.last = ''
        self.queries = []

    def execute(self, sql, params=None):
        assert sql.lstrip().startswith('SELECT')
        self.last = sql
        self.queries.append(sql)

    def fetchone(self):
        assert 'FROM pg_namespace' in self.last
        return (False,) * 6

    def fetchall(self):
        if 'p.prosrc' in self.last:
            return deepcopy(self.functions)
        if 'SELECT relname' in self.last:
            return [(name,) for name in self.registry]
        if 'p.proconfig' in self.last:
            return [(name, ['search_path=pg_catalog, mlb036_private, public, pg_temp'],
                     3 if name == 'issue_knowledge' else 2 if name == 'correct_exact' else 1,
                     *([False]*6)) for name, *_ in self.functions]
        raise AssertionError('Unknown metadata query')


@pytest.fixture
def capability_cursor(monkeypatch):
    monkeypatch.setattr(repository.frozen035, 'verify_capabilities', lambda cursor: True)
    monkeypatch.setattr(repository, 'verify_schema_catalog036', lambda cursor: True)
    return _CapabilityCursor()


@pytest.mark.parametrize('alteration', ['missing_gateway', 'body', 'volatile', 'definer', 'parallel', 'unknown_overload'])
def test_T23_exact_callable_profile_refuses_each_unknown_capability(capability_cursor, alteration):
    cursor = capability_cursor
    index = next(i for i, row in enumerate(cursor.functions) if row[0] == 'certified_data')
    row = list(cursor.functions[index])
    if alteration == 'missing_gateway':
        cursor.functions.pop(index)
    elif alteration == 'unknown_overload':
        cursor.functions.append(tuple(row))
    else:
        field = {'body': 1, 'volatile': 2, 'definer': 3, 'parallel': 4}[alteration]
        row[field] = {'body': 'UNREVIEWED_BODY', 'volatile': 's', 'definer': False, 'parallel': 's'}[alteration]
        cursor.functions[index] = tuple(row)
    with pytest.raises(OperatorRefusal, match='function capability'):
        repository.verify_capabilities(cursor)


@pytest.mark.parametrize('registry', [[], ['arbitration_events', 'arbitrations', 'authority'],
    ['arbitration_events', 'arbitrations', 'authority', 'knowledge_receipts', 'unknown_history']])
def test_T50_unknown_or_missing_audit_receipt_registry_refuses_not_broadly_exempted(capability_cursor, registry):
    capability_cursor.registry = registry
    with pytest.raises(OperatorRefusal, match='strict audit/receipt registry differs'):
        repository.verify_capabilities(capability_cursor)


def test_T23_T50_reviewed_callable_and_registry_metadata_reaches_owner_checks(capability_cursor):
    assert repository.verify_capabilities(capability_cursor) is True
    assert all(query.lstrip().startswith('SELECT') for query in capability_cursor.queries)


@pytest.mark.parametrize('field,value', [('host', '127.0.0.2'), ('dbname', 'sportsmodel_test_arbitration210_998')])
def test_T24_probe_endpoint_host_and_database_refuse_without_correction(protocol, field, value):
    setattr(protocol.probe.info, field, value)
    with pytest.raises(OperatorRefusal, match='fresh probe endpoint differs'):
        protocol.execute()
    assert not any(entry[1] == 'execute' and 'correct_exact(' in entry[2] for entry in protocol.events)
    assert not any(entry[1] == 'commit' for entry in protocol.events)
    assert ('probe', 'rollback') in protocol.events and ('probe', 'close') in protocol.events
    assert ('X', 'rollback') in protocol.events and ('X', 'close') in protocol.events
    assert len(protocol.calls) == 2


def test_T24_fresh_probe_read_failure_has_no_correction_commit_or_retry(protocol):
    protocol.probe.fail_statement = 'operator_state()'
    with pytest.raises(RuntimeError, match='Synthetic statement failure'):
        protocol.execute()
    assert not any(entry[1] == 'execute' and 'correct_exact(' in entry[2] for entry in protocol.events)
    assert not any(entry[1] == 'commit' for entry in protocol.events)
    assert ('probe', 'rollback') in protocol.events and ('probe', 'close') in protocol.events
    assert ('X', 'rollback') in protocol.events and ('X', 'close') in protocol.events
    assert len(protocol.calls) == 2
