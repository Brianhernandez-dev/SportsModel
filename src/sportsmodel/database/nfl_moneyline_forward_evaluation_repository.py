from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID


@dataclass(frozen=True)
class NFLMoneylineForwardEvidence:
    prediction_id: int
    prediction_run_id: int
    run_key: UUID
    run_type: str
    protocol_version: str
    prediction_set_sha256: str
    game_id: int
    season: int
    target_kickoff: datetime
    prediction_created_at: datetime
    home_team_id: int
    away_team_id: int
    canonical_kickoff: datetime
    canonical_home_team_id: int
    canonical_away_team_id: int
    game_status: str
    home_score: int | None
    away_score: int | None
    home_prior_games: int
    away_prior_games: int
    route: str
    routing_contract_version: str
    model_specification_version: str
    feature_schema_version: str
    specification_fingerprint: str
    model_fingerprint: str
    home_win_probability: Decimal
    baseline_home_win_probability: Decimal
    classification_threshold: Decimal
    predicted_side: str


def list_nfl_moneyline_forward_evidence(
    cursor: Any,
    *,
    season: int,
    protocol_version: str,
    run_type: str = "official",
    slate_start_time: datetime | None = None,
    slate_end_time: datetime | None = None,
    route: str | None = None,
) -> tuple[NFLMoneylineForwardEvidence, ...]:
    conditions = [
        "prediction.season = %s",
        "prediction.evaluation_protocol_version = %s",
        "prediction.run_type = %s",
        "run.status = 'completed'",
    ]
    parameters: list[Any] = [season, protocol_version, run_type]
    if slate_start_time is not None:
        conditions.append("prediction.target_kickoff >= %s")
        parameters.append(slate_start_time)
    if slate_end_time is not None:
        conditions.append("prediction.target_kickoff < %s")
        parameters.append(slate_end_time)
    if route is not None:
        conditions.append("prediction.selected_route = %s")
        parameters.append(route)

    cursor.execute(
        f"""
        SELECT prediction.nfl_moneyline_game_prediction_id,
               run.nfl_moneyline_prediction_run_id, run.run_key,
               prediction.run_type, prediction.evaluation_protocol_version,
               run.prediction_set_sha256, prediction.game_id,
               prediction.season, prediction.target_kickoff,
               prediction.prediction_created_at, prediction.home_team_id,
               prediction.away_team_id, nfl.scheduled_start_time,
               game.home_team_id, game.away_team_id, nfl.status,
               nfl.home_score, nfl.away_score,
               prediction.home_current_prior_games,
               prediction.away_current_prior_games,
               prediction.selected_route,
               prediction.routing_contract_version,
               prediction.selected_model_specification_version,
               prediction.feature_schema_version,
               prediction.specification_fingerprint,
               prediction.model_fingerprint,
               prediction.model_home_win_probability,
               prediction.frozen_route_home_baseline_probability,
               prediction.classification_threshold,
               prediction.predicted_side
        FROM nfl_moneyline_game_predictions AS prediction
        JOIN nfl_moneyline_prediction_runs AS run
          ON run.nfl_moneyline_prediction_run_id =
             prediction.nfl_moneyline_prediction_run_id
        JOIN nfl_games AS nfl ON nfl.game_id = prediction.game_id
        JOIN games AS game ON game.game_id = prediction.game_id
        WHERE {' AND '.join(conditions)}
        ORDER BY prediction.target_kickoff, prediction.game_id,
                 prediction.nfl_moneyline_game_prediction_id;
        """,
        tuple(parameters),
    )
    return tuple(NFLMoneylineForwardEvidence(*row) for row in cursor.fetchall())
