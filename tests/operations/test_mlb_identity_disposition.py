"""Offline admission/integration checks; no credentials/providers/DB."""
from datetime import datetime,timezone
import json
from types import SimpleNamespace
import pytest
from sportsmodel.operations import mlb_identity_disposition as operator
from sportsmodel.database import mlb_identity_disposition_repository as identity
from sportsmodel.database.mlb_operator_guard import OperatorRefusal


@pytest.mark.parametrize('body',[{'admission':'DESIGN_ONLY','executable':False},{},
    {'format':operator.FORMAT,'version':True},{'format':operator.FORMAT,'version':1,'domain':'NFL'}])
def test_non_executable_requests_refuse_before_connection(body):
    called=[]
    with pytest.raises((OperatorRefusal,ValueError)):
        operator.execute_disposition(request_bytes=json.dumps(body).encode(),evidence_bytes=b'',
            preview={},approved_preview_sha256='a'*64,target=None,
            connection_factory=lambda:called.append(True),acknowledge_writes=True)
    assert called==[]


@pytest.mark.parametrize('endpoint',['schedule','results','prediction'])
def test_schema_refusal_precedes_provider_or_reservation(endpoint,monkeypatch):
    from sportsmodel.ingest import mlb_schedule,mlb_stats
    from sportsmodel.predictions import moneyline_service
    module={'schedule':mlb_schedule,'results':mlb_stats,'prediction':moneyline_service}[endpoint]
    calls=[]
    def incompatible(factory):
        calls.append('schema');raise identity.IdentityDispositionError('Synthetic missing034')
    def prohibited(*a,**k):pytest.fail('Provider/model/reservation reached after schema refusal')
    monkeypatch.setattr(module,'require_schema034',incompatible)
    with pytest.raises(identity.IdentityDispositionError):
        if endpoint=='schedule':mlb_schedule.sync_mlb_schedule(schedule_fetcher=prohibited,connection_factory=prohibited)
        elif endpoint=='results':mlb_stats.fetch_historical_results(schedule_fetcher=prohibited,connection_factory=prohibited)
        else:
            monkeypatch.setattr(module,'load_moneyline_model_package',prohibited)
            moneyline_service.run_moneyline_predictions(target_date=datetime.now().date(),connection_factory=prohibited)
    assert calls==['schema']


def test_uncaptured_knowledge_cannot_be_forged_from_a_hash():
    body=dict(version=1,ledger_fingerprint='a'*64,available_at='2026-10-08T00:00:00+00:00')
    proof=identity.IdentityKnowledgeSnapshot(body['ledger_fingerprint'],body['available_at'],identity._knowledge_hash(body))
    with pytest.raises(identity.IdentityDispositionError):identity.install_identity_knowledge(
        SimpleNamespace(execute=lambda *a:pytest.fail('Unproven snapshot reached SQL')),proof,
        cutoff_time=datetime(2026,10,8,1,tzinfo=timezone.utc))


@pytest.mark.parametrize('links',[{}, {'game_id':True},{'game_id':0},{'unexpected':1}])
def test_application_decision_link_validation_before_sql(links):
    with pytest.raises(identity.IdentityDispositionError):identity.assert_decision_write(
        SimpleNamespace(execute=lambda *a:pytest.fail('Invalid links reached SQL')),**links)


def test_application_decision_gate_before_eligibility():
    calls=[]
    identity.assert_decision_write(SimpleNamespace(execute=lambda *args:calls.append(args)),game_id=7,odds_market_snapshot_id=9)
    assert calls[0][0]=='SELECT mlb_identity_gate(false)'
    assert calls[1][0]=='SELECT mlb_identity_assert_decision_links(%s::jsonb)'
    assert json.loads(calls[1][1][0])=={'game_id':7,'odds_market_snapshot_id':9}


def test_catalog_function_mismatch_refuses_without_fallback():
    cursor=SimpleNamespace(execute=lambda *a:None,fetchall=lambda:[])
    with pytest.raises(identity.IdentityDispositionError,match='function capability'):identity.verify_capabilities(cursor)


def test_operator_file_bound_and_secret_path_refuse(tmp_path):
    from sportsmodel.operations.mlb_identity_disposition_cli import _read
    evidence=tmp_path/'evidence.json';evidence.write_bytes(b'12345')
    assert _read(evidence,5)==b'12345'
    with pytest.raises(OperatorRefusal):_read(evidence,4)
    with pytest.raises(OperatorRefusal):_read(tmp_path/'.env',100)
    with pytest.raises(OperatorRefusal):_read(__import__('pathlib').Path(r'\\host\share\evidence.json'),100)


def test_recovery_gate_precedes_eligibility_and_child_locks(monkeypatch):
    from sportsmodel.ingest import mlb_recovery
    calls=[]
    def events(*args):
        assert calls==['SELECT mlb_identity_gate(false)']
        raise RuntimeError('Synthetic stop before eligibility/child locks')
    monkeypatch.setattr(mlb_recovery,'_events',events)
    with pytest.raises(RuntimeError,match='Synthetic stop'):
        mlb_recovery.read_snapshot(SimpleNamespace(execute=lambda sql,params:calls.append(sql)),None,None,lock=True)
