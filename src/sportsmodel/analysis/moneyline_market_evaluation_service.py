from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from sportsmodel.analysis.consensus import (
    build_consensus_markets,
)
from sportsmodel.analysis.market_builder import (
    build_complete_markets,
)
from sportsmodel.analysis.moneyline_model_value import (
    DEFAULT_MONEYLINE_MARKET_EVALUATION_POLICY,
    evaluate_moneyline_model_value,
)
from sportsmodel.analysis.no_vig import (
    calculate_no_vig_markets,
)
from sportsmodel.database.connection import (
    get_connection,
)
from sportsmodel.database.moneyline_market_evaluation_repository import (
    upsert_moneyline_market_evaluation,
)
from sportsmodel.models.consensus_market import (
    ConsensusMarket,
)
from sportsmodel.models.moneyline_market_evaluation import (
    MoneylineMarketEvaluationPolicy,
    MoneylinePredictionMarketContext,
)
from sportsmodel.models.snapshot import (
    MarketSnapshot,
)


ConnectionFactory = Callable[[], Any]


@dataclass(frozen=True)
class StoredMoneylinePrediction:
    """
    Stored prediction data needed for market evaluation.
    """

    moneyline_game_prediction_id: int

    game_id: int

    prediction_time: datetime

    game_start_time: datetime

    away_team_name: str

    home_team_name: str

    selection_name: str

    model_probability: Decimal

    starter_coverage: str

    home_starter_features_available: bool

    away_starter_features_available: bool


@dataclass(frozen=True)
class MoneylineMarketEvaluationResult:
    """
    Display details for one persisted evaluation.
    """

    moneyline_prediction_market_evaluation_id: int

    moneyline_game_prediction_id: int

    game_id: int

    away_team_name: str

    home_team_name: str

    selection_name: str

    sportsbook_name: str

    price: int

    snapshot_time: datetime

    model_probability: Decimal

    market_no_vig_probability: Decimal

    model_market_edge: Decimal

    implied_probability: Decimal

    model_price_edge: Decimal

    model_expected_value: Decimal

    sportsbook_count: int

    qualifies_as_paper_candidate: bool

    disqualification_reasons: tuple[str, ...]


@dataclass(frozen=True)
class MoneylineMarketEvaluationRunResult:
    """
    Summary of one persisted prediction/market evaluation.
    """

    prediction_run_id: int

    odds_ingestion_run_id: int

    policy_version: str

    predictions_loaded: int

    evaluations_saved: int

    paper_candidates: int

    evaluations: tuple[
        MoneylineMarketEvaluationResult,
        ...,
    ]

    skipped_missing_market_game_ids: tuple[int, ...] = ()


def evaluate_moneyline_prediction_run(
    *,
    prediction_run_id: int,
    odds_ingestion_run_id: int,
    policy: MoneylineMarketEvaluationPolicy = (
        DEFAULT_MONEYLINE_MARKET_EVALUATION_POLICY
    ),
    connection_factory: ConnectionFactory = (
        get_connection
    ),
    require_complete_market_coverage: bool = True,
) -> MoneylineMarketEvaluationRunResult:
    """
    Evaluate and persist one prediction run against one odds run.

    Every evaluation is written in one transaction. Re-running the same
    prediction run, odds run, and policy version updates the existing
    records rather than creating duplicates.
    """

    _validate_positive_identifier(
        value=prediction_run_id,
        field_name="Prediction run ID",
    )

    _validate_positive_identifier(
        value=odds_ingestion_run_id,
        field_name="Odds ingestion run ID",
    )

    connection = connection_factory()

    try:
        with connection.cursor() as cursor:
            _validate_completed_runs(
                cursor,
                prediction_run_id=(
                    prediction_run_id
                ),
                odds_ingestion_run_id=(
                    odds_ingestion_run_id
                ),
            )

            predictions = (
                _load_prediction_records(
                    cursor,
                    prediction_run_id=(
                        prediction_run_id
                    ),
                )
            )

            (
                snapshots,
                sportsbook_names,
            ) = _load_snapshot_records(
                cursor,
                prediction_run_id=(
                    prediction_run_id
                ),
                odds_ingestion_run_id=(
                    odds_ingestion_run_id
                ),
            )

        if not predictions:
            raise LookupError(
                "The prediction run contains no predictions."
            )

        if not snapshots and require_complete_market_coverage:
            raise LookupError(
                "The odds run contains no matching "
                "Moneyline snapshots."
            )

        complete_markets = build_complete_markets(
            snapshots
        )

        no_vig_markets = (
            calculate_no_vig_markets(
                complete_markets
            )
        )

        consensus_markets = (
            build_consensus_markets(
                no_vig_markets
            )
        )

        consensus_by_game = (
            _build_consensus_by_game(
                consensus_markets
            )
        )

        evaluated_rows: list[
            tuple[
                StoredMoneylinePrediction,
                Any,
            ]
        ] = []
        skipped_missing_market_game_ids: list[int] = []

        for prediction in predictions:
            consensus_market = (
                consensus_by_game.get(
                    prediction.game_id
                )
            )

            if consensus_market is None:
                if not require_complete_market_coverage:
                    skipped_missing_market_game_ids.append(
                        prediction.game_id
                    )
                    continue

                raise LookupError(
                    "No complete Moneyline consensus "
                    "market exists for canonical game "
                    f"{prediction.game_id}."
                )

            _validate_evaluation_timing(
                prediction=prediction,
                snapshot_time=(
                    consensus_market.snapshot_time
                ),
            )

            context = (
                MoneylinePredictionMarketContext(
                    game_id=prediction.game_id,
                    selection_name=(
                        prediction.selection_name
                    ),
                    model_probability=(
                        prediction.model_probability
                    ),
                    starter_coverage=(
                        prediction.starter_coverage
                    ),
                    home_starter_features_available=(
                        prediction
                        .home_starter_features_available
                    ),
                    away_starter_features_available=(
                        prediction
                        .away_starter_features_available
                    ),
                )
            )

            game_snapshots = [
                snapshot
                for snapshot in snapshots
                if (
                    snapshot.game_id
                    == prediction.game_id
                )
            ]

            evaluation = (
                evaluate_moneyline_model_value(
                    prediction=context,
                    consensus_market=(
                        consensus_market
                    ),
                    snapshots=game_snapshots,
                    policy=policy,
                )
            )

            evaluated_rows.append(
                (
                    prediction,
                    evaluation,
                )
            )

        results: list[
            MoneylineMarketEvaluationResult
        ] = []

        with connection.cursor() as cursor:
            for (
                prediction,
                evaluation,
            ) in evaluated_rows:
                evaluation_id = (
                    upsert_moneyline_market_evaluation(
                        cursor,
                        moneyline_game_prediction_id=(
                            prediction
                            .moneyline_game_prediction_id
                        ),
                        odds_ingestion_run_id=(
                            odds_ingestion_run_id
                        ),
                        evaluation=evaluation,
                    )
                )

                sportsbook_name = (
                    sportsbook_names.get(
                        evaluation.sportsbook_id,
                        (
                            "Sportsbook "
                            f"{evaluation.sportsbook_id}"
                        ),
                    )
                )

                results.append(
                    MoneylineMarketEvaluationResult(
                        moneyline_prediction_market_evaluation_id=(
                            evaluation_id
                        ),
                        moneyline_game_prediction_id=(
                            prediction
                            .moneyline_game_prediction_id
                        ),
                        game_id=(
                            prediction.game_id
                        ),
                        away_team_name=(
                            prediction.away_team_name
                        ),
                        home_team_name=(
                            prediction.home_team_name
                        ),
                        selection_name=(
                            evaluation.selection_name
                        ),
                        sportsbook_name=(
                            sportsbook_name
                        ),
                        price=evaluation.price,
                        snapshot_time=(
                            evaluation.snapshot_time
                        ),
                        model_probability=(
                            evaluation.model_probability
                        ),
                        market_no_vig_probability=(
                            evaluation
                            .market_no_vig_probability
                        ),
                        model_market_edge=(
                            evaluation.model_market_edge
                        ),
                        implied_probability=(
                            evaluation.implied_probability
                        ),
                        model_price_edge=(
                            evaluation.model_price_edge
                        ),
                        model_expected_value=(
                            evaluation.model_expected_value
                        ),
                        sportsbook_count=(
                            evaluation.sportsbook_count
                        ),
                        qualifies_as_paper_candidate=(
                            evaluation
                            .qualifies_as_paper_candidate
                        ),
                        disqualification_reasons=(
                            evaluation
                            .disqualification_reasons
                        ),
                    )
                )

        connection.commit()

        paper_candidates = sum(
            result.qualifies_as_paper_candidate
            for result in results
        )

        results.sort(
            key=lambda result: (
                result.model_expected_value
            ),
            reverse=True,
        )

        return MoneylineMarketEvaluationRunResult(
            prediction_run_id=prediction_run_id,
            odds_ingestion_run_id=(
                odds_ingestion_run_id
            ),
            policy_version=(
                policy.policy_version
            ),
            predictions_loaded=len(
                predictions
            ),
            evaluations_saved=len(
                results
            ),
            paper_candidates=(
                paper_candidates
            ),
            evaluations=tuple(results),
            skipped_missing_market_game_ids=tuple(
                skipped_missing_market_game_ids
            ),
        )

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()


def _validate_completed_runs(
    cursor: Any,
    *,
    prediction_run_id: int,
    odds_ingestion_run_id: int,
) -> None:
    cursor.execute(
        """
        SELECT status
        FROM moneyline_prediction_runs
        WHERE moneyline_prediction_run_id = %s;
        """,
        (prediction_run_id,),
    )

    prediction_run = cursor.fetchone()

    if prediction_run is None:
        raise LookupError(
            "Moneyline prediction run was not found."
        )

    if prediction_run[0] != "completed":
        raise ValueError(
            "Moneyline prediction run must be completed."
        )

    cursor.execute(
        """
        SELECT status
        FROM odds_ingestion_runs
        WHERE odds_ingestion_run_id = %s;
        """,
        (odds_ingestion_run_id,),
    )

    odds_run = cursor.fetchone()

    if odds_run is None:
        raise LookupError(
            "Odds ingestion run was not found."
        )

    if odds_run[0] != "completed":
        raise ValueError(
            "Odds ingestion run must be completed."
        )


def _load_prediction_records(
    cursor: Any,
    *,
    prediction_run_id: int,
) -> tuple[StoredMoneylinePrediction, ...]:
    cursor.execute(
        """
        SELECT
            prediction.moneyline_game_prediction_id,
            prediction.game_id,
            prediction.prediction_time,
            prediction.game_start_time,
            away_team.team_name,
            home_team.team_name,
            predicted_team.team_name,
            prediction.predicted_probability,
            prediction.starter_coverage,
            prediction.home_starter_features_available,
            prediction.away_starter_features_available
        FROM moneyline_game_predictions AS prediction
        JOIN teams AS away_team
          ON away_team.team_id =
             prediction.away_team_id
        JOIN teams AS home_team
          ON home_team.team_id =
             prediction.home_team_id
        JOIN teams AS predicted_team
          ON predicted_team.team_id =
             prediction.predicted_team_id
        WHERE
            prediction.moneyline_prediction_run_id = %s
        ORDER BY
            prediction.game_start_time,
            prediction.game_id;
        """,
        (prediction_run_id,),
    )

    rows = cursor.fetchall()

    return tuple(
        StoredMoneylinePrediction(
            moneyline_game_prediction_id=row[0],
            game_id=row[1],
            prediction_time=row[2],
            game_start_time=row[3],
            away_team_name=row[4],
            home_team_name=row[5],
            selection_name=row[6],
            model_probability=row[7],
            starter_coverage=row[8],
            home_starter_features_available=row[9],
            away_starter_features_available=row[10],
        )
        for row in rows
    )


def _load_snapshot_records(
    cursor: Any,
    *,
    prediction_run_id: int,
    odds_ingestion_run_id: int,
) -> tuple[
    tuple[MarketSnapshot, ...],
    dict[int, str],
]:
    cursor.execute(
        """
        SELECT
            snapshot.odds_market_snapshot_id,
            snapshot.game_id,
            snapshot.sportsbook_id,
            snapshot.market_type,
            snapshot.selection_name,
            snapshot.line_value,
            snapshot.price,
            snapshot.snapshot_time,
            sportsbook.name
        FROM odds_market_snapshots AS snapshot
        JOIN sportsbooks AS sportsbook
          ON sportsbook.sportsbook_id =
             snapshot.sportsbook_id
        WHERE
            snapshot.odds_ingestion_run_id = %s
            AND snapshot.market_type = 'h2h'
            AND snapshot.game_id IN (
                SELECT game_id
                FROM moneyline_game_predictions
                WHERE
                    moneyline_prediction_run_id = %s
            )
        ORDER BY
            snapshot.game_id,
            snapshot.sportsbook_id,
            snapshot.odds_market_snapshot_id;
        """,
        (
            odds_ingestion_run_id,
            prediction_run_id,
        ),
    )

    rows = cursor.fetchall()

    snapshots: list[MarketSnapshot] = []
    sportsbook_names: dict[int, str] = {}

    for row in rows:
        sportsbook_id = row[2]

        snapshots.append(
            MarketSnapshot(
                odds_market_snapshot_id=row[0],
                game_id=row[1],
                sportsbook_id=sportsbook_id,
                market_type=row[3],
                selection_name=row[4],
                line_value=row[5],
                price=row[6],
                snapshot_time=row[7],
            )
        )

        sportsbook_names[
            sportsbook_id
        ] = row[8]

    return (
        tuple(snapshots),
        sportsbook_names,
    )


def _build_consensus_by_game(
    markets: list[ConsensusMarket],
) -> dict[int, ConsensusMarket]:
    consensus_by_game: dict[
        int,
        ConsensusMarket,
    ] = {}

    for market in markets:
        if market.market_type != "h2h":
            continue

        if market.game_id in consensus_by_game:
            raise RuntimeError(
                "Multiple Moneyline consensus snapshots "
                "were found for canonical game "
                f"{market.game_id}."
            )

        consensus_by_game[
            market.game_id
        ] = market

    return consensus_by_game


def _validate_evaluation_timing(
    *,
    prediction: StoredMoneylinePrediction,
    snapshot_time: datetime,
) -> None:
    if snapshot_time < prediction.prediction_time:
        raise ValueError(
            "Odds snapshot cannot precede the "
            "stored prediction timestamp."
        )

    if snapshot_time >= prediction.game_start_time:
        raise ValueError(
            "Odds snapshot must be captured before "
            "the game starts."
        )


def _validate_positive_identifier(
    *,
    value: int,
    field_name: str,
) -> None:
    if value <= 0:
        raise ValueError(
            f"{field_name} must be greater than zero."
        )
