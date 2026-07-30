from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sportsmodel.database.connection import (
    get_connection,
)


ConnectionFactory = Callable[[], Any]


@dataclass(frozen=True)
class MoneylineLivePipelineAudit:
    """
    Read-only integrity summary for one live Moneyline slate.
    """

    prediction_run_id: int
    odds_ingestion_run_id: int
    policy_version: str

    prediction_run_status: str | None
    odds_ingestion_run_status: str | None

    predictions: int
    prediction_games: int

    odds_snapshots: int
    odds_games: int

    evaluations: int
    evaluated_predictions: int

    paper_candidates: int
    settlements: int
    pending_candidates: int

    duplicate_prediction_games: int
    duplicate_evaluations: int
    duplicate_settlements: int

    pipeline_state: str
    integrity_issues: tuple[str, ...]


AUDIT_QUERY = """
    WITH prediction_scope AS (
        SELECT
            prediction.moneyline_game_prediction_id,
            prediction.game_id
        FROM moneyline_game_predictions AS prediction
        WHERE
            prediction.moneyline_prediction_run_id = %s
    ),
    snapshot_scope AS (
        SELECT
            snapshot.odds_market_snapshot_id,
            snapshot.game_id
        FROM odds_market_snapshots AS snapshot
        WHERE
            snapshot.odds_ingestion_run_id = %s
            AND snapshot.market_type = 'h2h'
            AND snapshot.game_id IN (
                SELECT game_id
                FROM prediction_scope
            )
    ),
    evaluation_scope AS (
        SELECT
            evaluation
                .moneyline_prediction_market_evaluation_id,
            evaluation.moneyline_game_prediction_id,
            evaluation.qualifies_as_paper_candidate
        FROM moneyline_prediction_market_evaluations
            AS evaluation
        JOIN prediction_scope AS prediction
          ON prediction.moneyline_game_prediction_id =
             evaluation.moneyline_game_prediction_id
        WHERE
            evaluation.odds_ingestion_run_id = %s
            AND evaluation.policy_version = %s
    ),
    settlement_scope AS (
        SELECT
            settlement
                .moneyline_paper_candidate_settlement_id,
            settlement
                .moneyline_prediction_market_evaluation_id
        FROM moneyline_paper_candidate_settlements
            AS settlement
        JOIN evaluation_scope AS evaluation
          ON evaluation
             .moneyline_prediction_market_evaluation_id =
             settlement
             .moneyline_prediction_market_evaluation_id
    )
    SELECT
        (
            SELECT status
            FROM moneyline_prediction_runs
            WHERE moneyline_prediction_run_id = %s
        ) AS prediction_run_status,

        (
            SELECT status
            FROM odds_ingestion_runs
            WHERE odds_ingestion_run_id = %s
        ) AS odds_ingestion_run_status,

        (
            SELECT COUNT(*)
            FROM prediction_scope
        ) AS predictions,

        (
            SELECT COUNT(DISTINCT game_id)
            FROM prediction_scope
        ) AS prediction_games,

        (
            SELECT COUNT(*)
            FROM snapshot_scope
        ) AS odds_snapshots,

        (
            SELECT COUNT(DISTINCT game_id)
            FROM snapshot_scope
        ) AS odds_games,

        (
            SELECT COUNT(*)
            FROM evaluation_scope
        ) AS evaluations,

        (
            SELECT COUNT(
                DISTINCT moneyline_game_prediction_id
            )
            FROM evaluation_scope
        ) AS evaluated_predictions,

        (
            SELECT COUNT(*)
            FROM evaluation_scope
            WHERE qualifies_as_paper_candidate IS TRUE
        ) AS paper_candidates,

        (
            SELECT COUNT(*)
            FROM settlement_scope
        ) AS settlements,

        (
            SELECT
                COUNT(*)
                - COUNT(DISTINCT game_id)
            FROM prediction_scope
        ) AS duplicate_prediction_games,

        (
            SELECT
                COUNT(*)
                - COUNT(
                    DISTINCT moneyline_game_prediction_id
                )
            FROM evaluation_scope
        ) AS duplicate_evaluations,

        (
            SELECT
                COUNT(*)
                - COUNT(
                    DISTINCT
                    moneyline_prediction_market_evaluation_id
                )
            FROM settlement_scope
        ) AS duplicate_settlements;
"""


def audit_moneyline_live_pipeline(
    *,
    prediction_run_id: int,
    odds_ingestion_run_id: int,
    policy_version: str = "1.0.0",
    connection_factory: ConnectionFactory = get_connection,
) -> MoneylineLivePipelineAudit:
    """
    Audit one prediction, odds, evaluation, and settlement chain.
    """

    _validate_positive_identifier(
        value=prediction_run_id,
        field_name="Prediction run ID",
    )

    _validate_positive_identifier(
        value=odds_ingestion_run_id,
        field_name="Odds ingestion run ID",
    )

    normalized_policy_version = policy_version.strip()

    if not normalized_policy_version:
        raise ValueError(
            "Policy version cannot be blank."
        )

    connection = connection_factory()

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                AUDIT_QUERY,
                (
                    prediction_run_id,
                    odds_ingestion_run_id,
                    odds_ingestion_run_id,
                    normalized_policy_version,
                    prediction_run_id,
                    odds_ingestion_run_id,
                ),
            )

            row = cursor.fetchone()

        if row is None:
            raise RuntimeError(
                "Moneyline live pipeline audit returned no row."
            )

        return _build_audit(
            prediction_run_id=prediction_run_id,
            odds_ingestion_run_id=odds_ingestion_run_id,
            policy_version=normalized_policy_version,
            row=row,
        )

    finally:
        connection.close()


def _build_audit(
    *,
    prediction_run_id: int,
    odds_ingestion_run_id: int,
    policy_version: str,
    row: tuple[Any, ...],
) -> MoneylineLivePipelineAudit:
    (
        prediction_status,
        odds_status,
        predictions,
        prediction_games,
        odds_snapshots,
        odds_games,
        evaluations,
        evaluated_predictions,
        paper_candidates,
        settlements,
        duplicate_prediction_games,
        duplicate_evaluations,
        duplicate_settlements,
    ) = row

    pending_candidates = max(
        paper_candidates - settlements,
        0,
    )

    issues: list[str] = []

    if prediction_status is None:
        issues.append(
            "prediction_run_not_found"
        )
    elif prediction_status != "completed":
        issues.append(
            "prediction_run_not_completed"
        )

    if odds_status is None:
        issues.append(
            "odds_ingestion_run_not_found"
        )
    elif odds_status != "completed":
        issues.append(
            "odds_ingestion_run_not_completed"
        )

    if predictions == 0:
        issues.append(
            "prediction_run_has_no_predictions"
        )

    if duplicate_prediction_games:
        issues.append(
            "duplicate_prediction_games"
        )

    if duplicate_evaluations:
        issues.append(
            "duplicate_evaluations"
        )

    if duplicate_settlements:
        issues.append(
            "duplicate_settlements"
        )

    if evaluations > predictions:
        issues.append(
            "evaluation_count_exceeds_predictions"
        )

    if paper_candidates > evaluations:
        issues.append(
            "candidate_count_exceeds_evaluations"
        )

    if settlements > paper_candidates:
        issues.append(
            "settlement_count_exceeds_candidates"
        )

    pipeline_state = _determine_pipeline_state(
        issues=issues,
        predictions=predictions,
        evaluated_predictions=evaluated_predictions,
        paper_candidates=paper_candidates,
        settlements=settlements,
    )

    return MoneylineLivePipelineAudit(
        prediction_run_id=prediction_run_id,
        odds_ingestion_run_id=odds_ingestion_run_id,
        policy_version=policy_version,
        prediction_run_status=prediction_status,
        odds_ingestion_run_status=odds_status,
        predictions=predictions,
        prediction_games=prediction_games,
        odds_snapshots=odds_snapshots,
        odds_games=odds_games,
        evaluations=evaluations,
        evaluated_predictions=evaluated_predictions,
        paper_candidates=paper_candidates,
        settlements=settlements,
        pending_candidates=pending_candidates,
        duplicate_prediction_games=(
            duplicate_prediction_games
        ),
        duplicate_evaluations=(
            duplicate_evaluations
        ),
        duplicate_settlements=(
            duplicate_settlements
        ),
        pipeline_state=pipeline_state,
        integrity_issues=tuple(issues),
    )


def _determine_pipeline_state(
    *,
    issues: list[str],
    predictions: int,
    evaluated_predictions: int,
    paper_candidates: int,
    settlements: int,
) -> str:
    if issues:
        return "invalid"

    if evaluated_predictions < predictions:
        return "awaiting_evaluations"

    if settlements < paper_candidates:
        return "awaiting_results"

    return "complete"


def _validate_positive_identifier(
    *,
    value: int,
    field_name: str,
) -> None:
    if value <= 0:
        raise ValueError(
            f"{field_name} must be greater than zero."
        )
