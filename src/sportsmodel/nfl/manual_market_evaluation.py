"""Guarded operator service for persisted NFL market evaluation evidence.

The default path is a read-only preview. This module accepts only persisted
prediction and odds-run identifiers and has no provider or HTTP dependency.
"""

from __future__ import annotations

from dataclasses import dataclass

from sportsmodel.database.connection import get_connection
from sportsmodel.nfl.market_evaluation import (
    ConnectionFactory,
    OfficialMarketEvaluationExecutionResult,
    OfficialMarketEvaluationPreview,
    evaluate_official_nfl_moneyline_market,
    preview_official_nfl_moneyline_market,
)


class ManualMarketEvaluationGuardError(ValueError):
    """The operator did not supply the exact pair of live-write guards."""


@dataclass(frozen=True)
class ManualMarketEvaluationResult:
    preview: OfficialMarketEvaluationPreview
    execution: OfficialMarketEvaluationExecutionResult | None

    @property
    def dry_run(self) -> bool:
        return self.execution is None


def execute_manual_market_evaluation(
    *,
    prediction_id: int,
    odds_ingestion_run_id: int,
    live: bool = False,
    confirm_create_evaluation: bool = False,
    connection_factory: ConnectionFactory = get_connection,
) -> ManualMarketEvaluationResult:
    """Preview by default; write only with both explicit operator guards."""

    if live != confirm_create_evaluation:
        raise ManualMarketEvaluationGuardError(
            "A live evaluation requires both --live and "
            "--confirm-create-evaluation; neither flag alone is accepted."
        )
    preview = preview_official_nfl_moneyline_market(
        prediction_id=prediction_id,
        odds_ingestion_run_id=odds_ingestion_run_id,
        connection_factory=connection_factory,
    )
    if not live:
        return ManualMarketEvaluationResult(
            preview=preview,
            execution=None,
        )
    execution = evaluate_official_nfl_moneyline_market(
        prediction_id=prediction_id,
        odds_ingestion_run_id=odds_ingestion_run_id,
        connection_factory=connection_factory,
    )
    return ManualMarketEvaluationResult(
        preview=preview,
        execution=execution,
    )
