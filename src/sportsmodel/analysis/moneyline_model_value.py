from collections.abc import Iterable
from decimal import Decimal

from sportsmodel.analysis.probability import (
    american_to_decimal_odds,
    american_to_implied_probability,
)
from sportsmodel.models.consensus_market import (
    ConsensusMarket,
)
from sportsmodel.models.moneyline_market_evaluation import (
    MoneylineMarketEvaluationPolicy,
    MoneylineModelMarketEvaluation,
    MoneylinePredictionMarketContext,
)
from sportsmodel.models.snapshot import (
    MarketSnapshot,
)


DEFAULT_MONEYLINE_MARKET_EVALUATION_POLICY = (
    MoneylineMarketEvaluationPolicy()
)


def evaluate_moneyline_model_value(
    *,
    prediction: MoneylinePredictionMarketContext,
    consensus_market: ConsensusMarket,
    snapshots: Iterable[MarketSnapshot],
    policy: MoneylineMarketEvaluationPolicy = (
        DEFAULT_MONEYLINE_MARKET_EVALUATION_POLICY
    ),
) -> MoneylineModelMarketEvaluation:
    """
    Evaluate the predicted Moneyline side against stored market prices.

    The best available stored price is used. Market probability comes
    from the cross-sportsbook no-vig consensus.
    """

    _validate_consensus_market(
        prediction=prediction,
        consensus_market=consensus_market,
    )

    matching_consensus_selections = [
        selection
        for selection
        in consensus_market.selections
        if (
            selection.selection_name
            == prediction.selection_name
            and selection.line_value is None
        )
    ]

    if len(matching_consensus_selections) != 1:
        raise LookupError(
            "The predicted selection was not represented "
            "exactly once in the consensus market."
        )

    consensus_selection = (
        matching_consensus_selections[0]
    )

    matching_snapshots = [
        snapshot
        for snapshot in snapshots
        if (
            snapshot.game_id
            == prediction.game_id
            and snapshot.market_type == "h2h"
            and snapshot.selection_name
            == prediction.selection_name
            and snapshot.line_value is None
            and snapshot.snapshot_time
            == consensus_market.snapshot_time
        )
    ]

    if not matching_snapshots:
        raise LookupError(
            "No matching stored Moneyline prices were "
            "found for the predicted selection."
        )

    best_snapshot = max(
        matching_snapshots,
        key=lambda snapshot: (
            american_to_decimal_odds(
                snapshot.price
            ),
            -snapshot.sportsbook_id,
            -snapshot.odds_market_snapshot_id,
        ),
    )

    decimal_odds = american_to_decimal_odds(
        best_snapshot.price
    )

    implied_probability = (
        american_to_implied_probability(
            best_snapshot.price
        )
    )

    market_probability = (
        consensus_selection
        .consensus_probability
    )

    model_market_edge = (
        prediction.model_probability
        - market_probability
    )

    model_price_edge = (
        prediction.model_probability
        - implied_probability
    )

    model_expected_value = (
        prediction.model_probability
        * decimal_odds
        - Decimal("1")
    )

    disqualification_reasons = (
        _build_disqualification_reasons(
            prediction=prediction,
            sportsbook_count=(
                consensus_selection
                .sportsbook_count
            ),
            model_market_edge=(
                model_market_edge
            ),
            model_expected_value=(
                model_expected_value
            ),
            policy=policy,
        )
    )

    return MoneylineModelMarketEvaluation(
        odds_market_snapshot_id=(
            best_snapshot
            .odds_market_snapshot_id
        ),
        game_id=prediction.game_id,
        sportsbook_id=(
            best_snapshot.sportsbook_id
        ),
        snapshot_time=(
            best_snapshot.snapshot_time
        ),
        selection_name=(
            prediction.selection_name
        ),
        price=best_snapshot.price,
        model_probability=(
            prediction.model_probability
        ),
        market_no_vig_probability=(
            market_probability
        ),
        sportsbook_count=(
            consensus_selection
            .sportsbook_count
        ),
        implied_probability=(
            implied_probability
        ),
        model_market_edge=(
            model_market_edge
        ),
        model_price_edge=(
            model_price_edge
        ),
        model_expected_value=(
            model_expected_value
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
        policy_version=(
            policy.policy_version
        ),
        qualifies_as_paper_candidate=(
            not disqualification_reasons
        ),
        disqualification_reasons=(
            disqualification_reasons
        ),
        starter_match_status=prediction.starter_match_status,
        starter_mismatch_reason=prediction.starter_mismatch_reason,
        current_home_starting_pitcher_mlb_id=(
            prediction.current_home_starting_pitcher_mlb_id
        ),
        current_away_starting_pitcher_mlb_id=(
            prediction.current_away_starting_pitcher_mlb_id
        ),
    )


def _validate_consensus_market(
    *,
    prediction: MoneylinePredictionMarketContext,
    consensus_market: ConsensusMarket,
) -> None:
    if (
        consensus_market.game_id
        != prediction.game_id
    ):
        raise ValueError(
            "Prediction and consensus market game IDs "
            "do not match."
        )

    if consensus_market.market_type != "h2h":
        raise ValueError(
            "Moneyline model evaluation requires an "
            "h2h consensus market."
        )

    if consensus_market.line_value is not None:
        raise ValueError(
            "Moneyline consensus markets cannot have "
            "a line value."
        )


def _build_disqualification_reasons(
    *,
    prediction: MoneylinePredictionMarketContext,
    sportsbook_count: int,
    model_market_edge: Decimal,
    model_expected_value: Decimal,
    policy: MoneylineMarketEvaluationPolicy,
) -> tuple[str, ...]:
    reasons: list[str] = []

    if prediction.starter_match_status != "matched":
        reasons.append(
            prediction.starter_mismatch_reason
            or "starter_status_unavailable"
        )

    if (
        model_expected_value
        < policy.minimum_model_expected_value
    ):
        reasons.append(
            "model_expected_value_below_minimum"
        )

    if (
        model_market_edge
        < policy.minimum_model_market_edge
    ):
        reasons.append(
            "model_market_edge_below_minimum"
        )

    if (
        sportsbook_count
        < policy.minimum_sportsbook_count
    ):
        reasons.append(
            "insufficient_sportsbook_count"
        )

    if (
        policy.require_both_starters
        and prediction.starter_coverage
        != "both"
    ):
        reasons.append(
            "incomplete_starter_coverage"
        )

    if (
        policy.require_both_starter_features
        and not (
            prediction
            .home_starter_features_available
            and prediction
            .away_starter_features_available
        )
    ):
        reasons.append(
            "incomplete_starter_features"
        )

    return tuple(reasons)
