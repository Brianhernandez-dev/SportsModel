"""Offline schema036 orchestration proofs, not PostgreSQL authority proofs.

Use the real CertifiedReader type, schedule policy, independent H-1/completeness,
feature generation, flattener and prediction model. Only reader I/O methods and
the analytical model are mocked. No connection, provider, model artifact loading,
identity ingestion, or actual prediction persistence is possible here.
"""
from copy import deepcopy
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from sportsmodel.database.mlb_canonical_time_repository import CertifiedReader, KnowledgeReceipt
from sportsmodel.database.mlb_operator_guard import OperatorRefusal
from sportsmodel.features.datasets.feature_flattener import flatten_game_feature_vector
from sportsmodel.models.baseball_game import BaseballGame
from sportsmodel.predictions import certified_moneyline_service as service
from sportsmodel.predictions.moneyline_service import LoadedMoneylineModelPackage


TARGET_DATE = date(2026, 10, 12)
CUTOFF = datetime(2026, 10, 12, 18, tzinfo=timezone.utc)
START = datetime(2026, 10, 12, 20, tzinfo=timezone.utc)
GAME_PK = 900584
HOME, AWAY = 14, 76
HOME_STARTER, AWAY_STARTER = 101, 102
HOME_EXTERNAL, AWAY_EXTERNAL = 8001, 8002
PROFILE, BODY = 'a' * 64, 'b' * 64
_UNSET_PAYLOAD = object()


def _schedule_game(**changes):
    value = dict(gamePk=GAME_PK, gameType='R', gameDate=START.isoformat(),
                 status={'abstractGameState': 'Preview', 'detailedState': 'Scheduled', 'startTimeTBD': False},
                 ifNecessary='N', teams={
                     'home': {'team': {'id': 146, 'name': 'Miami Marlins'},
                              'probablePitcher': {'id': HOME_EXTERNAL, 'fullName': 'Synthetic Home Starter'}},
                     'away': {'team': {'id': 114, 'name': 'Cleveland Guardians'},
                              'probablePitcher': {'id': AWAY_EXTERNAL, 'fullName': 'Synthetic Away Starter'}},
                 })
    value.update(changes)
    return value


def _payload(*games):
    return {'dates': [{'date': TARGET_DATE.isoformat(), 'games': list(games)}]}


class _AnalyticalModel:
    def __init__(self, harness):
        self.harness = harness
        self.transformer = SimpleNamespace(source_feature_names=())
        self.probability = 0.6
        self.error = None
        self.on_predict = None

    def predict_home_win_probability(self, features):
        self.harness.events.append(('model', dict(features), self.harness.reader.cutoff_time))
        if self.on_predict is not None:
            self.on_predict()
        if self.error is not None:
            raise self.error
        return self.probability


class _Harness:
    def __init__(self, monkeypatch):
        self.events = []
        self.game = BaseballGame(26, START, HOME, AWAY)
        self.games = {26: self.game}
        self.pk_to_game = {GAME_PK: 26}
        self.slate_ids = [26]
        self.starter_mapping = {HOME_EXTERNAL: HOME_STARTER, AWAY_EXTERNAL: AWAY_STARTER}
        self.team_rows = [dict(team_id=HOME, name='Miami Marlins', mlb_team_id=146, source_row_id=11),
                          dict(team_id=AWAY, name='Cleveland Guardians', mlb_team_id=114, source_row_id=12)]
        self.source_rows = [dict(game_id=26, external_game_id=str(GAME_PK))]
        self.history_rows = []
        self.rows_override = {}
        self.errors = {}
        self.game_refresh = None
        self.game_reads = 0
        self.inserted = []
        self.finishes = []
        self.reader = CertifiedReader(self._forbidden_connection,
            KnowledgeReceipt(1, BODY, CUTOFF-timedelta(minutes=1), PROFILE,
                             ('127.0.0.1', 55572, 'sportsmodel_test_arbitration210_36')), CUTOFF)
        monkeypatch.setattr(CertifiedReader, 'rows', lambda reader, purpose, **params: self._rows_method(reader, purpose, **params))
        monkeypatch.setattr(CertifiedReader, 'game', lambda reader, game_id: self._game_method(reader, game_id))
        monkeypatch.setattr(CertifiedReader, 'reserve_run', lambda reader, **params: self._reserve_method(reader, **params))
        monkeypatch.setattr(CertifiedReader, 'insert_prediction', lambda reader, prediction: self._insert_method(reader, prediction))
        monkeypatch.setattr(CertifiedReader, 'finish_run', lambda reader, **params: self._finish_method(reader, **params))
        self.model = _AnalyticalModel(self)
        # Derive the exact source feature contract with real generation, not an
        # invented list or stub feature vector. All historical I/O returns empty.
        vector = service._knowledge_feature_service(self.reader).generate_for_game_record(
            game=self.game, cutoff_time=CUTOFF,
            home_starting_pitcher_id=HOME_STARTER, away_starting_pitcher_id=AWAY_STARTER)
        self.model.transformer.source_feature_names = tuple(flatten_game_feature_vector(vector))
        self.package = LoadedMoneylineModelPackage(self.model, 'synthetic-model-v1', vector.feature_schema_version,
                                                   'd' * 64, CUTOFF-timedelta(days=1))
        self.events.clear()

    @staticmethod
    def _forbidden_connection():
        raise AssertionError('No ambient or actual connection is permitted')

    def _reader(self, reader):
        assert reader is self.reader and reader.cutoff_time == CUTOFF

    def _rows_method(self, reader, purpose, **params):
        self._reader(reader)
        self.events.append(('rows', purpose, deepcopy(params), self.reader.cutoff_time))
        if purpose in self.errors:
            raise self.errors[purpose]
        if purpose in self.rows_override:
            return tuple(deepcopy(self.rows_override[purpose]))
        if purpose == 'slate':
            return tuple(dict(game_id=i, game_date=self.games[i].game_start_time.isoformat(),
                              home_team_id=self.games[i].home_team_id, away_team_id=self.games[i].away_team_id)
                         for i in self.slate_ids)
        if purpose == 'recovery_identity':
            identifier = self.pk_to_game.get(params['id'])
            return () if identifier is None else ({'game_id': identifier},)
        if purpose == 'mlb_teams':
            return tuple(deepcopy(row) for row in self.team_rows if row['team_id'] in params['ids'])
        if purpose == 'mlb_starters':
            return tuple(dict(baseball_player_id=canonical, external_player_id=str(external))
                         for external, canonical in self.starter_mapping.items() if canonical in params['ids'])
        if purpose == 'h1_team':
            return tuple(deepcopy(self.history_rows))
        if purpose in ('h1_starter', 'required_game_pks', 'team_stats', 'starter_stats', 'bullpen_stats'):
            return ()
        if purpose == 'game_sources':
            return tuple(deepcopy(row) for row in self.source_rows if row['game_id'] in params['ids'])
        if purpose == 'completeness':
            return tuple(dict(game_pk=pk, mapping_game_ids=[self.pk_to_game[pk]], home_team_id=HOME,
                              away_team_id=AWAY, canonical_mlb_game_pks=[str(pk)], results=[],
                              team_statistics=[], pitching_statistics=[]) for pk in params['ids'])
        raise AssertionError(f'Unexpected certified purpose: {purpose}')

    def _game_method(self, reader, game_id):
        self._reader(reader)
        self.game_reads += 1
        self.events.append(('game', game_id, self.reader.cutoff_time))
        if 'game' in self.errors:
            raise self.errors['game']
        if self.game_reads > 1 and self.game_refresh is not None:
            if isinstance(self.game_refresh, Exception):
                raise self.game_refresh
            return self.game_refresh
        return self.games.get(game_id)

    def _reserve_method(self, reader, **params):
        self._reader(reader)
        self.events.append(('reserve', deepcopy(params), self.reader.cutoff_time))
        if 'reserve' in self.errors:
            raise self.errors['reserve']
        return 7

    def _insert_method(self, reader, prediction):
        self._reader(reader)
        self.events.append(('insert', prediction, self.reader.cutoff_time))
        assert prediction.prediction_time == self.reader.cutoff_time == CUTOFF
        if 'insert' in self.errors:
            raise self.errors['insert']
        self.inserted.append(prediction)
        return len(self.inserted)

    def _finish_method(self, reader, **params):
        self._reader(reader)
        self.events.append(('finish', deepcopy(params), self.reader.cutoff_time))
        self.finishes.append(deepcopy(params))
        error = self.errors.get('finish_'+params['outcome'])
        if error is not None:
            raise error

    def run(self, schedule_payload=_UNSET_PAYLOAD, **changes):
        request = dict(reader=self.reader, target_date=TARGET_DATE,
                       schedule_payload=_payload(_schedule_game()) if schedule_payload is _UNSET_PAYLOAD else schedule_payload,
                       starter_mapping=self.starter_mapping, model_package=self.package, run_type='preview')
        request.update(changes)
        return service.run_certified_moneyline_predictions(**request)


@pytest.fixture
def harness(monkeypatch):
    return _Harness(monkeypatch)


def _assert_held(harness):
    assert not any(event[0] in ('model', 'reserve', 'insert', 'finish') for event in harness.events)
    assert harness.inserted == [] and harness.finishes == []


@pytest.mark.parametrize('payload', [None, [], {}, {'dates': {}}, {'dates': [None]},
                                    {'dates': [{'games': []}]},
                                    {'dates': [{'date': '2026-10-11', 'games': []}]},
                                    {'dates': [{'date': '2026-10-12'}]},
                                    {'dates': [{'date': '2026-10-12', 'games': {}}]},
                                    {'dates': [{'date': '2026-10-12', 'games': [None]}]}])
def test_precollected_schedule_malformed_or_wrong_date_fails_before_reader(harness, payload):
    with pytest.raises((ValueError, OperatorRefusal)):
        harness.run(payload)
    assert harness.events == []


def test_legitimate_empty_date_still_consumes_receipt_bound_slate_and_run_paths(harness):
    harness.slate_ids = []
    result = harness.run({'dates': []})
    assert result.predictions_created == 0 and result.games_received == 0 and result.predictions == ()
    assert [(event[0], event[1] if event[0] == 'rows' else None) for event in harness.events] == [
        ('rows', 'slate'), ('reserve', None), ('finish', None)]
    assert harness.finishes == [dict(run_id=7, outcome='completed', games_received=0,
                                    predictions_created=0, games_skipped=0)]


def test_empty_provider_response_cannot_hide_retained_canonical_slate(harness):
    with pytest.raises(OperatorRefusal, match='complete retained canonical slate'):
        harness.run({'dates': []})
    _assert_held(harness)


@pytest.mark.parametrize('slate_ids', [[26, 27], [26, 26], [27]])
def test_provider_partial_or_mismatched_retained_slate_cannot_reserve_run(harness, slate_ids):
    harness.games[27] = BaseballGame(27, START+timedelta(hours=1), HOME, AWAY)
    harness.slate_ids = slate_ids
    with pytest.raises(OperatorRefusal, match='complete retained canonical slate'):
        harness.run()
    _assert_held(harness)


@pytest.mark.parametrize('game_type', ['F', 'D', 'L', 'W'])
def test_all_conditional_postseason_date_defers_before_certified_data_or_run(harness, game_type):
    with pytest.raises(OperatorRefusal, match='All-conditional.*deferred'):
        harness.run(_payload(_schedule_game(gameType=game_type, ifNecessary='Y')))
    assert harness.events == []


@pytest.mark.parametrize('game_type', ['S', 'E', 'A', 'I'])
def test_deliberate_exclusions_keep_explicit_empty_certification(harness, game_type):
    harness.slate_ids = []
    result = harness.run(_payload(_schedule_game(gameType=game_type)))
    assert result.games_received == 1 and result.predictions_created == 0 and result.games_skipped == 1
    assert not any(event[0] == 'model' for event in harness.events)
    assert harness.finishes[0]['outcome'] == 'completed'


@pytest.mark.parametrize('game_type', [None, 'X', 1])
def test_unknown_or_malformed_game_type_never_becomes_exclusion(harness, game_type):
    with pytest.raises(ValueError, match='gameType'):
        harness.run(_payload(_schedule_game(gameType=game_type)))
    assert harness.events == []


def test_malformed_regular_game_cannot_become_partial_slate(harness):
    malformed = _schedule_game(gamePk=900585, teams={})
    with pytest.raises(OperatorRefusal, match='Malformed regular-season'):
        harness.run(_payload(_schedule_game(), malformed))
    assert harness.events == []


def test_duplicate_schedule_event_refuses_before_canonical_read(harness):
    with pytest.raises(OperatorRefusal, match='Duplicate schedule event identity'):
        harness.run(_payload(_schedule_game(), _schedule_game()))
    assert harness.events == []


def test_schedule_response_cardinality_is_bounded_before_read(harness):
    with pytest.raises(OperatorRefusal, match='Bounded MLB schedule'):
        harness.run(_payload(*[_schedule_game(gamePk=GAME_PK+i) for i in range(33)]))
    assert harness.events == []


@pytest.mark.parametrize('source', [[], [{'game_id': 26}, {'game_id': 27}]])
def test_canonical_source_claim_must_be_unique(harness, source):
    harness.rows_override['recovery_identity'] = source
    with pytest.raises(OperatorRefusal, match='Unique active canonical MLB event'):
        harness.run()
    _assert_held(harness)


@pytest.mark.parametrize('mapping', [{}, {HOME_EXTERNAL: HOME_STARTER},
                                   {HOME_EXTERNAL: HOME_STARTER, AWAY_EXTERNAL: HOME_STARTER},
                                   {True: HOME_STARTER, AWAY_EXTERNAL: AWAY_STARTER},
                                   {HOME_EXTERNAL: True, AWAY_EXTERNAL: AWAY_STARTER}])
def test_both_unique_typed_starter_claims_are_required(harness, mapping):
    with pytest.raises(OperatorRefusal):
        harness.run(starter_mapping=mapping)
    _assert_held(harness)


@pytest.mark.parametrize('sources', [[], [{'baseball_player_id': HOME_STARTER, 'external_player_id': str(HOME_EXTERNAL)}],
    [{'baseball_player_id': HOME_STARTER, 'external_player_id': str(AWAY_EXTERNAL)},
     {'baseball_player_id': AWAY_STARTER, 'external_player_id': str(HOME_EXTERNAL)}]])
def test_starter_claims_need_exact_unique_authoritative_source_pairs(harness, sources):
    harness.rows_override['mlb_starters'] = sources
    with pytest.raises(OperatorRefusal, match='canonical starter claim'):
        harness.run()
    _assert_held(harness)


def test_actual_h1_refuses_reused_canonical_starter_across_target_games(harness):
    second = BaseballGame(27, START+timedelta(hours=1), HOME, AWAY)
    harness.games[27] = second
    harness.pk_to_game[GAME_PK+1] = 27
    harness.slate_ids = [26, 27]
    harness.source_rows.append(dict(game_id=27, external_game_id=str(GAME_PK+1)))
    second_schedule = _schedule_game(gamePk=GAME_PK+1, gameDate=second.game_start_time.isoformat())
    with pytest.raises(OperatorRefusal, match='starter IDs must be unique across the target slate'):
        harness.run(_payload(_schedule_game(), second_schedule))
    _assert_held(harness)


def test_actual_independent_h1_missing_history_identity_holds_before_model_or_reservation(harness):
    harness.history_rows = [dict(team_id=HOME, game_id=19, home_team_id=HOME, away_team_id=AWAY,
                                game_date=(CUTOFF-timedelta(days=1)).isoformat(), rank=1)]
    with pytest.raises(OperatorRefusal, match='Independent H-1 is incomplete'):
        harness.run()
    assert any(event[:2] == ('rows', 'h1_team') for event in harness.events)
    assert any(event[:2] == ('rows', 'game_sources') and 19 in event[2]['ids'] for event in harness.events)
    _assert_held(harness)


def test_real_feature_generation_and_model_run_use_same_original_cutoff(harness):
    result = harness.run()
    assert result.prediction_time == CUTOFF and result.predictions_created == 1
    assert len(harness.inserted) == 1 and harness.inserted[0].prediction_time == CUTOFF
    assert all(event[-1] == CUTOFF for event in harness.events)
    kinds = [event[0] for event in harness.events]
    model_index, insert_index = kinds.index('model'), kinds.index('insert')
    assert kinds.index('reserve') < model_index < insert_index < kinds.index('finish')
    assert kinds[model_index-1] == 'game'  # Receipt-bound canonical refresh after actual feature assembly.
    assert any(event[:2] == ('rows', 'completeness') for event in harness.events)
    assert any(event[:2] == ('rows', 'team_stats') for event in harness.events)
    assert harness.finishes[0]['outcome'] == 'completed'


@pytest.mark.parametrize('game_type', ['R', 'F', 'D', 'L', 'W'])
def test_confirmed_championship_game_types_keep_certified_orchestration(harness, game_type):
    result = harness.run(_payload(_schedule_game(gameType=game_type)))
    assert result.predictions_created == 1 and result.games_skipped == 0
    assert harness.inserted[0].prediction_time == CUTOFF


@pytest.mark.parametrize('change', ['time', 'orientation'])
def test_schedule_claim_cannot_substitute_current_canonical_identity(harness, change):
    game = (_schedule_game(gameDate=(START+timedelta(seconds=60)).isoformat()) if change == 'time'
            else _schedule_game())
    if change == 'orientation':
        game['teams']['home'], game['teams']['away'] = game['teams']['away'], game['teams']['home']
    with pytest.raises(OperatorRefusal):
        harness.run(_payload(game))
    _assert_held(harness)


@pytest.mark.parametrize('contract', ['schema', 'names', 'order'])
def test_feature_contract_mismatch_holds_model_and_marks_reserved_run_failed(harness, contract):
    if contract == 'schema':
        harness.package = replace(harness.package, feature_schema_version='unreviewed-schema')
    elif contract == 'names':
        harness.model.transformer.source_feature_names += ('unreviewed_feature',)
    else:
        harness.model.transformer.source_feature_names = tuple(reversed(harness.model.transformer.source_feature_names))
    with pytest.raises(OperatorRefusal, match='frozen model contract'):
        harness.run()
    assert not any(event[0] in ('model', 'insert') for event in harness.events)
    assert [row['outcome'] for row in harness.finishes] == ['failed']


@pytest.mark.parametrize('change', ['time', 'receipt_refusal'])
def test_post_feature_proof_refresh_refuses_before_model(harness, change):
    harness.game_refresh = (replace(harness.game, game_start_time=START+timedelta(seconds=1))
                            if change == 'time' else OperatorRefusal('synthetic stale receipt'))
    with pytest.raises(OperatorRefusal):
        harness.run()
    assert not any(event[0] in ('model', 'insert') for event in harness.events)
    assert [row['outcome'] for row in harness.finishes] == ['failed']


def test_persistence_proof_refusal_after_model_cannot_complete_successfully(harness):
    harness.model.on_predict = lambda: harness.errors.update(insert=OperatorRefusal('synthetic stale persistence proof'))
    with pytest.raises(OperatorRefusal, match='stale persistence proof'):
        harness.run()
    assert len([event for event in harness.events if event[0] == 'model']) == 1
    assert harness.inserted == []
    assert [row['outcome'] for row in harness.finishes] == ['failed']


@pytest.mark.parametrize('probability', [True, None, float('nan'), float('inf'), -0.1, 1.1])
def test_invalid_analytical_probability_fails_run_without_prediction(harness, probability):
    harness.model.probability = probability
    with pytest.raises(OperatorRefusal, match='Invalid model probability'):
        harness.run()
    assert harness.inserted == [] and [row['outcome'] for row in harness.finishes] == ['failed']


def test_normal_model_error_records_one_failed_outcome_without_retry(harness):
    harness.model.error = RuntimeError('synthetic analytical refusal')
    with pytest.raises(RuntimeError, match='synthetic analytical refusal'):
        harness.run()
    assert len([event for event in harness.events if event[0] == 'model']) == 1
    assert harness.inserted == []
    assert [row['outcome'] for row in harness.finishes] == ['failed']
    assert harness.finishes[0]['predictions_created'] == 0


def test_later_normal_error_preserves_partial_prediction_under_failed_not_successful_run(harness):
    second = BaseballGame(27, START+timedelta(hours=1), HOME, AWAY)
    harness.games[27] = second
    harness.pk_to_game[GAME_PK+1] = 27
    harness.slate_ids = [26, 27]
    harness.source_rows.append(dict(game_id=27, external_game_id=str(GAME_PK+1)))
    harness.starter_mapping.update({8003: 103, 8004: 104})
    second_schedule = _schedule_game(gamePk=GAME_PK+1, gameDate=second.game_start_time.isoformat())
    second_schedule['teams']['home']['probablePitcher']['id'] = 8003
    second_schedule['teams']['away']['probablePitcher']['id'] = 8004
    def fail_second_model_call():
        if len([event for event in harness.events if event[0] == 'model']) == 2:
            harness.model.error = RuntimeError('synthetic second-game refusal')
    harness.model.on_predict = fail_second_model_call
    with pytest.raises(RuntimeError, match='second-game refusal'):
        harness.run(_payload(_schedule_game(), second_schedule))
    assert len(harness.inserted) == 1
    assert len([event for event in harness.events if event[0] == 'reserve']) == 1
    assert [row['outcome'] for row in harness.finishes] == ['failed']
    assert harness.finishes[0]['predictions_created'] == 1
    assert harness.finishes[0]['games_received'] == 2 and harness.finishes[0]['games_skipped'] == 1


@pytest.mark.parametrize('stage', ['reserve', 'insert', 'finish_completed'])
def test_unknown_commit_never_triggers_failed_completion_or_retry(harness, stage):
    harness.errors[stage] = OperatorRefusal('UNKNOWN synthetic acknowledgement; inspection only, no retry')
    with pytest.raises(OperatorRefusal, match='UNKNOWN'):
        harness.run()
    assert len([event for event in harness.events if event[0] == 'reserve']) == 1
    assert len([event for event in harness.events if event[0] == 'insert']) <= 1
    assert not any(row['outcome'] == 'failed' for row in harness.finishes)
    assert len(harness.finishes) == (1 if stage == 'finish_completed' else 0)


def test_failed_outcome_error_requires_inspection_without_second_attempt(harness):
    harness.model.error = RuntimeError('synthetic model error')
    harness.errors['finish_failed'] = RuntimeError('synthetic failure-state refusal')
    with pytest.raises(OperatorRefusal, match='read-only inspection; no automatic retry'):
        harness.run()
    assert [row['outcome'] for row in harness.finishes] == ['failed']


def test_entrypoint_rejects_fake_reader_and_future_training_before_input(harness):
    with pytest.raises(OperatorRefusal, match='Explicit certified reader'):
        harness.run(reader=SimpleNamespace(cutoff_time=CUTOFF))
    with pytest.raises(OperatorRefusal, match='training cutoff'):
        harness.run(model_package=replace(harness.package, model_training_cutoff=CUTOFF+timedelta(microseconds=1)))
    assert harness.events == []


def test_no_ambient_provider_model_or_identity_ingestion_is_called(harness, monkeypatch):
    from sportsmodel.predictions import moneyline_service as legacy
    forbidden = []
    def refuse(*args, **kwargs):
        forbidden.append('unexpected ambient action')
        raise AssertionError('No ambient provider/model/identity operation is authorized')
    for name in ('get_connection', 'fetch_hydrated_schedule_for_date', 'load_current_probable_starters',
                 'load_moneyline_model_package', 'sync_mlb_schedule', 'sync_mlb_players'):
        monkeypatch.setattr(legacy, name, refuse)
    result = harness.run()
    assert result.predictions_created == 1 and forbidden == []
