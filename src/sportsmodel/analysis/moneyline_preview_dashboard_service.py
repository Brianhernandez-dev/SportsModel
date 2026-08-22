from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
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
from sportsmodel.ingest.odds_api_parser import (
    ODDS_API_MLB_SPORT_KEY,
)
from sportsmodel.models.consensus_market import (
    ConsensusMarket,
)
from sportsmodel.models.moneyline_market_evaluation import (
    MoneylineMarketEvaluationPolicy,
    MoneylinePredictionMarketContext,
)
from sportsmodel.models.moneyline_preview_dashboard import (
    MoneylinePreviewDashboard,
    MoneylinePreviewGame,
    MoneylinePreviewUnavailableGame,
)
from sportsmodel.models.snapshot import (
    MarketSnapshot,
)


ConnectionFactory = Callable[[], Any]


@dataclass(frozen=True)
class _PreviewRunMetadata:
    prediction_run_id: int

    model_version: str


@dataclass(frozen=True)
class _StoredPreviewPrediction:
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

    missing_raw_value_count: int


def build_moneyline_preview_dashboard(
    *,
    target_date: date,
    policy: MoneylineMarketEvaluationPolicy = (
        DEFAULT_MONEYLINE_MARKET_EVALUATION_POLICY
    ),
    connection_factory: ConnectionFactory = get_connection,
) -> MoneylinePreviewDashboard:
    """
    Build a read-only opening-market value card for a preview run.

    Preview evaluation intentionally does not apply the official
    prediction-before-odds timing rule. The opening snapshot is expected
    to precede the preview prediction.

    Nothing from this service is persisted as an official market
    evaluation or paper candidate.
    """

    connection = connection_factory()

    try:
        with connection.cursor() as cursor:
            preview_run = _load_latest_preview_run(
                cursor,
                target_date=target_date,
            )

            selected_market_run = (
                _load_latest_opening_run(
                    cursor,
                    target_date=target_date,
                    include_role=True,
                )
            )

            opening_run_id = _load_latest_opening_run(
                cursor,
                target_date=target_date,
                include_late_night=False,
            )

            if isinstance(selected_market_run, tuple):
                (
                    selected_market_run_id,
                    selected_market_role,
                ) = selected_market_run
            else:
                # Existing unit-test mocks return only
                # the ingestion-run ID.
                selected_market_run_id = (
                    selected_market_run
                )

                selected_market_role = (
                    "late_night"
                    if (
                        selected_market_run_id
                        != opening_run_id
                    )
                    else "opening"
                )

            predictions = _load_preview_predictions(
                cursor,
                prediction_run_id=(
                    preview_run.prediction_run_id
                ),
            )

            (
                snapshots,
                sportsbook_names,
            ) = _load_opening_snapshots(
                cursor,
                prediction_run_id=(
                    preview_run.prediction_run_id
                ),
                odds_ingestion_run_id=(
                    selected_market_run_id
                ),
            )

            if (
                opening_run_id
                != selected_market_run_id
            ):
                (
                    opening_snapshots,
                    _,
                ) = _load_opening_snapshots(
                    cursor,
                    prediction_run_id=(
                        preview_run.prediction_run_id
                    ),
                    odds_ingestion_run_id=(
                        opening_run_id
                    ),
                )
            else:
                opening_snapshots = snapshots

        if not predictions:
            raise LookupError(
                "The preview prediction run contains no predictions."
            )

        if not snapshots:
            raise LookupError(
                "The selected preview market run contains no "
                "matching Moneyline snapshots."
            )

        complete_markets = build_complete_markets(
            snapshots
        )

        no_vig_markets = calculate_no_vig_markets(
            complete_markets
        )

        consensus_markets = build_consensus_markets(
            no_vig_markets
        )

        consensus_by_game = _build_consensus_by_game(
            consensus_markets
        )

        if (
            opening_run_id
            != selected_market_run_id
            and opening_snapshots
        ):
            opening_complete_markets = (
                build_complete_markets(
                    opening_snapshots
                )
            )

            opening_no_vig_markets = (
                calculate_no_vig_markets(
                    opening_complete_markets
                )
            )

            opening_consensus_markets = (
                build_consensus_markets(
                    opening_no_vig_markets
                )
            )

            opening_consensus_by_game = (
                _build_consensus_by_game(
                    opening_consensus_markets
                )
            )
        else:
            opening_consensus_by_game = (
                consensus_by_game
            )

        games: list[MoneylinePreviewGame] = []

        unavailable_games: list[
            MoneylinePreviewUnavailableGame
        ] = []

        for prediction in predictions:
            consensus_market = consensus_by_game.get(
                prediction.game_id
            )

            if consensus_market is None:
                unavailable_games.append(
                    MoneylinePreviewUnavailableGame(
                        game_id=prediction.game_id,
                        game_start_time=(
                            prediction.game_start_time
                        ),
                        away_team_name=(
                            prediction.away_team_name
                        ),
                        home_team_name=(
                            prediction.home_team_name
                        ),
                        predicted_team_name=(
                            prediction.selection_name
                        ),
                        model_probability=(
                            prediction.model_probability
                        ),
                        starter_coverage=(
                            prediction.starter_coverage
                        ),
                        missing_raw_value_count=(
                            prediction
                            .missing_raw_value_count
                        ),
                        reason=(
                            "Current preview market "
                            "consensus unavailable"
                        ),
                    )
                )

                continue

            context = MoneylinePredictionMarketContext(
                game_id=prediction.game_id,
                selection_name=prediction.selection_name,
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

            game_snapshots = tuple(
                snapshot
                for snapshot in snapshots
                if (
                    snapshot.game_id
                    == prediction.game_id
                )
            )

            evaluation = evaluate_moneyline_model_value(
                prediction=context,
                consensus_market=consensus_market,
                snapshots=game_snapshots,
                policy=policy,
            )

            sportsbook_name = sportsbook_names.get(
                evaluation.sportsbook_id,
                (
                    "Sportsbook "
                    f"{evaluation.sportsbook_id}"
                ),
            )

            current_value_signal = (
                evaluation.model_expected_value
                >= policy.minimum_model_expected_value
                and evaluation.model_market_edge
                >= policy.minimum_model_market_edge
            )

            opening_evaluation = None

            if (
                opening_run_id
                == selected_market_run_id
            ):
                opening_evaluation = evaluation

            else:
                opening_consensus_market = (
                    opening_consensus_by_game.get(
                        prediction.game_id
                    )
                )

                if opening_consensus_market is not None:
                    opening_game_snapshots = tuple(
                        snapshot
                        for snapshot
                        in opening_snapshots
                        if (
                            snapshot.game_id
                            == prediction.game_id
                        )
                    )

                    opening_evaluation = (
                        evaluate_moneyline_model_value(
                            prediction=context,
                            consensus_market=(
                                opening_consensus_market
                            ),
                            snapshots=(
                                opening_game_snapshots
                            ),
                            policy=policy,
                        )
                    )

            opening_policy_pass = (
                opening_evaluation
                .qualifies_as_paper_candidate
                if opening_evaluation is not None
                else None
            )

            movement_status = (
                _classify_preview_movement(
                    market_snapshot_role=(
                        selected_market_role
                    ),
                    opening_policy_pass=(
                        opening_policy_pass
                    ),
                    current_policy_pass=(
                        evaluation
                        .qualifies_as_paper_candidate
                    ),
                    current_value_signal=(
                        current_value_signal
                    ),
                )
            )

            games.append(
                MoneylinePreviewGame(
                    game_id=prediction.game_id,
                    game_start_time=(
                        prediction.game_start_time
                    ),
                    away_team_name=(
                        prediction.away_team_name
                    ),
                    home_team_name=(
                        prediction.home_team_name
                    ),
                    predicted_team_name=(
                        prediction.selection_name
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
                    model_price_edge=(
                        evaluation.model_price_edge
                    ),
                    price=evaluation.price,
                    sportsbook_name=sportsbook_name,
                    model_expected_value=(
                        evaluation.model_expected_value
                    ),
                    sportsbook_count=(
                        evaluation.sportsbook_count
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
                    missing_raw_value_count=(
                        prediction
                        .missing_raw_value_count
                    ),
                    preview_value_signal=(
                        current_value_signal
                    ),
                    preview_policy_pass=(
                        evaluation
                        .qualifies_as_paper_candidate
                    ),
                    disqualification_reasons=(
                        evaluation
                        .disqualification_reasons
                    ),
                    opening_price=(
                        opening_evaluation.price
                        if opening_evaluation
                        is not None
                        else None
                    ),
                    opening_model_expected_value=(
                        opening_evaluation
                        .model_expected_value
                        if opening_evaluation
                        is not None
                        else None
                    ),
                    opening_model_market_edge=(
                        opening_evaluation
                        .model_market_edge
                        if opening_evaluation
                        is not None
                        else None
                    ),
                    opening_policy_pass=(
                        opening_policy_pass
                    ),
                    movement_status=(
                        movement_status
                    ),
                )
            )

        games.sort(
            key=lambda game: (
                game.model_expected_value
            ),
            reverse=True,
        )

        return MoneylinePreviewDashboard(
            target_date=target_date,
            prediction_run_id=(
                preview_run.prediction_run_id
            ),
            odds_ingestion_run_id=(
                selected_market_run_id
            ),
            market_snapshot_time=max(
                snapshot.snapshot_time
                for snapshot in snapshots
            ),
            model_version=preview_run.model_version,
            policy_version=policy.policy_version,
            predictions_loaded=len(predictions),
            games=tuple(games),
            unavailable_games=tuple(
                unavailable_games
            ),
            market_snapshot_role=(
                selected_market_role
            ),
            opening_odds_ingestion_run_id=(
                opening_run_id
            ),
            opening_market_snapshot_time=(
                max(
                    snapshot.snapshot_time
                    for snapshot
                    in opening_snapshots
                )
                if opening_snapshots
                else None
            ),
        )

    finally:
        connection.close()



def _classify_preview_movement(
    *,
    market_snapshot_role: str,
    opening_policy_pass: bool | None,
    current_policy_pass: bool,
    current_value_signal: bool,
) -> str:
    """
    Classify opening-to-current preview value movement.
    """

    if market_snapshot_role == "opening":
        return "OPENING ONLY"

    if market_snapshot_role not in {
        "evening",
        "late_night",
    }:
        return "NO VALUE"

    if opening_policy_pass is None:
        if current_policy_pass:
            if market_snapshot_role == "evening":
                return "EVENING VALUE"

            return "LATE-NIGHT VALUE"

        if current_value_signal:
            return "POLICY BLOCKED"

        return "NO VALUE"

    if (
        not opening_policy_pass
        and current_policy_pass
    ):
        return "NEW VALUE"

    if (
        opening_policy_pass
        and current_policy_pass
    ):
        return "STILL VALUE"

    if (
        opening_policy_pass
        and not current_policy_pass
    ):
        return "VALUE LOST"

    if current_value_signal:
        return "POLICY BLOCKED"

    return "NO VALUE"


def _load_latest_preview_run(
    cursor: Any,
    *,
    target_date: date,
) -> _PreviewRunMetadata:
    cursor.execute(
        """
        SELECT
            moneyline_prediction_run_id,
            model_version
        FROM moneyline_prediction_runs
        WHERE
            target_date = %s
            AND status = 'completed'
            AND run_type = 'preview'
        ORDER BY
            moneyline_prediction_run_id DESC
        LIMIT 1;
        """,
        (target_date,),
    )

    row = cursor.fetchone()

    if row is None:
        raise LookupError(
            "No completed Moneyline preview run exists "
            f"for {target_date}."
        )

    return _PreviewRunMetadata(
        prediction_run_id=row[0],
        model_version=row[1],
    )


def _load_latest_opening_run(
    cursor: Any,
    *,
    target_date: date,
    include_late_night: bool = True,
    include_role: bool = False,
) -> int | tuple[int, str]:
    roles = (
        (
            "opening",
            "evening",
            "late_night",
        )
        if include_late_night
        else ("opening",)
    )

    cursor.execute(
        """
        SELECT
            odds_ingestion_run_id,
            snapshot_role
        FROM odds_ingestion_runs
        WHERE
            target_date = %s
            AND status = 'completed'
            AND snapshot_role = ANY(%s)
            AND sport = %s
        ORDER BY
            CASE snapshot_role
                WHEN 'late_night' THEN 1
                WHEN 'evening' THEN 2
                WHEN 'opening' THEN 3
                ELSE 99
            END,
            odds_ingestion_run_id DESC
        LIMIT 1;
        """,
        (
            target_date,
            list(roles),
            ODDS_API_MLB_SPORT_KEY,
        ),
    )

    row = cursor.fetchone()

    if row is None:
        if include_late_night:
            message = (
                "No completed opening, evening, or "
                "late-night odds snapshot exists "
                f"for {target_date}."
            )
        else:
            message = (
                "No completed opening odds snapshot "
                f"exists for {target_date}."
            )

        raise LookupError(message)

    if include_role:
        return (
            row[0],
            row[1],
        )

    return row[0]


def _load_preview_predictions(
    cursor: Any,
    *,
    prediction_run_id: int,
) -> tuple[_StoredPreviewPrediction, ...]:
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
            prediction.away_starter_features_available,
            prediction.missing_raw_value_count
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

    return tuple(
        _StoredPreviewPrediction(
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
            missing_raw_value_count=row[11],
        )
        for row in cursor.fetchall()
    )


def _load_opening_snapshots(
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
                WHERE moneyline_prediction_run_id = %s
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

        sportsbook_names[sportsbook_id] = row[8]

    return (
        tuple(snapshots),
        sportsbook_names,
    )


def _build_consensus_by_game(
    consensus_markets: tuple[
        ConsensusMarket,
        ...,
    ],
) -> dict[int, ConsensusMarket]:
    by_game: dict[int, ConsensusMarket] = {}

    for market in consensus_markets:
        if (
            market.market_type != "h2h"
            or market.line_value is not None
        ):
            continue

        if market.game_id in by_game:
            raise ValueError(
                "Multiple opening Moneyline consensus markets "
                f"exist for game {market.game_id}."
            )

        by_game[market.game_id] = market

    return by_game
