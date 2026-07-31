from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sportsmodel.database.connection import (
    get_connection,
)
from sportsmodel.database.moneyline_paper_settlement_repository import (
    upsert_moneyline_paper_settlement,
)
from sportsmodel.models.game_result import (
    GameResult,
)
from sportsmodel.models.moneyline_paper_settlement import (
    MoneylinePaperCandidate,
    MoneylinePaperSettlement,
)
from sportsmodel.models.settled_bet import (
    BetOutcome,
)
from sportsmodel.settlement.moneyline_paper import (
    settle_moneyline_paper_candidates,
)


ConnectionFactory = Callable[[], Any]


@dataclass(frozen=True)
class MoneylinePaperSettlementRecord:
    """
    Display record for one settled paper candidate.
    """

    moneyline_paper_candidate_settlement_id: int

    moneyline_prediction_market_evaluation_id: int

    game_id: int

    away_team_name: str

    home_team_name: str

    away_score: int

    home_score: int

    selection_name: str

    price: int

    model_probability: Decimal

    model_expected_value: Decimal

    outcome: BetOutcome

    profit_units: Decimal


@dataclass(frozen=True)
class MoneylinePaperPerformanceReport:
    """
    Flat one-unit performance for settled paper candidates.
    """

    candidates_loaded: int

    settlements_saved: int

    pending_candidates: int

    wins: int

    losses: int

    pushes: int

    settled_decisions: int

    win_rate: Decimal

    total_staked_units: Decimal

    profit_units: Decimal

    roi: Decimal

    average_model_expected_value: Decimal

    maximum_drawdown_units: Decimal


@dataclass(frozen=True)
class MoneylinePaperSettlementRunResult:
    """
    Result of settling one stored paper-candidate slate.
    """

    prediction_run_id: int

    odds_ingestion_run_id: int

    policy_version: str

    report: MoneylinePaperPerformanceReport

    settlements: tuple[
        MoneylinePaperSettlementRecord,
        ...,
    ]


def settle_moneyline_paper_candidate_run(
    *,
    prediction_run_id: int,
    odds_ingestion_run_id: int,
    policy_version: str = "1.0.0",
    connection_factory: ConnectionFactory = (
        get_connection
    ),
) -> MoneylinePaperSettlementRunResult:
    """
    Settle one qualified Moneyline paper-candidate slate.

    Candidates without stored final scores remain pending. Completed
    candidates are upserted in one transaction, making the operation
    safe to rerun after results ingestion or a score correction.
    """

    _validate_positive_identifier(
        value=prediction_run_id,
        field_name="Prediction run ID",
    )

    _validate_positive_identifier(
        value=odds_ingestion_run_id,
        field_name="Odds ingestion run ID",
    )

    normalized_policy_version = (
        policy_version.strip()
    )

    if not normalized_policy_version:
        raise ValueError(
            "Policy version cannot be blank."
        )

    connection = connection_factory()

    try:
        with connection.cursor() as cursor:
            candidates = _load_paper_candidates(
                cursor,
                prediction_run_id=(
                    prediction_run_id
                ),
                odds_ingestion_run_id=(
                    odds_ingestion_run_id
                ),
                policy_version=(
                    normalized_policy_version
                ),
            )

            results = _load_completed_results(
                cursor,
                game_ids={
                    candidate.game_id
                    for candidate in candidates
                },
            )

        settlements = (
            settle_moneyline_paper_candidates(
                candidates,
                results,
            )
        )

        settlement_records: list[
            MoneylinePaperSettlementRecord
        ] = []

        with connection.cursor() as cursor:
            for settlement in settlements:
                settlement_id = (
                    upsert_moneyline_paper_settlement(
                        cursor,
                        settlement,
                    )
                )

                settlement_records.append(
                    MoneylinePaperSettlementRecord(
                        moneyline_paper_candidate_settlement_id=(
                            settlement_id
                        ),
                        moneyline_prediction_market_evaluation_id=(
                            settlement
                            .moneyline_prediction_market_evaluation_id
                        ),
                        game_id=(
                            settlement.game_id
                        ),
                        away_team_name=(
                            settlement.away_team_name
                        ),
                        home_team_name=(
                            settlement.home_team_name
                        ),
                        away_score=(
                            settlement.away_score
                        ),
                        home_score=(
                            settlement.home_score
                        ),
                        selection_name=(
                            settlement.selection_name
                        ),
                        price=settlement.price,
                        model_probability=(
                            settlement.model_probability
                        ),
                        model_expected_value=(
                            settlement.model_expected_value
                        ),
                        outcome=(
                            settlement.outcome
                        ),
                        profit_units=(
                            settlement.profit_units
                        ),
                    )
                )

        connection.commit()

        report = _build_performance_report(
            candidates_loaded=len(candidates),
            settlements=settlements,
        )

        return MoneylinePaperSettlementRunResult(
            prediction_run_id=(
                prediction_run_id
            ),
            odds_ingestion_run_id=(
                odds_ingestion_run_id
            ),
            policy_version=(
                normalized_policy_version
            ),
            report=report,
            settlements=tuple(
                settlement_records
            ),
        )

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()


def _load_paper_candidates(
    cursor: Any,
    *,
    prediction_run_id: int,
    odds_ingestion_run_id: int,
    policy_version: str,
) -> tuple[MoneylinePaperCandidate, ...]:
    cursor.execute(
        """
        SELECT
            evaluation
                .moneyline_prediction_market_evaluation_id,
            prediction.game_id,
            evaluation.selection_name,
            evaluation.snapshot_time,
            evaluation.price,
            evaluation.model_probability,
            evaluation.model_expected_value
        FROM moneyline_prediction_market_evaluations
            AS evaluation
        JOIN moneyline_game_predictions AS prediction
          ON prediction.moneyline_game_prediction_id =
             evaluation.moneyline_game_prediction_id
        WHERE
            prediction.moneyline_prediction_run_id = %s
            AND evaluation.odds_ingestion_run_id = %s
            AND evaluation.policy_version = %s
            AND evaluation.qualifies_as_paper_candidate
                IS TRUE
        ORDER BY
            evaluation.snapshot_time,
            prediction.game_id,
            evaluation
                .moneyline_prediction_market_evaluation_id;
        """,
        (
            prediction_run_id,
            odds_ingestion_run_id,
            policy_version,
        ),
    )

    rows = cursor.fetchall()

    return tuple(
        MoneylinePaperCandidate(
            moneyline_prediction_market_evaluation_id=(
                row[0]
            ),
            game_id=row[1],
            selection_name=row[2],
            snapshot_time=row[3],
            price=row[4],
            model_probability=row[5],
            model_expected_value=row[6],
        )
        for row in rows
    )


def _load_completed_results(
    cursor: Any,
    *,
    game_ids: set[int],
) -> tuple[GameResult, ...]:
    if not game_ids:
        return ()

    cursor.execute(
        """
        SELECT
            game.game_id,
            historical.home_team,
            historical.away_team,
            historical.home_score,
            historical.away_score
        FROM games AS game
        JOIN historical_games AS historical
          ON historical.game_id =
             game.game_id
        WHERE
            game.game_id = ANY(%s)
            AND historical.home_score
                IS NOT NULL
            AND historical.away_score
                IS NOT NULL
        ORDER BY
            game.game_date,
            game.game_id;
        """,
        (
            sorted(game_ids),
        ),
    )

    rows = cursor.fetchall()

    return tuple(
        GameResult(
            game_id=row[0],
            home_team=row[1],
            away_team=row[2],
            home_score=row[3],
            away_score=row[4],
        )
        for row in rows
    )


def _build_performance_report(
    *,
    candidates_loaded: int,
    settlements: list[
        MoneylinePaperSettlement
    ],
) -> MoneylinePaperPerformanceReport:
    ordered_settlements = sorted(
        settlements,
        key=lambda settlement: (
            settlement.snapshot_time,
            settlement.game_id,
            settlement
            .moneyline_prediction_market_evaluation_id,
        ),
    )

    settlements_saved = len(
        ordered_settlements
    )

    wins = sum(
        settlement.outcome is BetOutcome.WIN
        for settlement in ordered_settlements
    )

    losses = sum(
        settlement.outcome is BetOutcome.LOSS
        for settlement in ordered_settlements
    )

    pushes = sum(
        settlement.outcome is BetOutcome.PUSH
        for settlement in ordered_settlements
    )

    settled_decisions = wins + losses

    total_staked_units = Decimal(
        settlements_saved
    )

    profit_units = sum(
        (
            settlement.profit_units
            for settlement
            in ordered_settlements
        ),
        start=Decimal("0"),
    )

    if settled_decisions:
        win_rate = (
            Decimal(wins)
            / Decimal(settled_decisions)
        )
    else:
        win_rate = Decimal("0")

    if total_staked_units:
        roi = (
            profit_units
            / total_staked_units
        )
    else:
        roi = Decimal("0")

    if settlements_saved:
        average_model_expected_value = (
            sum(
                (
                    settlement
                    .model_expected_value
                    for settlement
                    in ordered_settlements
                ),
                start=Decimal("0"),
            )
            / Decimal(settlements_saved)
        )
    else:
        average_model_expected_value = (
            Decimal("0")
        )

    maximum_drawdown_units = (
        _calculate_maximum_drawdown(
            ordered_settlements
        )
    )

    return MoneylinePaperPerformanceReport(
        candidates_loaded=(
            candidates_loaded
        ),
        settlements_saved=(
            settlements_saved
        ),
        pending_candidates=(
            candidates_loaded
            - settlements_saved
        ),
        wins=wins,
        losses=losses,
        pushes=pushes,
        settled_decisions=(
            settled_decisions
        ),
        win_rate=win_rate,
        total_staked_units=(
            total_staked_units
        ),
        profit_units=profit_units,
        roi=roi,
        average_model_expected_value=(
            average_model_expected_value
        ),
        maximum_drawdown_units=(
            maximum_drawdown_units
        ),
    )


def _calculate_maximum_drawdown(
    settlements: list[
        MoneylinePaperSettlement
    ],
) -> Decimal:
    cumulative_profit = Decimal("0")
    peak_profit = Decimal("0")
    maximum_drawdown = Decimal("0")

    for settlement in settlements:
        cumulative_profit += (
            settlement.profit_units
        )

        if cumulative_profit > peak_profit:
            peak_profit = cumulative_profit

        current_drawdown = (
            peak_profit
            - cumulative_profit
        )

        if current_drawdown > maximum_drawdown:
            maximum_drawdown = (
                current_drawdown
            )

    return maximum_drawdown


def _validate_positive_identifier(
    *,
    value: int,
    field_name: str,
) -> None:
    if value <= 0:
        raise ValueError(
            f"{field_name} must be greater than zero."
        )
