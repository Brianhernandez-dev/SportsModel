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
    cohort_settlements: tuple[
        "MoneylineEarlyEntryCohortSettlement",
        ...,
    ]
    performance: MoneylineEarlyEntryPerformance


@dataclass(frozen=True)
class MoneylineEarlyEntryCohortSettlement:
    """One persisted Early Entry prediction/odds cohort."""

    prediction_run_id: int
    odds_ingestion_run_id: int
    settlement_result: MoneylinePaperSettlementRunResult


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

    cohort_settlements = []

    for prediction_run_id, odds_ingestion_run_id in cohort_ids:
        settlement_result = settlement_runner(
            prediction_run_id=prediction_run_id,
            odds_ingestion_run_id=odds_ingestion_run_id,
            connection_factory=connection_factory,
        )
        cohort_settlements.append(
            MoneylineEarlyEntryCohortSettlement(
                prediction_run_id=prediction_run_id,
                odds_ingestion_run_id=odds_ingestion_run_id,
                settlement_result=settlement_result,
            )
        )

    performance = load_moneyline_early_entry_performance(
        target_date=target_date,
        connection_factory=connection_factory,
    )

    return MoneylineEarlyEntrySettlementResult(
        target_date=target_date,
        cohort_settlements=tuple(cohort_settlements),
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
) -> tuple[tuple[int, int], ...]:
    connection = connection_factory()

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT DISTINCT
                    prediction_run.moneyline_prediction_run_id,
                    odds_run.odds_ingestion_run_id
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
                WHERE
                    prediction_run.target_date = %s
                    AND prediction_run.run_type = 'preview'
                    AND odds_run.target_date = %s
                    AND odds_run.snapshot_role = 'late_night'
                    AND evaluation.qualifies_as_paper_candidate
                        IS TRUE
                ORDER BY
                    prediction_run.moneyline_prediction_run_id,
                    odds_run.odds_ingestion_run_id;
                """,
                (target_date, target_date),
            )
            rows = cursor.fetchall()
    finally:
        connection.close()

    return tuple(
        (row[0], row[1])
        for row in rows
    )
