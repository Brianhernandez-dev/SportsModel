from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from sportsmodel.database.connection import get_connection
from sportsmodel.settlement.moneyline_paper_service import (
    MoneylinePaperSettlementRunResult,
    settle_moneyline_paper_candidate_run,
)


ConnectionFactory = Callable[[], Any]
SettlementRunner = Callable[..., MoneylinePaperSettlementRunResult]


@dataclass(frozen=True)
class MoneylineEarlyEntryPerformance:
    """Flat one-unit performance for the Early Entry cohort."""

    total_qualified_bets: int
    settled_bets: int
    wins: int
    losses: int
    pushes: int
    pending: int
    total_staked_units: Decimal
    profit_units: Decimal
    roi: Decimal


@dataclass(frozen=True)
class MoneylineEarlyEntrySettlementResult:
    """Settlement and performance result for one target date."""

    target_date: date
    prediction_run_id: int | None
    odds_ingestion_run_id: int | None
    settlement_result: MoneylinePaperSettlementRunResult | None
    performance: MoneylineEarlyEntryPerformance


def settle_moneyline_early_entry(
    *,
    target_date: date,
    connection_factory: ConnectionFactory = get_connection,
    settlement_runner: SettlementRunner = (
        settle_moneyline_paper_candidate_run
    ),
) -> MoneylineEarlyEntrySettlementResult:
    """Settle one preview plus late-night Early Entry cohort."""

    cohort_ids = _load_early_entry_cohort_ids(
        target_date=target_date,
        connection_factory=connection_factory,
    )

    settlement_result = None

    if cohort_ids is not None:
        prediction_run_id, odds_ingestion_run_id = cohort_ids
        settlement_result = settlement_runner(
            prediction_run_id=prediction_run_id,
            odds_ingestion_run_id=odds_ingestion_run_id,
            connection_factory=connection_factory,
        )
    else:
        prediction_run_id = None
        odds_ingestion_run_id = None

    performance = load_moneyline_early_entry_performance(
        target_date=target_date,
        connection_factory=connection_factory,
    )

    return MoneylineEarlyEntrySettlementResult(
        target_date=target_date,
        prediction_run_id=prediction_run_id,
        odds_ingestion_run_id=odds_ingestion_run_id,
        settlement_result=settlement_result,
        performance=performance,
    )


def load_moneyline_early_entry_performance(
    *,
    target_date: date | None = None,
    connection_factory: ConnectionFactory = get_connection,
) -> MoneylineEarlyEntryPerformance:
    """Return isolated Early Entry performance, optionally by date."""

    connection = connection_factory()

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    COUNT(*),
                    COUNT(settlement
                        .moneyline_paper_candidate_settlement_id),
                    COUNT(*) FILTER (
                        WHERE settlement.outcome = 'win'
                    ),
                    COUNT(*) FILTER (
                        WHERE settlement.outcome = 'loss'
                    ),
                    COUNT(*) FILTER (
                        WHERE settlement.outcome = 'push'
                    ),
                    COALESCE(
                        SUM(settlement.profit_units),
                        0
                    )
                FROM moneyline_prediction_market_evaluations
                    AS evaluation
                JOIN moneyline_game_predictions AS prediction
                  ON prediction.moneyline_game_prediction_id =
                     evaluation.moneyline_game_prediction_id
                JOIN moneyline_prediction_runs AS prediction_run
                  ON prediction_run.moneyline_prediction_run_id =
                     prediction.moneyline_prediction_run_id
                JOIN odds_ingestion_runs AS odds_run
                  ON odds_run.odds_ingestion_run_id =
                     evaluation.odds_ingestion_run_id
                LEFT JOIN moneyline_paper_candidate_settlements
                    AS settlement
                  ON settlement
                     .moneyline_prediction_market_evaluation_id =
                     evaluation
                     .moneyline_prediction_market_evaluation_id
                WHERE
                    prediction_run.run_type = 'preview'
                    AND odds_run.snapshot_role = 'late_night'
                    AND prediction_run
                        .moneyline_prediction_run_id = (
                            SELECT candidate_run
                                .moneyline_prediction_run_id
                            FROM moneyline_prediction_runs
                                AS candidate_run
                            WHERE
                                candidate_run.target_date =
                                    prediction_run.target_date
                                AND candidate_run.run_type = 'preview'
                                AND candidate_run.status = 'completed'
                            ORDER BY
                                candidate_run.completed_at DESC,
                                candidate_run
                                .moneyline_prediction_run_id DESC
                            LIMIT 1
                        )
                    AND odds_run.odds_ingestion_run_id = (
                        SELECT candidate_odds.odds_ingestion_run_id
                        FROM odds_ingestion_runs AS candidate_odds
                        WHERE
                            candidate_odds.target_date =
                                prediction_run.target_date
                            AND candidate_odds.snapshot_role =
                                'late_night'
                            AND candidate_odds.status = 'completed'
                        ORDER BY
                            candidate_odds.odds_ingestion_run_id DESC
                        LIMIT 1
                    )
                    AND evaluation.qualifies_as_paper_candidate
                        IS TRUE
                    AND (
                        %s::date IS NULL
                        OR prediction_run.target_date = %s
                    );
                """,
                (target_date, target_date),
            )
            row = cursor.fetchone()
    finally:
        connection.close()

    if row is None:
        raise RuntimeError(
            "Early Entry performance query returned no row."
        )

    total_qualified_bets = row[0]
    settled_bets = row[1]
    profit_units = row[5]
    total_staked_units = Decimal(settled_bets)
    roi = (
        profit_units / total_staked_units
        if total_staked_units
        else Decimal("0")
    )

    return MoneylineEarlyEntryPerformance(
        total_qualified_bets=total_qualified_bets,
        settled_bets=settled_bets,
        wins=row[2],
        losses=row[3],
        pushes=row[4],
        pending=total_qualified_bets - settled_bets,
        total_staked_units=total_staked_units,
        profit_units=profit_units,
        roi=roi,
    )


def _load_early_entry_cohort_ids(
    *,
    target_date: date,
    connection_factory: ConnectionFactory,
) -> tuple[int, int] | None:
    connection = connection_factory()

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    prediction_run.moneyline_prediction_run_id,
                    odds_run.odds_ingestion_run_id
                FROM moneyline_prediction_runs AS prediction_run
                CROSS JOIN odds_ingestion_runs AS odds_run
                WHERE
                    prediction_run.target_date = %s
                    AND prediction_run.run_type = 'preview'
                    AND prediction_run.status = 'completed'
                    AND odds_run.target_date = %s
                    AND odds_run.snapshot_role = 'late_night'
                    AND odds_run.status = 'completed'
                ORDER BY
                    prediction_run.completed_at DESC,
                    prediction_run.moneyline_prediction_run_id DESC,
                    odds_run.odds_ingestion_run_id DESC
                LIMIT 1;
                """,
                (target_date, target_date),
            )
            row = cursor.fetchone()
    finally:
        connection.close()

    if row is None:
        return None

    return row[0], row[1]
