from datetime import datetime
from decimal import Decimal

from sportsmodel.models.moneyline_live_dashboard import (
    MoneylineLiveGame,
    MoneylineLiveSlate,
)


EXCLUSION_REASON_LABELS = {
    "model_expected_value_below_minimum": (
        "Model EV below 3% minimum"
    ),
    "model_market_edge_below_minimum": (
        "Model-market edge below 2 pp minimum"
    ),
    "insufficient_sportsbook_count": (
        "Fewer than 5 sportsbooks"
    ),
    "incomplete_starter_coverage": (
        "Incomplete probable-starter coverage"
    ),
    "incomplete_starter_features": (
        "Incomplete starter feature history"
    ),
}


def format_slate(
    slate: MoneylineLiveSlate,
) -> str:
    """Format a slate with its market snapshot context."""

    return (
        f"{slate.target_date.isoformat()} — "
        f"{slate.snapshot_role.replace('_', ' ').title()} "
        "snapshot "
        f"({format_datetime(slate.snapshot_started_at)}) — "
        f"Prediction Run {slate.prediction_run_id} / "
        f"Odds Run {slate.odds_ingestion_run_id} / "
        f"Policy {slate.policy_version}"
    )


def format_percent(
    value: Decimal | None,
) -> str:
    """
    Format a decimal probability or rate.
    """

    if value is None:
        return "Unavailable"

    return f"{float(value):.2%}"


def format_points(
    value: Decimal | None,
) -> str:
    """
    Format a probability difference in percentage points.
    """

    if value is None:
        return "Unavailable"

    points = value * Decimal("100")

    return f"{float(points):+.2f} pp"


def format_units(
    value: Decimal | None,
) -> str:
    """
    Format one-unit paper performance.
    """

    if value is None:
        return "Pending"

    return f"{value:+.4f} units"


def format_price(
    price: int,
) -> str:
    """
    Format American odds.
    """

    return f"{price:+d}"


def format_datetime(
    value: datetime,
) -> str:
    """
    Format a timestamp in UTC.
    """

    return value.strftime(
        "%b %d, %Y %I:%M %p UTC"
    )


def format_exclusion_reason(
    reason: str,
) -> str:
    """
    Convert one policy reason code into readable text.
    """

    normalized_reason = reason.strip()

    if not normalized_reason:
        return ""

    configured_label = (
        EXCLUSION_REASON_LABELS.get(
            normalized_reason
        )
    )

    if configured_label is not None:
        return configured_label

    return (
        normalized_reason
        .replace("_", " ")
        .capitalize()
    )


def format_exclusion_reasons(
    reasons: tuple[str, ...],
) -> str:
    """
    Convert policy reason codes into readable text.
    """

    formatted_reasons = tuple(
        formatted_reason
        for reason in reasons
        if (
            formatted_reason
            := format_exclusion_reason(reason)
        )
    )

    if not formatted_reasons:
        return "—"

    return "; ".join(formatted_reasons)


def get_candidate_games(
    games: tuple[MoneylineLiveGame, ...],
) -> tuple[MoneylineLiveGame, ...]:
    """
    Return only qualified paper-candidate rows.
    """

    return tuple(
        game
        for game in games
        if game.qualifies_as_paper_candidate
    )


def calculate_average_candidate_ev(
    games: tuple[MoneylineLiveGame, ...],
) -> Decimal | None:
    """
    Return average model EV for qualified candidates.
    """

    candidates = get_candidate_games(games)

    if not candidates:
        return None

    return (
        sum(
            (
                game.model_expected_value
                for game in candidates
            ),
            start=Decimal("0"),
        )
        / Decimal(len(candidates))
    )


def calculate_average_candidate_edge(
    games: tuple[MoneylineLiveGame, ...],
) -> Decimal | None:
    """
    Return average model-market edge for candidates.
    """

    candidates = get_candidate_games(games)

    if not candidates:
        return None

    return (
        sum(
            (
                game.model_market_edge
                for game in candidates
            ),
            start=Decimal("0"),
        )
        / Decimal(len(candidates))
    )


def build_candidate_table(
    games: tuple[MoneylineLiveGame, ...],
) -> list[dict[str, object]]:
    """
    Build a compact table for qualified candidates.
    """

    return [
        {
            "Game": _format_matchup(game),
            "Start": format_datetime(
                game.game_start_time
            ),
            "Model pick": (
                game.predicted_team_name
            ),
            "Model probability": format_percent(
                game.model_probability
            ),
            "Best price": format_price(
                game.price
            ),
            "Sportsbook": (
                game.sportsbook_name
            ),
            "Model EV": format_percent(
                game.model_expected_value
            ),
            "Market edge": format_points(
                game.model_market_edge
            ),
            "Starter coverage": (
                game.starter_coverage.title()
            ),
            "Status": _format_status(game),
            "Final score": _format_final_score(
                game
            ),
            "Profit": format_units(
                game.profit_units
            ),
        }
        for game in get_candidate_games(games)
    ]


def build_all_prediction_table(
    games: tuple[MoneylineLiveGame, ...],
) -> list[dict[str, object]]:
    """
    Build the complete prediction and evaluation table.
    """

    return [
        {
            "Game": _format_matchup(game),
            "Start": format_datetime(
                game.game_start_time
            ),
            "Model lean": (
                game.predicted_team_name
            ),
            "Model probability": format_percent(
                game.model_probability
            ),
            "Market no-vig": format_percent(
                game.market_no_vig_probability
            ),
            "Market edge": format_points(
                game.model_market_edge
            ),
            "Best price": format_price(
                game.price
            ),
            "Sportsbook": (
                game.sportsbook_name
            ),
            "Model EV": format_percent(
                game.model_expected_value
            ),
            "Starter coverage": (
                game.starter_coverage.title()
            ),
            "Missing values": (
                game.missing_raw_value_count
            ),
            "Paper candidate": (
                "Yes"
                if game.qualifies_as_paper_candidate
                else "No"
            ),
            "Status": _format_status(game),
            "Final score": _format_final_score(
                game
            ),
            "Profit": format_units(
                game.profit_units
            ),
            "Exclusion reasons": (
                format_exclusion_reasons(
                    game.disqualification_reasons
                )
            ),
        }
        for game in games
    ]


def _format_matchup(
    game: MoneylineLiveGame,
) -> str:
    return (
        f"{game.away_team_name} at "
        f"{game.home_team_name}"
    )


def _format_status(
    game: MoneylineLiveGame,
) -> str:
    if game.outcome is not None:
        return game.outcome.upper()

    if game.qualifies_as_paper_candidate:
        return "PENDING"

    return "NOT QUALIFIED"


def _format_final_score(
    game: MoneylineLiveGame,
) -> str:
    if (
        game.home_score is None
        or game.away_score is None
    ):
        return "Pending"

    return (
        f"{game.away_team_name} "
        f"{game.away_score}, "
        f"{game.home_team_name} "
        f"{game.home_score}"
    )
