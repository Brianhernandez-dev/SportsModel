from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sportsmodel.database.connection import get_connection


ConnectionFactory = Callable[[], Any]

AWAITING_OFFICIAL = "Awaiting 8 AM Official Card"
SURVIVED_TO_OFFICIAL = "Survived to Official"
EARLY_ENTRY_ONLY = "Did not survive to Official"
OFFICIAL_ONLY = "Appeared at Official"


@dataclass(frozen=True)
class MoneylineCohortBet:
    cohort: str
    evaluation_id: int
    game_id: int
    game_start_time: datetime
    away_team_name: str
    home_team_name: str
    selection_name: str
    price: int
    sportsbook_name: str
    outcome: str | None
    profit_units: Decimal | None
    prediction_run_id: int
    odds_ingestion_run_id: int


@dataclass(frozen=True)
class MoneylineCohortPerformance:
    qualified_bets: int
    settled: int
    wins: int
    losses: int
    pushes: int
    pending: int
    profit_units: Decimal
    roi: Decimal


@dataclass(frozen=True)
class MoneylineCohortComparisonRow:
    game_id: int
    game_start_time: datetime
    matchup: str
    selection_name: str
    early_entry_price: int | None
    official_price: int | None
    price_movement: int | None
    status: str


@dataclass(frozen=True)
class MoneylineCohortComparison:
    target_date: date
    official_exists: bool
    early_entry: MoneylineCohortPerformance
    official: MoneylineCohortPerformance
    rows: tuple[MoneylineCohortComparisonRow, ...]


OFFICIAL_EXISTS_QUERY = """
    SELECT EXISTS (
        SELECT 1
        FROM moneyline_daily_workflow_runs AS workflow
        JOIN moneyline_prediction_runs AS prediction_run
          ON prediction_run.moneyline_prediction_run_id =
             workflow.moneyline_prediction_run_id
        WHERE
            workflow.target_date = %s
            AND workflow.moneyline_prediction_run_id IS NOT NULL
            AND workflow.odds_ingestion_run_id IS NOT NULL
            AND prediction_run.run_type = 'official'
    );
"""


COHORT_BETS_QUERY = """
    WITH early_entry AS (
        SELECT
            'Early Entry' AS cohort,
            evaluation.moneyline_prediction_market_evaluation_id
                AS evaluation_id,
            prediction.game_id,
            prediction.game_start_time,
            away_team.team_name,
            home_team.team_name,
            selected_team.team_name,
            evaluation.price,
            sportsbook.name,
            settlement.outcome,
            settlement.profit_units,
            prediction_run.moneyline_prediction_run_id,
            odds_run.odds_ingestion_run_id
        FROM moneyline_prediction_market_evaluations AS evaluation
        JOIN moneyline_game_predictions AS prediction
          ON prediction.moneyline_game_prediction_id =
             evaluation.moneyline_game_prediction_id
        JOIN moneyline_prediction_runs AS prediction_run
          ON prediction_run.moneyline_prediction_run_id =
             prediction.moneyline_prediction_run_id
        JOIN odds_ingestion_runs AS odds_run
          ON odds_run.odds_ingestion_run_id =
             evaluation.odds_ingestion_run_id
        JOIN teams AS away_team
          ON away_team.team_id = prediction.away_team_id
        JOIN teams AS home_team
          ON home_team.team_id = prediction.home_team_id
        JOIN teams AS selected_team
          ON selected_team.team_id = prediction.predicted_team_id
        JOIN sportsbooks AS sportsbook
          ON sportsbook.sportsbook_id = evaluation.sportsbook_id
        LEFT JOIN moneyline_paper_candidate_settlements AS settlement
          ON settlement.moneyline_prediction_market_evaluation_id =
             evaluation.moneyline_prediction_market_evaluation_id
        WHERE
            prediction_run.target_date = %s
            AND prediction_run.run_type = 'preview'
            AND odds_run.target_date = %s
            AND odds_run.snapshot_role = 'late_night'
            AND evaluation.qualifies_as_paper_candidate IS TRUE
    ),
    official AS (
        SELECT
            'Official' AS cohort,
            evaluation.moneyline_prediction_market_evaluation_id
                AS evaluation_id,
            prediction.game_id,
            prediction.game_start_time,
            away_team.team_name,
            home_team.team_name,
            selected_team.team_name,
            evaluation.price,
            sportsbook.name,
            settlement.outcome,
            settlement.profit_units,
            prediction_run.moneyline_prediction_run_id,
            evaluation.odds_ingestion_run_id
        FROM moneyline_daily_workflow_runs AS workflow
        JOIN moneyline_prediction_runs AS prediction_run
          ON prediction_run.moneyline_prediction_run_id =
             workflow.moneyline_prediction_run_id
        JOIN moneyline_game_predictions AS prediction
          ON prediction.moneyline_prediction_run_id =
             workflow.moneyline_prediction_run_id
        JOIN moneyline_prediction_market_evaluations AS evaluation
          ON evaluation.moneyline_game_prediction_id =
             prediction.moneyline_game_prediction_id
         AND evaluation.odds_ingestion_run_id =
             workflow.odds_ingestion_run_id
        JOIN teams AS away_team
          ON away_team.team_id = prediction.away_team_id
        JOIN teams AS home_team
          ON home_team.team_id = prediction.home_team_id
        JOIN teams AS selected_team
          ON selected_team.team_id = prediction.predicted_team_id
        JOIN sportsbooks AS sportsbook
          ON sportsbook.sportsbook_id = evaluation.sportsbook_id
        LEFT JOIN moneyline_paper_candidate_settlements AS settlement
          ON settlement.moneyline_prediction_market_evaluation_id =
             evaluation.moneyline_prediction_market_evaluation_id
        WHERE
            workflow.target_date = %s
            AND prediction_run.run_type = 'official'
            AND evaluation.qualifies_as_paper_candidate IS TRUE
    )
    SELECT * FROM early_entry
    UNION ALL
    SELECT * FROM official
    ORDER BY game_start_time, game_id, cohort, evaluation_id;
"""


def load_moneyline_cohort_comparison(
    *,
    target_date: date,
    connection_factory: ConnectionFactory = get_connection,
) -> MoneylineCohortComparison:
    """Load persisted Early Entry and Official qualified bets."""

    connection = connection_factory()
    try:
        with connection.cursor() as cursor:
            cursor.execute(OFFICIAL_EXISTS_QUERY, (target_date,))
            exists_row = cursor.fetchone()
            official_exists = bool(exists_row and exists_row[0])

            cursor.execute(
                COHORT_BETS_QUERY,
                (target_date, target_date, target_date),
            )
            bets = tuple(_build_bet(row) for row in cursor.fetchall())
    finally:
        connection.close()

    early_entry_bets = tuple(
        bet for bet in bets if bet.cohort == "Early Entry"
    )
    official_bets = tuple(
        bet for bet in bets if bet.cohort == "Official"
    )

    return MoneylineCohortComparison(
        target_date=target_date,
        official_exists=official_exists,
        early_entry=_build_performance(early_entry_bets),
        official=_build_performance(official_bets),
        rows=_build_comparison_rows(
            early_entry_bets=early_entry_bets,
            official_bets=official_bets,
            official_exists=official_exists,
        ),
    )


def _build_bet(row: tuple[Any, ...]) -> MoneylineCohortBet:
    return MoneylineCohortBet(
        cohort=row[0],
        evaluation_id=row[1],
        game_id=row[2],
        game_start_time=row[3],
        away_team_name=row[4],
        home_team_name=row[5],
        selection_name=row[6],
        price=row[7],
        sportsbook_name=row[8],
        outcome=row[9],
        profit_units=row[10],
        prediction_run_id=row[11],
        odds_ingestion_run_id=row[12],
    )


def _build_performance(
    bets: tuple[MoneylineCohortBet, ...],
) -> MoneylineCohortPerformance:
    settled_bets = tuple(
        bet
        for bet in bets
        if bet.outcome is not None and bet.profit_units is not None
    )
    settled = len(settled_bets)
    profit_units = sum(
        (bet.profit_units for bet in settled_bets),
        start=Decimal("0"),
    )
    return MoneylineCohortPerformance(
        qualified_bets=len(bets),
        settled=settled,
        wins=sum(bet.outcome == "win" for bet in settled_bets),
        losses=sum(bet.outcome == "loss" for bet in settled_bets),
        pushes=sum(bet.outcome == "push" for bet in settled_bets),
        pending=len(bets) - settled,
        profit_units=profit_units,
        roi=(profit_units / Decimal(settled) if settled else Decimal("0")),
    )


def _build_comparison_rows(
    *,
    early_entry_bets: tuple[MoneylineCohortBet, ...],
    official_bets: tuple[MoneylineCohortBet, ...],
    official_exists: bool,
) -> tuple[MoneylineCohortComparisonRow, ...]:
    official_by_selection = {
        (bet.game_id, bet.selection_name): bet
        for bet in official_bets
    }
    matched_keys: set[tuple[int, str]] = set()
    rows = []

    for early_bet in early_entry_bets:
        key = (early_bet.game_id, early_bet.selection_name)
        official_bet = official_by_selection.get(key)
        if official_bet is not None:
            matched_keys.add(key)
        rows.append(
            _comparison_row(
                early_bet=early_bet,
                official_bet=official_bet,
                official_exists=official_exists,
            )
        )

    for official_bet in official_bets:
        key = (official_bet.game_id, official_bet.selection_name)
        if key not in matched_keys:
            rows.append(
                _comparison_row(
                    early_bet=None,
                    official_bet=official_bet,
                    official_exists=True,
                )
            )

    return tuple(
        sorted(rows, key=lambda row: (row.game_start_time, row.game_id))
    )


def _comparison_row(
    *,
    early_bet: MoneylineCohortBet | None,
    official_bet: MoneylineCohortBet | None,
    official_exists: bool,
) -> MoneylineCohortComparisonRow:
    source = early_bet or official_bet
    if source is None:
        raise ValueError("At least one cohort bet is required.")

    if not official_exists:
        status = AWAITING_OFFICIAL
    elif early_bet is not None and official_bet is not None:
        status = SURVIVED_TO_OFFICIAL
    elif early_bet is not None:
        status = EARLY_ENTRY_ONLY
    else:
        status = OFFICIAL_ONLY

    return MoneylineCohortComparisonRow(
        game_id=source.game_id,
        game_start_time=source.game_start_time,
        matchup=(
            f"{source.away_team_name} at {source.home_team_name}"
        ),
        selection_name=source.selection_name,
        early_entry_price=(early_bet.price if early_bet else None),
        official_price=(official_bet.price if official_bet else None),
        price_movement=(
            official_bet.price - early_bet.price
            if early_bet is not None and official_bet is not None
            else None
        ),
        status=status,
    )
