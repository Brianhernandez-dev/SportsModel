"""Explicit schema036 moneyline adapter; no provider, identity repair or discovery.

Callers supply already acquired schedule evidence, canonical starter claims and an
already loaded frozen model. The adapter verifies those claims through one fixed
CertifiedReader, requires independent H-1, and uses only protected run APIs. This
module does not activate the legacy CLI/workflow or authorize production use.
"""
from datetime import date, datetime, time, timedelta, timezone
from math import isfinite
from zoneinfo import ZoneInfo

from sportsmodel.database.mlb_canonical_time_repository import CertifiedReader
from sportsmodel.database.mlb_operator_guard import OperatorRefusal, aware
from sportsmodel.features.datasets.feature_flattener import flatten_game_feature_vector
from sportsmodel.ingest.mlb_game_policy import championship_game_type, extract_schedule_games
from sportsmodel.ingest.team_identity import normalize_team_name
from sportsmodel.models.moneyline_prediction import MoneylineGamePrediction
from sportsmodel.operations.mlb_history_check import check_feature_history
from sportsmodel.predictions.moneyline_service import (
    LoadedMoneylineModelPackage, MoneylinePredictionResult, MoneylinePredictionRunResult,
    _knowledge_feature_service, _parse_hydrated_schedule_game,
)


def run_certified_moneyline_predictions(*, reader, target_date, schedule_payload,
                                       starter_mapping, model_package, run_type='official'):
    """Run only after the complete retained slate and independent H-1 are proven.

    A failed later stage retains immutable partial evidence under a failed run;
    it is never a successful card. An uncertain commit is inspection-only. No
    identity/starter ingestion, provider request, publication or retry occurs.
    Both canonical starters are required by the reviewed independent H-1 gate.
    """
    if (not isinstance(reader, CertifiedReader) or type(target_date) is not date
        or type(starter_mapping) is not dict or not isinstance(model_package, LoadedMoneylineModelPackage)
        or run_type not in ('official', 'preview')):
        raise OperatorRefusal('Explicit certified reader, date, starter claims and model package required')
    if (not isinstance(model_package.model_training_cutoff, datetime)
        or model_package.model_training_cutoff.utcoffset() is None
        or model_package.model_training_cutoff > reader.cutoff_time):
        raise OperatorRefusal('Model training cutoff must precede the original certified cutoff')
    if any(type(key) is not int or key <= 0 or type(value) is not int or value <= 0
           for key, value in starter_mapping.items()):
        raise OperatorRefusal('Strict positive canonical starter claims required')
    raw_games = extract_schedule_games(schedule_payload, expected_date=target_date)
    if len(raw_games) > 32:
        raise OperatorRefusal('Bounded MLB schedule required')
    supported = tuple(game for game in raw_games if championship_game_type(game))
    hydrated = []
    for game in supported:
        parsed = _parse_hydrated_schedule_game(game)
        if parsed is None and game['gameType'] == 'R':
            raise OperatorRefusal('Malformed regular-season schedule event cannot become a partial slate')
        if parsed is not None:
            if type(parsed.mlb_game_id) is not int:
                raise OperatorRefusal('Strict MLB event identity required')
            hydrated.append(parsed)
    if supported and not hydrated:
        raise OperatorRefusal('All-conditional or unconfirmed slate is deferred, not a successful empty card')
    if len({game.mlb_game_id for game in hydrated}) != len(hydrated):
        raise OperatorRefusal('Duplicate schedule event identity')
    zone = ZoneInfo('America/Los_Angeles')
    start = datetime.combine(target_date, time.min, zone).astimezone(timezone.utc)
    end = datetime.combine(target_date + timedelta(days=1), time.min, zone).astimezone(timezone.utc)
    slate = reader.rows('slate', start=start.isoformat(), end=end.isoformat())
    resolved = []
    raw_by_pk = {game['gamePk']: game for game in supported if type(game.get('gamePk')) is int}
    for schedule_game in hydrated:
        source = reader.rows('recovery_identity', id=schedule_game.mlb_game_id)
        if len(source) != 1:
            raise OperatorRefusal('Unique active canonical MLB event required')
        game = reader.game(source[0]['game_id'])
        if (game is None or game.game_start_time != schedule_game.game_datetime
            or not start <= game.game_start_time < end or reader.cutoff_time >= game.game_start_time):
            raise OperatorRefusal('Schedule/current canonical time or prospective cutoff differs')
        teams = reader.rows('mlb_teams', ids=[game.home_team_id, game.away_team_id])
        expected_names = {game.home_team_id: schedule_game.home_team_name,
                          game.away_team_id: schedule_game.away_team_name}
        provider_teams = raw_by_pk[schedule_game.mlb_game_id]['teams']
        expected_provider_ids = {game.home_team_id: provider_teams['home']['team'].get('id'),
                                 game.away_team_id: provider_teams['away']['team'].get('id')}
        if (len(teams) != 2 or {row['team_id'] for row in teams} != set(expected_names)
            or any(normalize_team_name(row['name']) != normalize_team_name(expected_names[row['team_id']])
                   or type(expected_provider_ids[row['team_id']]) is not int
                   or row['mlb_team_id'] != expected_provider_ids[row['team_id']] for row in teams)):
            raise OperatorRefusal('Schedule franchise orientation differs from canonical identity')
        external_starters = (schedule_game.home_starting_pitcher_mlb_id, schedule_game.away_starting_pitcher_mlb_id)
        if any(type(identifier) is not int or identifier <= 0 or identifier not in starter_mapping
               for identifier in external_starters):
            raise OperatorRefusal('Both authoritative canonical starters must be prepared before this adapter')
        canonical_starters = tuple(starter_mapping[identifier] for identifier in external_starters)
        sources = reader.rows('mlb_starters', ids=list(canonical_starters))
        if (len(sources) != 2 or len(set(canonical_starters)) != 2
            or {(row['baseball_player_id'], row['external_player_id']) for row in sources}
               != set(zip(canonical_starters, map(str, external_starters)))):
            raise OperatorRefusal('Missing, ambiguous or conflicting canonical starter claim')
        resolved.append((schedule_game, game, canonical_starters))
    ids = tuple(game.game_id for _, game, _ in resolved)
    if (len(ids) != len(set(ids)) or len(slate) != len(ids)
        or {row['game_id'] for row in slate} != set(ids)):
        raise OperatorRefusal('Schedule differs from the complete retained canonical slate')
    if resolved:
        report = check_feature_history(target_date=target_date, target_game_ids=ids,
            starting_pitcher_ids=tuple(identifier for _, _, pair in resolved for identifier in pair),
            cutoff_time=reader.cutoff_time, target=None, connection_factory=reader)
        if report.get('status') != 'PASS':
            raise OperatorRefusal('Independent H-1 is incomplete; analytical execution remains held')
    # No provider/ambient model loading or reservation occurred before these gates.
    run_id = reader.reserve_run(target_date=target_date, run_type=run_type,
        model_version=model_package.model_version, feature_schema_version=model_package.feature_schema_version,
        model_artifact_sha256=model_package.model_artifact_sha256,
        model_training_cutoff=model_package.model_training_cutoff)
    predictions = []
    try:
        service = _knowledge_feature_service(reader)
        for schedule_game, game, starters in resolved:
            vector = service.generate_for_game_record(game=game, cutoff_time=reader.cutoff_time,
                home_starting_pitcher_id=starters[0], away_starting_pitcher_id=starters[1])
            flattened = flatten_game_feature_vector(vector)
            if (vector.game_id != game.game_id or vector.game_start_time != game.game_start_time
                or vector.feature_time != reader.cutoff_time or vector.home_team.team_id != game.home_team_id
                or vector.away_team.team_id != game.away_team_id
                or vector.feature_schema_version != model_package.feature_schema_version
                or tuple(flattened) != model_package.model.transformer.source_feature_names):
                raise OperatorRefusal('Generated features differ from the frozen model contract')
            # Refresh even if a feature family returned an empty result. A changed
            # receipt/state refuses before model invocation and again at persistence.
            current = reader.game(game.game_id)
            if current != game:
                raise OperatorRefusal('Canonical game changed during feature assembly')
            home_probability = model_package.model.predict_home_win_probability(flattened)
            if type(home_probability) not in (float, int) or not isfinite(home_probability) or not 0 <= home_probability <= 1:
                raise OperatorRefusal('Invalid model probability')
            home_probability = float(home_probability)
            away_probability = 1.0 - home_probability
            predicted_team = game.home_team_id if home_probability >= away_probability else game.away_team_id
            probability = max(home_probability, away_probability)
            missing = sum(value is None for value in flattened.values())
            reader.insert_prediction(MoneylineGamePrediction(run_id, game.game_id, schedule_game.mlb_game_id,
                game.game_start_time, reader.cutoff_time, game.home_team_id, game.away_team_id,
                starters[0], starters[1], schedule_game.home_starting_pitcher_mlb_id,
                schedule_game.away_starting_pitcher_mlb_id, vector.home_starting_pitcher.starter_available,
                vector.away_starting_pitcher.starter_available, 'both', missing,
                home_probability, away_probability, predicted_team, probability))
            predictions.append(MoneylinePredictionResult(game.game_id, schedule_game.mlb_game_id,
                game.game_start_time, schedule_game.home_team_name, schedule_game.away_team_name,
                schedule_game.home_starting_pitcher_name, schedule_game.away_starting_pitcher_name,
                'both', home_probability, away_probability,
                schedule_game.home_team_name if predicted_team == game.home_team_id else schedule_game.away_team_name,
                probability, missing))
        reader.finish_run(run_id=run_id, outcome='completed', games_received=len(raw_games),
            predictions_created=len(predictions), games_skipped=len(raw_games)-len(predictions))
    except Exception as error:
        # A lost acknowledgement may already have committed. Never attempt a
        # second lifecycle action in that case, or treat absent evidence as rollback.
        if isinstance(error, OperatorRefusal) and 'UNKNOWN' in str(error):
            raise
        try:
            reader.finish_run(run_id=run_id, outcome='failed', games_received=len(raw_games),
                predictions_created=len(predictions), games_skipped=len(raw_games)-len(predictions),
                error_message='Certified analytical stage refused; original proof and partial evidence retained')
        except Exception:
            raise OperatorRefusal('Run outcome requires read-only inspection; no automatic retry') from None
        raise
    return MoneylinePredictionRunResult(run_id, target_date, reader.cutoff_time, model_package.model_version,
        model_package.feature_schema_version, len(raw_games), len(predictions), len(raw_games)-len(predictions), tuple(predictions))
