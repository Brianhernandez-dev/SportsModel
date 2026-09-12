"""Read-only PostgreSQL snapshot for NFL historical probability evidence."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import replace
from datetime import timezone
from typing import Any

from sportsmodel.database.nfl_game_repository import (
    list_nfl_games_by_season_range,
)
from sportsmodel.database.nfl_team_game_statistics_repository import (
    list_all_nfl_completed_history,
)
from sportsmodel.nfl.dataset_audit import (
    SnapshotNflTeamHistoryRepository,
    dataset_fingerprint,
)
from sportsmodel.nfl.early_dataset_audit import early_dataset_fingerprint
from sportsmodel.nfl.early_features import NFL_EARLY_MONEYLINE_FEATURE_NAMES
from sportsmodel.nfl.early_moneyline_baseline import (
    build_nfl_early_modeling_examples,
)
from sportsmodel.nfl.early_moneyline_dataset import (
    NFLEarlyMoneylineTrainingDatasetBuilder,
)
from sportsmodel.nfl.features import NFLFeatureDataProvider
from sportsmodel.nfl.historical_probability_evidence import (
    ForwardExposure,
    HistoricalEvidenceInput,
    HistoricalScoreTarget,
    HistoricalTrainingRecord,
)
from sportsmodel.nfl.models import NflGameStatus, NflSeasonType
from sportsmodel.nfl.moneyline_baseline import (
    build_nfl_moneyline_modeling_examples,
)
from sportsmodel.nfl.moneyline_dataset import NFLMoneylineTrainingDatasetBuilder
from sportsmodel.nfl.moneyline_frozen import (
    EARLY_FEATURE_NAMES,
    MATURE_FEATURE_NAMES,
    fingerprint_payload,
    load_frozen_nfl_early_artifact,
    load_frozen_nfl_mature_artifact,
)
from sportsmodel.nfl.moneyline_inference import _infer_nfl_moneyline
from sportsmodel.nfl.moneyline_routing import NFLMoneylineRoute


def load_historical_evidence_input(
    cursor: Any,
    *,
    repository_revision: str,
) -> HistoricalEvidenceInput:
    """Load one pinned snapshot; caller must own a read-only repeatable transaction."""

    _require_read_only_repeatable_transaction(cursor)
    (
        reconstruction_as_of,
        database_identity,
        server_identity,
        transaction_snapshot,
    ) = _capture_snapshot_identity(cursor)
    games = list_nfl_games_by_season_range(
        cursor, season_from=2018, season_to=2026
    )
    if len({game.game_id for game in games}) != len(games):
        raise ValueError("duplicate canonical NFL game IDs in snapshot")
    history = list_all_nfl_completed_history(
        cursor, season_from=2017, season_to=2025
    )
    team_names = _load_team_names(cursor, games)
    game_sources, game_observations, stats_observations, snapshots, findings = (
        _load_source_provenance(cursor, games)
    )

    development_games = tuple(game for game in games if game.season <= 2024)
    mature_snapshot = SnapshotNflTeamHistoryRepository(history)
    mature_dataset = NFLMoneylineTrainingDatasetBuilder(
        provider_factory=lambda game: NFLFeatureDataProvider(
            game, repository=mature_snapshot.for_target(game)
        )
    ).build(development_games)
    mature_examples = build_nfl_moneyline_modeling_examples(
        mature_dataset.rows, development_games
    )
    mature_eligible = tuple(
        item for item in mature_examples
        if item.home_prior_games >= 3 and item.away_prior_games >= 3
    )
    mature_artifact = load_frozen_nfl_mature_artifact()
    mature_training_fingerprint = fingerprint_payload([
        {
            "game_id": item.game_id,
            "kickoff": item.kickoff.astimezone(timezone.utc).isoformat(),
            "season": item.season,
            "season_type": item.season_type.value,
            "home_win": item.home_win,
            "home_prior_games": item.home_prior_games,
            "away_prior_games": item.away_prior_games,
            "feature_values": list(item.feature_values),
        }
        for item in mature_eligible
    ])
    if mature_training_fingerprint != mature_artifact.dataset_fingerprint:
        raise ValueError(
            "current mature reconstruction differs from the locked historical dataset"
        )

    early_games = tuple(
        game for game in development_games if 2019 <= game.season <= 2024
    )
    early_snapshot = SnapshotNflTeamHistoryRepository(history)
    early_dataset = NFLEarlyMoneylineTrainingDatasetBuilder(
        provider_factory=lambda game: NFLFeatureDataProvider(
            game, repository=early_snapshot.for_target(game)
        )
    ).build(early_games)
    early_fingerprint = early_dataset_fingerprint(early_dataset.rows)
    early_artifact = load_frozen_nfl_early_artifact()
    if early_fingerprint != early_artifact.dataset_fingerprint:
        raise ValueError(
            "current early reconstruction differs from the locked historical dataset"
        )
    early_examples = build_nfl_early_modeling_examples(early_dataset.rows)
    (
        training_game_dependency_ids,
        training_statistics_dependency_game_ids,
    ) = _derive_training_reconstruction_dependencies(
        mature_rows=mature_dataset.rows,
        mature_traces=tuple(mature_snapshot.traces),
        early_rows=early_dataset.rows,
    )
    snapshots = _annotate_training_reconstruction_contributions(
        snapshots,
        game_observations=game_observations,
        stats_observations=stats_observations,
        game_dependency_ids=training_game_dependency_ids,
        statistics_dependency_game_ids=training_statistics_dependency_game_ids,
    )

    training = tuple(sorted((
        *(
            HistoricalTrainingRecord(
                canonical_game_id=item.game_id,
                kickoff=item.kickoff,
                season=item.season,
                route=NFLMoneylineRoute.MATURE,
                feature_names=MATURE_FEATURE_NAMES,
                feature_values=item.feature_values,
                home_win=item.home_win,
            )
            for item in mature_eligible
        ),
        *(
            HistoricalTrainingRecord(
                canonical_game_id=item.game_id,
                kickoff=item.kickoff,
                season=item.season,
                route=NFLMoneylineRoute.EARLY,
                feature_names=EARLY_FEATURE_NAMES,
                feature_values=tuple(
                    item.feature_values[NFL_EARLY_MONEYLINE_FEATURE_NAMES.index(name)]
                    for name in EARLY_FEATURE_NAMES
                ),
                home_win=item.home_win,
            )
            for item in early_examples
        ),
    ), key=lambda item: (item.kickoff, item.canonical_game_id, item.route.value)))

    score_snapshot = SnapshotNflTeamHistoryRepository(history)
    score_targets: list[HistoricalScoreTarget] = []
    for game in games:
        if not 2021 <= game.season <= 2025:
            continue
        if game.status is not NflGameStatus.FINAL:
            continue
        if game.season_type not in {NflSeasonType.REGULAR, NflSeasonType.POSTSEASON}:
            continue
        outcome_free = replace(
            game,
            status=NflGameStatus.UNPLAYED,
            home_score=None,
            away_score=None,
            overtime=None,
        )
        inference = _infer_nfl_moneyline(
            outcome_free,
            provider=NFLFeatureDataProvider(
                outcome_free, repository=score_snapshot.for_target(outcome_free)
            ),
            early_artifact_loader=lambda: early_artifact,
            mature_artifact_loader=lambda: mature_artifact,
            require_forward_target=False,
        )
        source_name, external_game_id = _require_game_source(
            game_sources, game.game_id
        )
        source_trace, target_snapshot_as_of = _build_source_trace(
            game_id=game.game_id,
            inference=inference,
            game_observations=game_observations,
            stats_observations=stats_observations,
        )
        score_targets.append(HistoricalScoreTarget(
            canonical_game_id=game.game_id,
            kickoff=game.scheduled_start_time,
            season=game.season,
            season_type=game.season_type.value,
            week=game.week,
            week_label=game.week_label,
            home_team_id=game.home_team_id,
            away_team_id=game.away_team_id,
            home_team=team_names[(game.home_team_id, game.season)],
            away_team=team_names[(game.away_team_id, game.season)],
            neutral_site=game.neutral_site,
            home_current_prior_games=inference.home_current_prior_games,
            away_current_prior_games=inference.away_current_prior_games,
            route=inference.selected_route,
            feature_names=inference.ordered_feature_names,
            feature_values=inference.ordered_feature_values,
            source_trace=source_trace,
            source_snapshot_as_of=target_snapshot_as_of,
            source_name=source_name,
            external_game_id=external_game_id,
        ))

    all_observation_times = [
        item["observed_at"]
        for grouped in (*game_observations.values(), *stats_observations.values())
        for item in grouped
    ]
    if not all_observation_times:
        raise ValueError("historical source snapshot has no retained observations")
    loaded_source_snapshot_as_of = max(all_observation_times)
    return HistoricalEvidenceInput(
        reconstruction_as_of=reconstruction_as_of,
        loaded_source_snapshot_as_of=loaded_source_snapshot_as_of,
        repository_revision=repository_revision,
        database_identity=database_identity,
        server_identity=server_identity,
        transaction_snapshot=transaction_snapshot,
        training_records=training,
        score_targets=tuple(score_targets),
        forward_exposures=_load_forward_exposures(cursor),
        source_snapshot_metadata=tuple(snapshots),
        source_correction_findings=tuple(findings),
        locked_dataset_fingerprints={
            "mature_frozen_training": mature_training_fingerprint,
            "mature_full_development": dataset_fingerprint(mature_dataset.rows),
            "early_frozen_training": early_fingerprint,
        },
    )


def _require_read_only_repeatable_transaction(cursor: Any) -> None:
    cursor.execute("SHOW transaction_isolation;")
    isolation = str(cursor.fetchone()[0]).lower().replace("_", " ")
    cursor.execute("SHOW transaction_read_only;")
    read_only = str(cursor.fetchone()[0]).lower()
    if isolation != "repeatable read" or read_only not in {"on", "true", "1"}:
        raise RuntimeError(
            "historical evidence requires a read-only REPEATABLE READ transaction"
        )


def _capture_snapshot_identity(cursor: Any):
    """Capture non-secret source identity from the active export transaction."""

    cursor.execute(
        """
        SELECT transaction_timestamp(), current_database(), current_user,
               inet_server_addr()::text, inet_server_port(), version(),
               current_setting('server_version_num'), pg_is_in_recovery(),
               current_setting('transaction_isolation'),
               current_setting('transaction_read_only'),
               pg_current_snapshot()::text, txid_current_if_assigned();
        """
    )
    row = cursor.fetchone()
    connection_info = getattr(getattr(cursor, "connection", None), "info", None)
    configured_host = getattr(connection_info, "host", None)
    configured_port = getattr(connection_info, "port", None)
    database_identity = {
        "database": row[1],
        "user": row[2],
        "configured_host": configured_host,
        "configured_port": configured_port,
    }
    server_identity = {
        "server_address": row[3],
        "server_port": row[4],
        "postgresql_version": row[5],
        "server_version_num": row[6],
        "in_recovery": row[7],
    }
    transaction_snapshot = {
        "transaction_isolation": str(row[8]).lower().replace("_", " "),
        "transaction_read_only": str(row[9]).lower() in {"on", "true", "1"},
        "snapshot_id": row[10],
        "transaction_id_if_assigned": row[11],
    }
    return row[0], database_identity, server_identity, transaction_snapshot


def _load_team_names(cursor: Any, games) -> dict[tuple[int, int], str]:
    pairs = sorted({
        (team_id, game.season)
        for game in games
        for team_id in (game.home_team_id, game.away_team_id)
    })
    cursor.execute(
        """
        SELECT requested.team_id, requested.season,
               COALESCE(season.abbreviation, profile.current_abbreviation)
        FROM unnest(%s::integer[], %s::integer[]) AS requested(team_id, season)
        JOIN nfl_team_profiles profile ON profile.team_id = requested.team_id
        LEFT JOIN nfl_team_seasons season
          ON season.team_id = requested.team_id
         AND season.season = requested.season
        ORDER BY requested.team_id, requested.season;
        """,
        ([item[0] for item in pairs], [item[1] for item in pairs]),
    )
    result = {(row[0], row[1]): row[2] for row in cursor.fetchall()}
    if set(result) != set(pairs):
        raise ValueError("canonical game has missing NFL team identity")
    return result


def _load_source_provenance(cursor: Any, games):
    game_ids = sorted({game.game_id for game in games})
    cursor.execute(
        """
        SELECT game_id, source_name, external_game_id
        FROM game_sources
        WHERE game_id = ANY(%s)
        ORDER BY game_id, source_name, external_game_id;
        """,
        (game_ids,),
    )
    sources: dict[int, list[tuple[str, str]]] = defaultdict(list)
    for game_id, source_name, external_game_id in cursor.fetchall():
        sources[game_id].append((source_name, external_game_id))

    cursor.execute(
        """
        SELECT observation.game_id, observation.source_name,
               observation.external_game_id, observation.raw_row_sha256,
               observation.observed_at, observation.provider_updated_at,
               observation.anomaly_state, observation.override_provenance,
               run.nfl_ingestion_run_id, run.source_asset, run.source_sha256,
               run.retrieved_at, run.completed_at
        FROM nfl_game_source_observations observation
        JOIN nfl_ingestion_runs run
          ON run.nfl_ingestion_run_id = observation.nfl_ingestion_run_id
        WHERE observation.game_id = ANY(%s) AND run.status = 'completed'
        ORDER BY observation.game_id, observation.observed_at,
                 observation.nfl_game_source_observation_id;
        """,
        (game_ids,),
    )
    game_observations: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in cursor.fetchall():
        game_observations[row[0]].append(_observation(row))

    cursor.execute(
        """
        SELECT observation.game_id, observation.team_id,
               observation.source_name, observation.external_game_id,
               observation.provider_team_external_id,
               observation.raw_row_sha256, observation.observed_at,
               observation.provider_updated_at, run.nfl_ingestion_run_id,
               run.source_asset, run.source_sha256, run.retrieved_at,
               run.completed_at
        FROM nfl_team_game_statistics_source_observations observation
        JOIN nfl_ingestion_runs run
          ON run.nfl_ingestion_run_id = observation.nfl_ingestion_run_id
        WHERE observation.game_id = ANY(%s) AND run.status = 'completed'
        ORDER BY observation.game_id, observation.team_id,
                 observation.observed_at,
                 observation.nfl_team_game_statistics_source_observation_id;
        """,
        (game_ids,),
    )
    stats_observations: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
    for row in cursor.fetchall():
        stats_observations[(row[0], row[1])].append(_stats_observation(row))

    findings: list[dict[str, Any]] = []
    for game_id, observations in game_observations.items():
        identities = {(item["source_name"], item["external_game_id"]) for item in observations}
        if len(identities) != 1:
            raise ValueError(f"ambiguous retained game source observations: {game_id}")
        _reject_latest_timestamp_ambiguity(observations, f"game {game_id}")
        if len({item["raw_row_sha256"] for item in observations}) > 1:
            findings.append({
                "canonical_game_id": game_id,
                "kind": "game_source_correction_lineage",
                "observation_count": len(observations),
                "selected_raw_row_sha256": observations[-1]["raw_row_sha256"],
            })
    for key, observations in stats_observations.items():
        identities = {
            (item["source_name"], item["external_game_id"], item["provider_team_external_id"])
            for item in observations
        }
        if len(identities) != 1:
            raise ValueError(f"ambiguous retained statistics observations: {key}")
        _reject_latest_timestamp_ambiguity(observations, f"statistics {key}")
        if len({item["raw_row_sha256"] for item in observations}) > 1:
            findings.append({
                "canonical_game_id": key[0],
                "canonical_team_id": key[1],
                "kind": "statistics_source_correction_lineage",
                "observation_count": len(observations),
                "selected_raw_row_sha256": observations[-1]["raw_row_sha256"],
            })
    snapshots_by_run: dict[int, dict[str, Any]] = {}
    for observation_kind, grouped in (
        ("game", game_observations.values()),
        ("statistics", stats_observations.values()),
    ):
        for observations in grouped:
            for item in observations:
                snapshot = snapshots_by_run.setdefault(item["ingestion_run_id"], {
                    "ingestion_run_id": item["ingestion_run_id"],
                    "source_name": item["source_name"],
                    "source_asset": item["source_asset"],
                    "source_file_sha256": item["source_file_sha256"],
                    "retrieved_at": item["retrieved_at"],
                    "completed_at": item["completed_at"],
                    "loaded_game_observation_count": 0,
                    "loaded_statistics_observation_count": 0,
                    "loaded_observation_count": 0,
                    "loaded_source_snapshot_as_of": item["observed_at"],
                })
                snapshot[f"loaded_{observation_kind}_observation_count"] += 1
                snapshot["loaded_observation_count"] += 1
                snapshot["loaded_source_snapshot_as_of"] = max(
                    snapshot["loaded_source_snapshot_as_of"],
                    item["observed_at"],
                )
    return (
        {key: tuple(value) for key, value in sources.items()},
        {key: tuple(value) for key, value in game_observations.items()},
        {key: tuple(value) for key, value in stats_observations.items()},
        tuple(snapshots_by_run[key] for key in sorted(snapshots_by_run)),
        tuple(findings),
    )


def _annotate_training_reconstruction_contributions(
    snapshots,
    *,
    game_observations,
    stats_observations,
    game_dependency_ids: set[int],
    statistics_dependency_game_ids: set[int],
):
    contribution_counts: Counter[int] = Counter()
    latest_contributions: dict[int, Any] = {}
    for game_id, observations in game_observations.items():
        if game_id in game_dependency_ids:
            _count_snapshot_contributions(
                observations,
                contribution_counts,
                latest_contributions,
            )
    for (game_id, _), observations in stats_observations.items():
        if game_id in statistics_dependency_game_ids:
            _count_snapshot_contributions(
                observations,
                contribution_counts,
                latest_contributions,
            )
    return tuple({
        **snapshot,
        "training_reconstruction_observation_count": contribution_counts[
            snapshot["ingestion_run_id"]
        ],
        "training_reconstruction_source_snapshot_as_of": (
            latest_contributions.get(snapshot["ingestion_run_id"])
        ),
    } for snapshot in snapshots)


def _derive_training_reconstruction_dependencies(
    *,
    mature_rows,
    mature_traces,
    early_rows,
) -> tuple[set[int], set[int]]:
    """Return exact game-row and statistics provenance dependencies.

    ``mature_rows`` is the reconstructed full-development fingerprint
    population; ``early_rows`` is the retained frozen early-route population.
    """

    mature_target_ids = {
        _require_dependency_game_id(row.get("target_game_id"), "mature target")
        for row in mature_rows
    }
    mature_traces_by_target: dict[int, list[Any]] = defaultdict(list)
    for trace in mature_traces:
        mature_traces_by_target[trace.target_game_id].append(trace)
    missing_mature_traces = mature_target_ids - set(mature_traces_by_target)
    if missing_mature_traces:
        raise ValueError(
            "mature training reconstruction lacks feature-source traces: "
            f"{sorted(missing_mature_traces)}"
        )
    mature_source_ids = {
        _require_dependency_game_id(game_id, "mature feature source")
        for target_game_id in mature_target_ids
        for trace in mature_traces_by_target[target_game_id]
        for game_id in trace.source_game_ids
    }

    early_target_ids = {
        _require_dependency_game_id(row.get("target_game_id"), "early target")
        for row in early_rows
    }
    early_source_ids = {
        _require_dependency_game_id(game_id, "early feature source")
        for row in early_rows
        for key in (
            "home_prior_season_source_game_ids",
            "away_prior_season_source_game_ids",
            "home_current_season_source_game_ids",
            "away_current_season_source_game_ids",
        )
        for game_id in _require_dependency_game_id_collection(row, key)
    }
    feature_source_ids = mature_source_ids | early_source_ids
    return (
        mature_target_ids | early_target_ids | feature_source_ids,
        feature_source_ids,
    )


def _require_dependency_game_id_collection(row, key: str):
    value = row.get(key)
    if not isinstance(value, tuple):
        raise ValueError(f"training reconstruction row lacks {key}")
    return value


def _require_dependency_game_id(value, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{label} game ID is invalid")
    return value


def _count_snapshot_contributions(
    observations,
    contribution_counts: Counter[int],
    latest_contributions: dict[int, Any],
) -> None:
    for item in observations:
        run_id = item["ingestion_run_id"]
        contribution_counts[run_id] += 1
        latest_contributions[run_id] = max(
            item["observed_at"],
            latest_contributions.get(run_id, item["observed_at"]),
        )


def _observation(values) -> dict[str, Any]:
    return {
        "canonical_game_id": values[0],
        "source_name": values[1],
        "external_game_id": values[2],
        "raw_row_sha256": values[3],
        "observed_at": values[4],
        "provider_updated_at": values[5],
        "anomaly_state": values[6],
        "override_provenance": values[7],
        "ingestion_run_id": values[8],
        "source_asset": values[9],
        "source_file_sha256": values[10],
        "retrieved_at": values[11],
        "completed_at": values[12],
    }


def _stats_observation(values) -> dict[str, Any]:
    return {
        "canonical_game_id": values[0],
        "canonical_team_id": values[1],
        "source_name": values[2],
        "external_game_id": values[3],
        "provider_team_external_id": values[4],
        "raw_row_sha256": values[5],
        "observed_at": values[6],
        "provider_updated_at": values[7],
        "ingestion_run_id": values[8],
        "source_asset": values[9],
        "source_file_sha256": values[10],
        "retrieved_at": values[11],
        "completed_at": values[12],
    }


def _reject_latest_timestamp_ambiguity(observations, identity: str) -> None:
    latest = observations[-1]["observed_at"]
    hashes = {
        item["raw_row_sha256"] for item in observations
        if item["observed_at"] == latest
    }
    if len(hashes) > 1:
        raise ValueError(f"ambiguous equally-latest source observations: {identity}")


def _require_game_source(sources, game_id: int) -> tuple[str, str]:
    identities = tuple(sources.get(game_id, ()))
    if len(identities) != 1:
        raise ValueError(f"canonical game source identity is missing or ambiguous: {game_id}")
    return identities[0]


def _build_source_trace(
    *, game_id: int, inference, game_observations, stats_observations,
):
    target_observations = tuple(game_observations.get(game_id, ()))
    if not target_observations:
        raise ValueError(f"target game lacks retained source evidence: {game_id}")
    relevant = list(target_observations)
    channels = []
    for channel in inference.source_trace:
        games = []
        for source_game in channel.games:
            source_game_observations = tuple(
                game_observations.get(source_game.game_id, ())
            )
            team_observations = tuple(
                item
                for (candidate_game_id, _), observations in stats_observations.items()
                if candidate_game_id == source_game.game_id
                for item in observations
            )
            if not source_game_observations or not team_observations:
                raise ValueError(
                    f"feature source game lacks retained provenance: {source_game.game_id}"
                )
            relevant.extend(source_game_observations)
            relevant.extend(team_observations)
            games.append({
                "canonical_game_id": source_game.game_id,
                "kickoff": source_game.kickoff,
                "season": source_game.season,
                "season_type": source_game.season_type,
                "game_observations": [
                    _trace_observation(item)
                    for item in source_game_observations
                ],
                "statistics_observations": [
                    _trace_observation(item) for item in team_observations
                ],
            })
        channels.append({
            "side": channel.side,
            "channel": channel.channel,
            "games": games,
        })
    return ({
        "target_game": {
            "canonical_game_id": game_id,
            "game_observations": [_trace_observation(item) for item in target_observations],
        },
        "channels": channels,
    }, max(item["observed_at"] for item in relevant))


def _trace_observation(item: dict[str, Any]) -> dict[str, Any]:
    return {
        key: item[key]
        for key in (
            "canonical_game_id", "canonical_team_id", "source_name",
            "external_game_id", "provider_team_external_id", "raw_row_sha256",
            "observed_at", "provider_updated_at", "anomaly_state",
            "override_provenance", "ingestion_run_id", "source_asset",
            "source_file_sha256", "retrieved_at", "completed_at",
        )
        if key in item
    }


def _load_forward_exposures(cursor: Any) -> tuple[ForwardExposure, ...]:
    cursor.execute(
        """
        SELECT prediction.game_id,
               prediction.nfl_moneyline_prediction_run_id,
               prediction.nfl_moneyline_game_prediction_id,
               prediction.prediction_created_at, prediction.selected_route,
               prediction.selected_model_specification_version,
               prediction.model_fingerprint
        FROM nfl_moneyline_game_predictions prediction
        JOIN nfl_moneyline_prediction_runs run
          ON run.nfl_moneyline_prediction_run_id =
             prediction.nfl_moneyline_prediction_run_id
        WHERE prediction.season >= 2026
          AND run.status = 'completed'
          AND run.run_type = 'official'
          AND prediction.run_type = 'official'
        ORDER BY prediction.prediction_created_at,
                 prediction.nfl_moneyline_game_prediction_id;
        """
    )
    return tuple(
        ForwardExposure(
            canonical_game_id=row[0],
            prediction_run_id=row[1],
            prediction_id=row[2],
            prediction_created_at=row[3],
            route=NFLMoneylineRoute(row[4]),
            model_specification_version=row[5],
            model_fingerprint=row[6],
        )
        for row in cursor.fetchall()
    )
