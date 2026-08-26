from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_EVEN, localcontext
import json
from pathlib import Path
from typing import Any, Literal
from uuid import UUID, uuid4

from psycopg2.errors import SerializationFailure, UniqueViolation

from sportsmodel.database.connection import get_connection
from sportsmodel.nfl.market_math import (
    DECIMAL_PRECISION,
    CanonicalSelectionPrice,
    CompleteSportsbookMarket,
    build_complete_sportsbook_market,
    calculate_market_consensus,
    calculate_model_market_evaluation,
    calculate_per_book_no_vig,
    find_best_offered_price,
)
from sportsmodel.nfl.moneyline_frozen import (
    EARLY_FEATURE_SCHEMA_VERSION,
    EARLY_MODEL_FINGERPRINT,
    EARLY_SPECIFICATION_FINGERPRINT,
    EARLY_SPECIFICATION_VERSION,
MATURE_FEATURE_SCHEMA_VERSION,
    MATURE_MODEL_FINGERPRINT,
    MATURE_SPECIFICATION_VERSION,
    fingerprint_payload,
)
from sportsmodel.nfl.moneyline_prediction import (
    NFL_MONEYLINE_EVALUATION_PROTOCOL_VERSION,
)
from sportsmodel.nfl.moneyline_routing import (
    NFL_MONEYLINE_ROUTING_CONTRACT_VERSION,
)


MARKET_EVALUATION_PROTOCOL_VERSION = (
    "nfl_moneyline_market_evaluation_0.1.0"
)
MARKET_EVALUATION_PROTOCOL_FINGERPRINT = (
    "383592d724a83c991877dc940dc0f5f386b2f522725def58fef06f1035fbca0e"
)
PREDICTION_PROTOCOL_FINGERPRINT = (
    "7e211679904df35db95d2da7e559c5b1cc0650f2e2849048fae8247dba3c1aa7"
)
MATURE_SPECIFICATION_FINGERPRINT = (
    "49cbdb4ccc03b2a876aa4ba2bce2232da62c2eb5a09a9a2884d776b4ea684f38"
)
EVALUATION_KIND = "official_entry"
NFL_SPORT_KEY = "americanfootball_nfl"
ODDS_SOURCE_NAME = "odds_api"
MINIMUM_CONTRIBUTOR_COUNT = 5
DERIVED_QUANTUM = Decimal("0.0000000000000001")
PROTOCOL_PATH = (
    Path(__file__).resolve().parents[3]
    / "artifacts"
    / f"{MARKET_EVALUATION_PROTOCOL_VERSION}.json"
)

ConnectionFactory = Callable[[], Any]
SelectionSide = Literal["home", "away"]


class OfficialMarketEvaluationError(RuntimeError):
    """A fail-closed official evaluation result with a stable reason code."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        evaluation_run_id: int | None = None,
        source_graph_fingerprint: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.evaluation_run_id = evaluation_run_id
        self.source_graph_fingerprint = source_graph_fingerprint


class OfficialMarketEvaluationConflictError(OfficialMarketEvaluationError):
    """The immutable evaluation identity already has a different graph."""


@dataclass(frozen=True)
class OfficialMarketEvaluationContributor:
    provider_identity_id: int
    home_evidence_id: int
    away_evidence_id: int
    home_american_price: int
    away_american_price: int
    home_raw_implied_probability: Decimal
    away_raw_implied_probability: Decimal
    home_no_vig_probability: Decimal
    away_no_vig_probability: Decimal
    trusted_observed_at: datetime
    market_updated_at: datetime


@dataclass(frozen=True)
class OfficialMarketEvaluationExclusion:
    provider_identity_id: int
    reason_code: str


@dataclass(frozen=True)
class OfficialMarketEvaluation:
    evaluation_id: int
    prediction_id: int
    prediction_run_id: int
    game_id: int
    selected_team_id: int
    selected_side: SelectionSide
    odds_ingestion_run_id: int
    trusted_observed_at: datetime
    evaluation_created_at: datetime
    contributor_count: int
    consensus_no_vig_selected_probability: Decimal
    best_price_provider_identity_id: int
    best_price_evidence_id: int
    best_american_price: int
    best_decimal_odds: Decimal
    market_edge: Decimal
    model_expected_value: Decimal
    source_graph_fingerprint: str
    contributors: tuple[OfficialMarketEvaluationContributor, ...]
    exclusions: tuple[OfficialMarketEvaluationExclusion, ...]


@dataclass(frozen=True)
class OfficialMarketEvaluationExecutionResult:
    evaluation_run_id: int
    run_key: UUID
    evaluation: OfficialMarketEvaluation
    idempotent: bool


@dataclass(frozen=True)
class _PredictionSource:
    prediction_id: int
    prediction_run_id: int
    run_type: str
    protocol_version: str
    game_id: int
    target_kickoff: datetime
    prediction_created_at: datetime
    home_team_id: int
    away_team_id: int
    selected_route: str
    routing_contract_version: str
    model_specification_version: str
    feature_schema_version: str
    specification_fingerprint: str
    model_fingerprint: str
    model_home_win_probability: Decimal
    predicted_side: str
    run_status: str
    run_completed_at: datetime | None
    early_model_specification_version: str
    early_feature_schema_version: str
    early_specification_fingerprint: str
    early_model_fingerprint: str
    mature_model_specification_version: str
    mature_feature_schema_version: str
    mature_specification_fingerprint: str
    mature_model_fingerprint: str
    current_kickoff: datetime
    current_game_status: str
    current_home_team_id: int
    current_away_team_id: int

    @property
    def selected_side(self) -> SelectionSide:
        return self.predicted_side  # type: ignore[return-value]

    @property
    def selected_team_id(self) -> int:
        return (
            self.home_team_id
            if self.predicted_side == "home"
            else self.away_team_id
        )

    @property
    def selected_model_probability(self) -> Decimal:
        if self.predicted_side == "home":
            return self.model_home_win_probability
        return Decimal("1.0000000000000000") - self.model_home_win_probability


@dataclass(frozen=True)
class _OddsRunSource:
    odds_ingestion_run_id: int
    sport: str
    source_name: str
    snapshot_role: str | None
    status: str
    request_started_at: datetime | None
    response_received_at: datetime | None


@dataclass(frozen=True)
class _EvidenceSource:
    evidence_id: int
    odds_ingestion_run_id: int
    provider_identity_id: int
    game_id: int
    selection_team_id: int
    american_price: int
    trusted_observed_at: datetime
    canonical_kickoff: datetime
    bookmaker_updated_at: datetime | None
    market_updated_at: datetime | None


@dataclass(frozen=True)
class _PreparedContributor:
    source: OfficialMarketEvaluationContributor
    market: CompleteSportsbookMarket


@dataclass(frozen=True)
class _PreparedEvaluation:
    prediction: _PredictionSource
    odds_run: _OddsRunSource
    contributors: tuple[_PreparedContributor, ...]
    exclusions: tuple[OfficialMarketEvaluationExclusion, ...]
    consensus_selected_probability: Decimal
    best_provider_identity_id: int
    best_evidence_id: int
    best_american_price: int
    best_decimal_odds: Decimal
    market_edge: Decimal
    model_expected_value: Decimal
    source_graph_fingerprint: str


def evaluate_official_nfl_moneyline_market(
    *,
    prediction_id: int,
    odds_ingestion_run_id: int,
    run_key: UUID | None = None,
    connection_factory: ConnectionFactory = get_connection,
) -> OfficialMarketEvaluationExecutionResult:
    """Persist one immutable official-entry market evaluation atomically."""

    _require_positive_identifier(prediction_id, "prediction_id")
    _require_positive_identifier(
        odds_ingestion_run_id,
        "odds_ingestion_run_id",
    )
    _load_and_verify_market_protocol()
    resolved_run_key = run_key or uuid4()
    request_sha256 = fingerprint_payload(
        {
            "evaluation_kind": EVALUATION_KIND,
            "market_evaluation_protocol_fingerprint": (
                MARKET_EVALUATION_PROTOCOL_FINGERPRINT
            ),
            "market_evaluation_protocol_version": (
                MARKET_EVALUATION_PROTOCOL_VERSION
            ),
            "nfl_moneyline_game_prediction_id": prediction_id,
            "odds_ingestion_run_id": odds_ingestion_run_id,
        }
    )

    for attempt in range(3):
        try:
            return _execute_evaluation_attempt(
                prediction_id=prediction_id,
                odds_ingestion_run_id=odds_ingestion_run_id,
                run_key=resolved_run_key,
                request_sha256=request_sha256,
                connection_factory=connection_factory,
            )
        except (SerializationFailure, UniqueViolation) as error:
            identity_race = (
                isinstance(error, SerializationFailure)
                or error.diag.constraint_name
                == "uq_nfl_market_evaluation_identity"
            )
            if not identity_race or attempt == 2:
                raise
    raise AssertionError("unreachable evaluation retry state")


def _execute_evaluation_attempt(
    *,
    prediction_id: int,
    odds_ingestion_run_id: int,
    run_key: UUID,
    request_sha256: str,
    connection_factory: ConnectionFactory,
) -> OfficialMarketEvaluationExecutionResult:
    connection = connection_factory()
    evaluation_run_id: int | None = None
    try:
        connection.set_session(isolation_level="REPEATABLE READ")
        with connection.cursor() as cursor:
            prediction = _load_prediction_source(cursor, prediction_id)
            odds_run = _load_odds_run_source(cursor, odds_ingestion_run_id)
            evaluation_run_id = _insert_evaluation_run(
                cursor,
                run_key=run_key,
                request_sha256=request_sha256,
                prediction=prediction,
                odds_run=odds_run,
            )
            cursor.execute("SAVEPOINT official_evaluation_work")
            existing = _load_existing_evaluation_identity(
                cursor,
                prediction_id=prediction_id,
            )
            try:
                prepared = _prepare_evaluation(
                    cursor,
                    prediction=prediction,
                    odds_run=odds_run,
                    enforce_creation_eligibility=(existing is None),
                )
                if existing is not None:
                    if existing[1] != prepared.source_graph_fingerprint:
                        raise OfficialMarketEvaluationConflictError(
                            "source_graph_conflict",
                            "The official evaluation identity already has a "
                            "different immutable source graph.",
                            source_graph_fingerprint=(
                                prepared.source_graph_fingerprint
                            ),
                        )
                    _complete_evaluation_run(
                        cursor,
                        evaluation_run_id=evaluation_run_id,
                        evaluation_id=existing[0],
                        source_graph_fingerprint=(
                            prepared.source_graph_fingerprint
                        ),
                    )
                    evaluation = _load_evaluation(cursor, existing[0])
                    connection.commit()
                    return OfficialMarketEvaluationExecutionResult(
                        evaluation_run_id=evaluation_run_id,
                        run_key=run_key,
                        evaluation=evaluation,
                        idempotent=True,
                    )

                evaluation_id = _insert_evaluation_parent(
                    cursor,
                    evaluation_run_id=evaluation_run_id,
                    prepared=prepared,
                )
                _insert_contributors(
                    cursor,
                    evaluation_id=evaluation_id,
                    prepared=prepared,
                )
                _insert_exclusions(
                    cursor,
                    evaluation_id=evaluation_id,
                    exclusions=prepared.exclusions,
                )
                cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
                _complete_evaluation_run(
                    cursor,
                    evaluation_run_id=evaluation_run_id,
                    evaluation_id=evaluation_id,
                    source_graph_fingerprint=(
                        prepared.source_graph_fingerprint
                    ),
                )
                evaluation = _load_evaluation(cursor, evaluation_id)
                connection.commit()
                return OfficialMarketEvaluationExecutionResult(
                    evaluation_run_id=evaluation_run_id,
                    run_key=run_key,
                    evaluation=evaluation,
                    idempotent=False,
                )
            except (SerializationFailure, UniqueViolation):
                connection.rollback()
                raise
            except OfficialMarketEvaluationError as error:
                cursor.execute("ROLLBACK TO SAVEPOINT official_evaluation_work")
                _fail_evaluation_run(
                    cursor,
                    evaluation_run_id=evaluation_run_id,
                    error=error,
                )
                connection.commit()
                error.evaluation_run_id = evaluation_run_id
                raise
            except Exception as error:
                cursor.execute("ROLLBACK TO SAVEPOINT official_evaluation_work")
                wrapped = OfficialMarketEvaluationError(
                    "persistence_error",
                    f"Official evaluation persistence failed: {error}",
                    evaluation_run_id=evaluation_run_id,
                )
                _fail_evaluation_run(
                    cursor,
                    evaluation_run_id=evaluation_run_id,
                    error=wrapped,
                )
                connection.commit()
                raise wrapped from error
    except Exception:
        if not connection.closed:
            connection.rollback()
        raise
    finally:
        connection.close()


def _load_and_verify_market_protocol() -> dict[str, Any]:
    try:
        protocol = json.loads(PROTOCOL_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise OfficialMarketEvaluationError(
            "protocol_artifact_unavailable",
            "The frozen market evaluation protocol artifact could not be loaded.",
        ) from error
    stored_fingerprint = protocol.pop("protocol_fingerprint", None)
    actual_fingerprint = fingerprint_payload(protocol)
    if (
        protocol.get("protocol_version")
        != MARKET_EVALUATION_PROTOCOL_VERSION
        or stored_fingerprint != MARKET_EVALUATION_PROTOCOL_FINGERPRINT
        or actual_fingerprint != MARKET_EVALUATION_PROTOCOL_FINGERPRINT
    ):
        raise OfficialMarketEvaluationError(
            "protocol_identity_mismatch",
            "The frozen market evaluation protocol identity is not recognized.",
        )
    return protocol


def _load_prediction_source(cursor: Any, prediction_id: int) -> _PredictionSource:
    cursor.execute(
        "SELECT nfl_moneyline_game_prediction_id "
        "FROM nfl_moneyline_game_predictions "
        "WHERE nfl_moneyline_game_prediction_id = %s FOR UPDATE",
        (prediction_id,),
    )
    if cursor.fetchone() is None:
        raise OfficialMarketEvaluationError(
            "prediction_not_found",
            "The NFL Moneyline prediction does not exist.",
        )
    cursor.execute(
        """
        SELECT
            prediction.nfl_moneyline_game_prediction_id,
            prediction.nfl_moneyline_prediction_run_id,
            prediction.run_type,
            prediction.evaluation_protocol_version,
            prediction.game_id,
            prediction.target_kickoff,
            prediction.prediction_created_at,
            prediction.home_team_id,
            prediction.away_team_id,
            prediction.selected_route,
            prediction.routing_contract_version,
            prediction.selected_model_specification_version,
            prediction.feature_schema_version,
            prediction.specification_fingerprint,
            prediction.model_fingerprint,
            prediction.model_home_win_probability,
            prediction.predicted_side,
            run.status,
            run.completed_at,
            run.early_model_specification_version,
            run.early_feature_schema_version,
            run.early_specification_fingerprint,
            run.early_model_fingerprint,
            run.mature_model_specification_version,
            run.mature_feature_schema_version,
            run.mature_specification_fingerprint,
            run.mature_model_fingerprint,
            nfl.scheduled_start_time,
            nfl.status,
            game.home_team_id,
            game.away_team_id
        FROM nfl_moneyline_game_predictions AS prediction
        JOIN nfl_moneyline_prediction_runs AS run
          ON run.nfl_moneyline_prediction_run_id
            = prediction.nfl_moneyline_prediction_run_id
        JOIN nfl_games AS nfl ON nfl.game_id = prediction.game_id
        JOIN games AS game ON game.game_id = prediction.game_id
        WHERE prediction.nfl_moneyline_game_prediction_id = %s
        FOR SHARE OF run, nfl, game
        """,
        (prediction_id,),
    )
    row = cursor.fetchone()
    if row is None:
        raise OfficialMarketEvaluationError(
            "prediction_source_incomplete",
            "The persisted prediction source graph is incomplete.",
        )
    return _PredictionSource(*row)


def _load_odds_run_source(cursor: Any, odds_run_id: int) -> _OddsRunSource:
    cursor.execute(
        """
        SELECT odds_ingestion_run_id, sport, source_name, snapshot_role,
               status, request_started_at, response_received_at
        FROM odds_ingestion_runs
        WHERE odds_ingestion_run_id = %s
        FOR SHARE
        """,
        (odds_run_id,),
    )
    row = cursor.fetchone()
    if row is None:
        raise OfficialMarketEvaluationError(
            "odds_run_not_found",
            "The odds ingestion run does not exist.",
        )
    return _OddsRunSource(*row)


def _prepare_evaluation(
    cursor: Any,
    *,
    prediction: _PredictionSource,
    odds_run: _OddsRunSource,
    enforce_creation_eligibility: bool,
) -> _PreparedEvaluation:
    _validate_prediction_source(
        prediction,
        enforce_current_eligibility=enforce_creation_eligibility,
    )
    _validate_odds_run_source(
        prediction,
        odds_run,
        enforce_current_eligibility=enforce_creation_eligibility,
    )
    if enforce_creation_eligibility:
        cursor.execute("SELECT clock_timestamp()")
        _validate_evaluation_clock(
            prediction=prediction,
            odds_run=odds_run,
            evaluation_created_at=cursor.fetchone()[0],
        )
    evidence = _load_official_evidence(
        cursor,
        game_id=prediction.game_id,
        odds_run_id=odds_run.odds_ingestion_run_id,
    )
    contributors, exclusions = _select_contributors(
        prediction=prediction,
        odds_run=odds_run,
        evidence=evidence,
    )
    if len(contributors) < MINIMUM_CONTRIBUTOR_COUNT:
        partial_fingerprint = _source_graph_fingerprint(
            prediction=prediction,
            odds_run=odds_run,
            contributors=contributors,
            exclusions=exclusions,
            best_evidence_id=None,
            best_provider_identity_id=None,
        )
        raise OfficialMarketEvaluationError(
            "insufficient_coverage",
            "Official entry evaluation requires at least five complete "
            f"provider markets; found {len(contributors)}.",
            source_graph_fingerprint=partial_fingerprint,
        )

    complete_markets = tuple(item.market for item in contributors)
    no_vig_markets = tuple(
        calculate_per_book_no_vig(market) for market in complete_markets
    )
    consensus = calculate_market_consensus(no_vig_markets)
    best_price = find_best_offered_price(
        complete_markets,
        selection_side=prediction.selected_side,
    )
    math = calculate_model_market_evaluation(
        model_probability=prediction.selected_model_probability,
        consensus=consensus,
        best_price=best_price,
    )
    best_contributor = next(
        contributor
        for contributor in contributors
        if contributor.source.provider_identity_id
        == best_price.sportsbook_provider_identity_id
    )
    best_evidence_id = (
        best_contributor.source.home_evidence_id
        if prediction.selected_side == "home"
        else best_contributor.source.away_evidence_id
    )
    graph_fingerprint = _source_graph_fingerprint(
        prediction=prediction,
        odds_run=odds_run,
        contributors=contributors,
        exclusions=exclusions,
        best_evidence_id=best_evidence_id,
        best_provider_identity_id=(
            best_price.sportsbook_provider_identity_id
        ),
    )
    selected_consensus = (
        consensus.home_no_vig_probability
        if prediction.selected_side == "home"
        else consensus.away_no_vig_probability
    )
    return _PreparedEvaluation(
        prediction=prediction,
        odds_run=odds_run,
        contributors=contributors,
        exclusions=exclusions,
        consensus_selected_probability=_quantize(selected_consensus),
        best_provider_identity_id=(
            best_price.sportsbook_provider_identity_id
        ),
        best_evidence_id=best_evidence_id,
        best_american_price=best_price.american_price,
        best_decimal_odds=_quantize(best_price.decimal_odds),
        market_edge=_quantize(math.market_edge),
        model_expected_value=_quantize(math.model_expected_value),
        source_graph_fingerprint=graph_fingerprint,
    )


def _validate_prediction_source(
    prediction: _PredictionSource,
    *,
    enforce_current_eligibility: bool,
) -> None:
    if (
        prediction.run_status != "completed"
        or prediction.run_completed_at is None
        or prediction.run_type != "official"
        or prediction.protocol_version
        != NFL_MONEYLINE_EVALUATION_PROTOCOL_VERSION
        or prediction.routing_contract_version
        != NFL_MONEYLINE_ROUTING_CONTRACT_VERSION
        or prediction.predicted_side not in ("home", "away")
    ):
        raise OfficialMarketEvaluationError(
            "prediction_ineligible",
            "A completed official prediction under the frozen forward protocol "
            "is required.",
        )
    expected_route_identity = {
        "early": (
            EARLY_SPECIFICATION_VERSION,
            EARLY_FEATURE_SCHEMA_VERSION,
            EARLY_SPECIFICATION_FINGERPRINT,
            EARLY_MODEL_FINGERPRINT,
            prediction.early_model_specification_version,
            prediction.early_feature_schema_version,
            prediction.early_specification_fingerprint,
            prediction.early_model_fingerprint,
        ),
        "mature": (
            MATURE_SPECIFICATION_VERSION,
            MATURE_FEATURE_SCHEMA_VERSION,
            MATURE_SPECIFICATION_FINGERPRINT,
            MATURE_MODEL_FINGERPRINT,
            prediction.mature_model_specification_version,
            prediction.mature_feature_schema_version,
            prediction.mature_specification_fingerprint,
            prediction.mature_model_fingerprint,
        ),
    }.get(prediction.selected_route)
    if expected_route_identity is None:
        raise OfficialMarketEvaluationError(
            "prediction_identity_unknown",
            "The persisted prediction route is not recognized.",
        )
    selected_identity = (
        prediction.model_specification_version,
        prediction.feature_schema_version,
        prediction.specification_fingerprint,
        prediction.model_fingerprint,
    )
    if (
        selected_identity != expected_route_identity[:4]
        or selected_identity != expected_route_identity[4:]
    ):
        raise OfficialMarketEvaluationError(
            "prediction_identity_unknown",
            "The persisted route/model/schema/fingerprint identity is not frozen.",
        )
    if prediction.prediction_created_at >= prediction.target_kickoff:
        raise OfficialMarketEvaluationError(
            "canonical_game_identity_mismatch",
            "The persisted prediction is not strictly pre-kickoff.",
        )
    if enforce_current_eligibility:
        if (
            prediction.current_home_team_id != prediction.home_team_id
            or prediction.current_away_team_id != prediction.away_team_id
            or prediction.current_kickoff != prediction.target_kickoff
        ):
            raise OfficialMarketEvaluationError(
                "canonical_game_identity_mismatch",
                "The prediction and current canonical NFL game identity disagree.",
            )
        if prediction.current_game_status != "unplayed":
            raise OfficialMarketEvaluationError(
                "game_already_played",
                "Official market evaluation requires an unplayed canonical game.",
            )


def _validate_odds_run_source(
    prediction: _PredictionSource,
    odds_run: _OddsRunSource,
    *,
    enforce_current_eligibility: bool,
) -> None:
    if (
        odds_run.sport != NFL_SPORT_KEY
        or odds_run.source_name != ODDS_SOURCE_NAME
        or odds_run.snapshot_role != "entry"
        or odds_run.status != "completed"
        or odds_run.request_started_at is None
        or odds_run.response_received_at is None
    ):
        raise OfficialMarketEvaluationError(
            "odds_run_ineligible",
            "A completed NFL Odds API entry run with trusted timing is required.",
        )
    if not enforce_current_eligibility:
        return
    if (
        prediction.run_completed_at is None
        or prediction.run_completed_at > odds_run.request_started_at
        or prediction.prediction_created_at >= odds_run.response_received_at
        or (
            odds_run.response_received_at - prediction.prediction_created_at
        ).total_seconds()
        > 900
        or odds_run.response_received_at >= prediction.current_kickoff
    ):
        raise OfficialMarketEvaluationError(
            "prediction_market_timing_ineligible",
            "Prediction, odds request, and trusted receipt violate the frozen "
            "entry ordering or 900-second boundary.",
        )


def _validate_evaluation_clock(
    *,
    prediction: _PredictionSource,
    odds_run: _OddsRunSource,
    evaluation_created_at: datetime,
) -> None:
    receipt = odds_run.response_received_at
    if receipt is None:
        raise AssertionError("validated odds receipt unexpectedly missing")
    if (
        evaluation_created_at < receipt
        or (evaluation_created_at - receipt).total_seconds() > 300
        or evaluation_created_at >= prediction.current_kickoff
    ):
        raise OfficialMarketEvaluationError(
            "evaluation_timing_ineligible",
            "Database evaluation time must be at or after trusted receipt, no "
            "more than 300 seconds later, and strictly before kickoff.",
        )


def _load_official_evidence(
    cursor: Any,
    *,
    game_id: int,
    odds_run_id: int,
) -> tuple[_EvidenceSource, ...]:
    cursor.execute(
        """
        SELECT nfl_official_pregame_evidence_id,
               odds_ingestion_run_id,
               sportsbook_provider_identity_id,
               game_id,
               canonical_selection_team_id,
               american_price,
               trusted_observed_at,
               canonical_kickoff_at_qualification,
               bookmaker_updated_at,
               market_updated_at
        FROM nfl_official_pregame_evidence
        WHERE game_id = %s AND odds_ingestion_run_id = %s
        ORDER BY sportsbook_provider_identity_id,
                 nfl_official_pregame_evidence_id
        FOR SHARE
        """,
        (game_id, odds_run_id),
    )
    return tuple(_EvidenceSource(*row) for row in cursor.fetchall())


def _select_contributors(
    *,
    prediction: _PredictionSource,
    odds_run: _OddsRunSource,
    evidence: tuple[_EvidenceSource, ...],
) -> tuple[
    tuple[_PreparedContributor, ...],
    tuple[OfficialMarketEvaluationExclusion, ...],
]:
    if odds_run.response_received_at is None:
        raise AssertionError("validated odds receipt unexpectedly missing")
    by_provider: dict[int, list[_EvidenceSource]] = defaultdict(list)
    for row in evidence:
        if (
            row.odds_ingestion_run_id != odds_run.odds_ingestion_run_id
            or row.game_id != prediction.game_id
            or row.trusted_observed_at != odds_run.response_received_at
            or row.canonical_kickoff != prediction.target_kickoff
            or row.selection_team_id
            not in (prediction.home_team_id, prediction.away_team_id)
        ):
            raise OfficialMarketEvaluationError(
                "source_graph_identity_conflict",
                "Official quote evidence crosses the required run/game/time/team "
                "source context.",
            )
        by_provider[row.provider_identity_id].append(row)

    contributors: list[_PreparedContributor] = []
    exclusions: list[OfficialMarketEvaluationExclusion] = []
    for provider_identity_id in sorted(by_provider):
        rows = by_provider[provider_identity_id]
        if len(rows) > 2:
            raise OfficialMarketEvaluationError(
                "ambiguous_provider_market",
                "A provider has duplicate or multiple official H2H selections.",
            )
        rows_by_team = {row.selection_team_id: row for row in rows}
        if len(rows_by_team) != len(rows):
            raise OfficialMarketEvaluationError(
                "ambiguous_provider_market",
                "A provider has a duplicate canonical selection.",
            )
        if set(rows_by_team) != {
            prediction.home_team_id,
            prediction.away_team_id,
        }:
            exclusions.append(
                OfficialMarketEvaluationExclusion(
                    provider_identity_id=provider_identity_id,
                    reason_code="incomplete_market",
                )
            )
            continue
        home = rows_by_team[prediction.home_team_id]
        away = rows_by_team[prediction.away_team_id]
        if home.market_updated_at != away.market_updated_at:
            raise OfficialMarketEvaluationError(
                "conflicting_provider_timestamps",
                "A complete provider pair has conflicting market timestamps.",
            )
        if (
            home.bookmaker_updated_at is not None
            and home.bookmaker_updated_at > odds_run.response_received_at
        ) or (
            away.bookmaker_updated_at is not None
            and away.bookmaker_updated_at > odds_run.response_received_at
        ):
            raise OfficialMarketEvaluationError(
                "future_provider_timestamp",
                "Provider provenance timestamps cannot be later than trusted "
                "receipt.",
            )
        market_updated_at = home.market_updated_at
        if (
            market_updated_at is None
            or market_updated_at > odds_run.response_received_at
            or (
                odds_run.response_received_at - market_updated_at
            ).total_seconds()
            > 300
        ):
            exclusions.append(
                OfficialMarketEvaluationExclusion(
                    provider_identity_id=provider_identity_id,
                    reason_code="stale_market",
                )
            )
            continue
        market = build_complete_sportsbook_market(
            (
                CanonicalSelectionPrice(
                    sport_key=NFL_SPORT_KEY,
                    canonical_game_id=prediction.game_id,
                    home_team_id=prediction.home_team_id,
                    away_team_id=prediction.away_team_id,
                    selection_team_id=prediction.home_team_id,
                    selection_side="home",
                    sportsbook_provider_identity_id=provider_identity_id,
                    american_price=home.american_price,
                    trusted_observed_at=home.trusted_observed_at,
                ),
                CanonicalSelectionPrice(
                    sport_key=NFL_SPORT_KEY,
                    canonical_game_id=prediction.game_id,
                    home_team_id=prediction.home_team_id,
                    away_team_id=prediction.away_team_id,
                    selection_team_id=prediction.away_team_id,
                    selection_side="away",
                    sportsbook_provider_identity_id=provider_identity_id,
                    american_price=away.american_price,
                    trusted_observed_at=away.trusted_observed_at,
                ),
            )
        )
        no_vig = calculate_per_book_no_vig(market)
        contributors.append(
            _PreparedContributor(
                source=OfficialMarketEvaluationContributor(
                    provider_identity_id=provider_identity_id,
                    home_evidence_id=home.evidence_id,
                    away_evidence_id=away.evidence_id,
                    home_american_price=home.american_price,
                    away_american_price=away.american_price,
                    home_raw_implied_probability=_quantize(
                        no_vig.home.implied_probability
                    ),
                    away_raw_implied_probability=_quantize(
                        no_vig.away.implied_probability
                    ),
                    home_no_vig_probability=_quantize(
                        no_vig.home.no_vig_probability
                    ),
                    away_no_vig_probability=_quantize(
                        no_vig.away.no_vig_probability
                    ),
                    trusted_observed_at=home.trusted_observed_at,
                    market_updated_at=market_updated_at,
                ),
                market=market,
            )
        )
    return tuple(contributors), tuple(exclusions)


def _source_graph_fingerprint(
    *,
    prediction: _PredictionSource,
    odds_run: _OddsRunSource,
    contributors: tuple[_PreparedContributor, ...],
    exclusions: tuple[OfficialMarketEvaluationExclusion, ...],
    best_evidence_id: int | None,
    best_provider_identity_id: int | None,
) -> str:
    return fingerprint_payload(
        {
            "best_price": {
                "evidence_id": best_evidence_id,
                "sportsbook_provider_identity_id": (
                    best_provider_identity_id
                ),
            },
            "contributors": [
                {
                    "away_american_price": item.source.away_american_price,
                    "away_evidence_id": item.source.away_evidence_id,
                    "home_american_price": item.source.home_american_price,
                    "home_evidence_id": item.source.home_evidence_id,
                    "market_updated_at": _utc_text(
                        item.source.market_updated_at
                    ),
                    "sportsbook_provider_identity_id": (
                        item.source.provider_identity_id
                    ),
                }
                for item in contributors
            ],
            "evaluation_kind": EVALUATION_KIND,
            "exclusions": [
                {
                    "reason_code": item.reason_code,
                    "sportsbook_provider_identity_id": (
                        item.provider_identity_id
                    ),
                }
                for item in exclusions
            ],
            "market_evaluation_protocol_fingerprint": (
                MARKET_EVALUATION_PROTOCOL_FINGERPRINT
            ),
            "market_evaluation_protocol_version": (
                MARKET_EVALUATION_PROTOCOL_VERSION
            ),
            "odds": {
                "odds_ingestion_run_id": odds_run.odds_ingestion_run_id,
                "trusted_observed_at": _utc_text(
                    _require_timestamp(odds_run.response_received_at)
                ),
            },
            "prediction": {
                "away_team_id": prediction.away_team_id,
                "feature_schema_version": prediction.feature_schema_version,
                "game_id": prediction.game_id,
                "home_team_id": prediction.home_team_id,
                "model_fingerprint": prediction.model_fingerprint,
                "model_probability": format(
                    prediction.selected_model_probability,
                    ".16f",
                ),
                "model_specification_version": (
                    prediction.model_specification_version
                ),
                "nfl_moneyline_game_prediction_id": prediction.prediction_id,
                "nfl_moneyline_prediction_run_id": (
                    prediction.prediction_run_id
                ),
                "prediction_created_at": _utc_text(
                    prediction.prediction_created_at
                ),
                "prediction_protocol_fingerprint": (
                    PREDICTION_PROTOCOL_FINGERPRINT
                ),
                "prediction_protocol_version": prediction.protocol_version,
                "routing_contract_version": (
                    prediction.routing_contract_version
                ),
                "selected_route": prediction.selected_route,
                "selected_side": prediction.selected_side,
                "selected_team_id": prediction.selected_team_id,
                "specification_fingerprint": (
                    prediction.specification_fingerprint
                ),
                "target_kickoff": _utc_text(prediction.target_kickoff),
            },
            "source_graph_schema": (
                "nfl_moneyline_market_evaluation_source_graph_0.1.0"
            ),
        }
    )


def _insert_evaluation_run(
    cursor: Any,
    *,
    run_key: UUID,
    request_sha256: str,
    prediction: _PredictionSource,
    odds_run: _OddsRunSource,
) -> int:
    cursor.execute(
        """
        INSERT INTO nfl_moneyline_market_evaluation_runs (
            run_key, request_sha256, nfl_moneyline_game_prediction_id,
            nfl_moneyline_prediction_run_id, odds_ingestion_run_id,
            market_evaluation_protocol_version,
            market_evaluation_protocol_fingerprint, evaluation_kind
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING nfl_moneyline_market_evaluation_run_id
        """,
        (
            run_key,
            request_sha256,
            prediction.prediction_id,
            prediction.prediction_run_id,
            odds_run.odds_ingestion_run_id,
            MARKET_EVALUATION_PROTOCOL_VERSION,
            MARKET_EVALUATION_PROTOCOL_FINGERPRINT,
            EVALUATION_KIND,
        ),
    )
    return cursor.fetchone()[0]


def _insert_evaluation_parent(
    cursor: Any,
    *,
    evaluation_run_id: int,
    prepared: _PreparedEvaluation,
) -> int:
    prediction = prepared.prediction
    odds_run = prepared.odds_run
    cursor.execute(
        """
        INSERT INTO nfl_moneyline_market_evaluations (
            creation_evaluation_run_id,
            nfl_moneyline_game_prediction_id,
            nfl_moneyline_prediction_run_id,
            game_id, home_team_id, away_team_id, selected_team_id,
            selected_side, selected_route, prediction_run_type,
            prediction_protocol_version, prediction_protocol_fingerprint,
            routing_contract_version, selected_model_specification_version,
            feature_schema_version, specification_fingerprint,
            model_fingerprint, selected_model_probability,
            prediction_created_at, odds_ingestion_run_id,
            trusted_observed_at, canonical_kickoff_at_evaluation,
            market_evaluation_protocol_version,
            market_evaluation_protocol_fingerprint, evaluation_kind,
            contributor_count, consensus_no_vig_selected_probability,
            best_price_sportsbook_provider_identity_id,
            best_price_nfl_official_pregame_evidence_id,
            best_american_price, best_decimal_odds, market_edge,
            model_expected_value, source_graph_fingerprint
        ) VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s
        )
        RETURNING nfl_moneyline_market_evaluation_id
        """,
        (
            evaluation_run_id,
            prediction.prediction_id,
            prediction.prediction_run_id,
            prediction.game_id,
            prediction.home_team_id,
            prediction.away_team_id,
            prediction.selected_team_id,
            prediction.selected_side,
            prediction.selected_route,
            prediction.run_type,
            prediction.protocol_version,
            PREDICTION_PROTOCOL_FINGERPRINT,
            prediction.routing_contract_version,
            prediction.model_specification_version,
            prediction.feature_schema_version,
            prediction.specification_fingerprint,
            prediction.model_fingerprint,
            prediction.selected_model_probability,
            prediction.prediction_created_at,
            odds_run.odds_ingestion_run_id,
            odds_run.response_received_at,
            prediction.current_kickoff,
            MARKET_EVALUATION_PROTOCOL_VERSION,
            MARKET_EVALUATION_PROTOCOL_FINGERPRINT,
            EVALUATION_KIND,
            len(prepared.contributors),
            prepared.consensus_selected_probability,
            prepared.best_provider_identity_id,
            prepared.best_evidence_id,
            prepared.best_american_price,
            prepared.best_decimal_odds,
            prepared.market_edge,
            prepared.model_expected_value,
            prepared.source_graph_fingerprint,
        ),
    )
    return cursor.fetchone()[0]


def _insert_contributors(
    cursor: Any,
    *,
    evaluation_id: int,
    prepared: _PreparedEvaluation,
) -> None:
    for ordinal, item in enumerate(prepared.contributors, start=1):
        source = item.source
        cursor.execute(
            """
            INSERT INTO nfl_moneyline_market_evaluation_contributors (
                nfl_moneyline_market_evaluation_id,
                odds_ingestion_run_id, game_id, trusted_observed_at,
                contributor_ordinal, sportsbook_provider_identity_id,
                home_nfl_official_pregame_evidence_id,
                away_nfl_official_pregame_evidence_id,
                home_american_price, away_american_price,
                home_raw_implied_probability,
                away_raw_implied_probability,
                home_no_vig_probability, away_no_vig_probability,
                market_updated_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s
            )
            """,
            (
                evaluation_id,
                prepared.odds_run.odds_ingestion_run_id,
                prepared.prediction.game_id,
                source.trusted_observed_at,
                ordinal,
                source.provider_identity_id,
                source.home_evidence_id,
                source.away_evidence_id,
                source.home_american_price,
                source.away_american_price,
                source.home_raw_implied_probability,
                source.away_raw_implied_probability,
                source.home_no_vig_probability,
                source.away_no_vig_probability,
                source.market_updated_at,
            ),
        )


def _insert_exclusions(
    cursor: Any,
    *,
    evaluation_id: int,
    exclusions: tuple[OfficialMarketEvaluationExclusion, ...],
) -> None:
    for exclusion in exclusions:
        cursor.execute(
            """
            INSERT INTO nfl_moneyline_market_evaluation_exclusions (
                nfl_moneyline_market_evaluation_id,
                sportsbook_provider_identity_id,
                reason_code
            ) VALUES (%s, %s, %s)
            """,
            (
                evaluation_id,
                exclusion.provider_identity_id,
                exclusion.reason_code,
            ),
        )


def _complete_evaluation_run(
    cursor: Any,
    *,
    evaluation_run_id: int,
    evaluation_id: int,
    source_graph_fingerprint: str,
) -> None:
    cursor.execute(
        """
        UPDATE nfl_moneyline_market_evaluation_runs
        SET status = 'completed', evaluation_count = 1,
            nfl_moneyline_market_evaluation_id = %s,
            source_graph_fingerprint = %s
        WHERE nfl_moneyline_market_evaluation_run_id = %s
        """,
        (evaluation_id, source_graph_fingerprint, evaluation_run_id),
    )


def _fail_evaluation_run(
    cursor: Any,
    *,
    evaluation_run_id: int,
    error: OfficialMarketEvaluationError,
) -> None:
    cursor.execute(
        """
        UPDATE nfl_moneyline_market_evaluation_runs
        SET status = 'failed', failure_code = %s, failure_message = %s,
            source_graph_fingerprint = %s
        WHERE nfl_moneyline_market_evaluation_run_id = %s
        """,
        (
            error.code,
            str(error),
            error.source_graph_fingerprint,
            evaluation_run_id,
        ),
    )


def _load_existing_evaluation_identity(
    cursor: Any,
    *,
    prediction_id: int,
) -> tuple[int, str] | None:
    cursor.execute(
        """
        SELECT nfl_moneyline_market_evaluation_id, source_graph_fingerprint
        FROM nfl_moneyline_market_evaluations
        WHERE nfl_moneyline_game_prediction_id = %s
          AND market_evaluation_protocol_version = %s
          AND evaluation_kind = %s
        """,
        (
            prediction_id,
            MARKET_EVALUATION_PROTOCOL_VERSION,
            EVALUATION_KIND,
        ),
    )
    return cursor.fetchone()


def _load_evaluation(cursor: Any, evaluation_id: int) -> OfficialMarketEvaluation:
    cursor.execute(
        """
        SELECT nfl_moneyline_market_evaluation_id,
               nfl_moneyline_game_prediction_id,
               nfl_moneyline_prediction_run_id,
               game_id, selected_team_id, selected_side,
               odds_ingestion_run_id, trusted_observed_at,
               evaluation_created_at, contributor_count,
               consensus_no_vig_selected_probability,
               best_price_sportsbook_provider_identity_id,
               best_price_nfl_official_pregame_evidence_id,
               best_american_price, best_decimal_odds, market_edge,
               model_expected_value, source_graph_fingerprint
        FROM nfl_moneyline_market_evaluations
        WHERE nfl_moneyline_market_evaluation_id = %s
        """,
        (evaluation_id,),
    )
    parent = cursor.fetchone()
    if parent is None:
        raise RuntimeError("Persisted official evaluation disappeared")
    cursor.execute(
        """
        SELECT sportsbook_provider_identity_id,
               home_nfl_official_pregame_evidence_id,
               away_nfl_official_pregame_evidence_id,
               home_american_price, away_american_price,
               home_raw_implied_probability,
               away_raw_implied_probability,
               home_no_vig_probability, away_no_vig_probability,
               trusted_observed_at, market_updated_at
        FROM nfl_moneyline_market_evaluation_contributors
        WHERE nfl_moneyline_market_evaluation_id = %s
        ORDER BY contributor_ordinal
        """,
        (evaluation_id,),
    )
    contributors = tuple(
        OfficialMarketEvaluationContributor(*row) for row in cursor.fetchall()
    )
    cursor.execute(
        """
        SELECT sportsbook_provider_identity_id, reason_code
        FROM nfl_moneyline_market_evaluation_exclusions
        WHERE nfl_moneyline_market_evaluation_id = %s
        ORDER BY sportsbook_provider_identity_id
        """,
        (evaluation_id,),
    )
    exclusions = tuple(
        OfficialMarketEvaluationExclusion(*row) for row in cursor.fetchall()
    )
    return OfficialMarketEvaluation(
        *parent,
        contributors=contributors,
        exclusions=exclusions,
    )


def _quantize(value: Decimal) -> Decimal:
    with localcontext() as context:
        context.prec = DECIMAL_PRECISION
        return value.quantize(DERIVED_QUANTUM, rounding=ROUND_HALF_EVEN)


def _utc_text(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise OfficialMarketEvaluationError(
            "naive_timestamp",
            "Official market evaluation timestamps must be timezone-aware.",
        )
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _require_timestamp(value: datetime | None) -> datetime:
    if value is None:
        raise AssertionError("validated timestamp unexpectedly missing")
    return value


def _require_positive_identifier(value: int, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field_name} must be a positive integer")
