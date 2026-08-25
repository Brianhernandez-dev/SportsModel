from __future__ import annotations

from dataclasses import dataclass

from sportsmodel.analysis.moneyline_prediction_explanation import (
    MoneylineFeatureContribution,
    MoneylinePredictionExplanation,
)


DEFAULT_TOP_REASON_COUNT = 3
MAX_TOP_REASON_COUNT = 5

# Presentation-only threshold for a readable directional label. The original
# category total is retained unchanged for analysis and advanced display.
NEUTRAL_CATEGORY_EPSILON = 1e-4

PRIMARY_CATEGORY_ORDER = (
    "starting_pitcher",
    "batting",
    "team_pitching",
    "bullpen",
)

CATEGORY_LABELS = {
    "starting_pitcher": "Starting pitcher",
    "batting": "Batting",
    "team_pitching": "Team pitching",
    "bullpen": "Bullpen",
    "other": "Other",
}


@dataclass(frozen=True)
class MoneylineCategoryLean:
    category: str
    label: str
    direction: str
    direction_team_name: str | None
    total: float


@dataclass(frozen=True)
class MoneylineFeatureReason:
    feature_name: str
    label: str
    category: str
    contribution: float
    standardized_value: float
    coefficient: float
    imputed_value: float
    is_missing_indicator: bool


@dataclass(frozen=True)
class MoneylineExplanationPresentation:
    title: str
    authoritative: bool
    authority_message: str
    selected_team_name: str
    opponent_team_name: str
    active_input_message: str
    inactive_input_message: str | None
    category_leans: tuple[MoneylineCategoryLean, ...]
    selected_team_reasons: tuple[MoneylineFeatureReason, ...]
    opponent_reasons: tuple[MoneylineFeatureReason, ...]
    advanced_feature_rows: tuple[MoneylineFeatureReason, ...]
    intercept_label: str


def present_moneyline_prediction_explanation(
    explanation: MoneylinePredictionExplanation,
    *,
    top_n: int = DEFAULT_TOP_REASON_COUNT,
) -> MoneylineExplanationPresentation:
    """Prepare analysis-service values for safe dashboard rendering."""

    if isinstance(top_n, bool) or not 1 <= top_n <= MAX_TOP_REASON_COUNT:
        raise ValueError(
            f"Top reason count must be between 1 and {MAX_TOP_REASON_COUNT}."
        )

    prediction = explanation.prediction
    title = (
        f"Why {prediction.predicted_team_name} "
        f"{float(prediction.stored_predicted_probability):.2%}?"
    )
    active_input_message = _active_input_message(
        explanation.active_missing_feature_names
    )
    inactive_input_message = _inactive_input_message(
        raw_missing_feature_names=explanation.raw_missing_feature_names,
        active_missing_feature_names=explanation.active_missing_feature_names,
        inactive_missing_feature_names=(
            explanation.inactive_missing_feature_names
        ),
    )

    if not explanation.authoritative:
        return MoneylineExplanationPresentation(
            title=title,
            authoritative=False,
            authority_message=(
                "Historical reconstruction did not match the stored prediction "
                "within the required tolerance. Contribution rankings are "
                "withheld because they may not represent the original prediction."
            ),
            selected_team_name=prediction.predicted_team_name,
            opponent_team_name=prediction.opponent_team_name,
            active_input_message=active_input_message,
            inactive_input_message=inactive_input_message,
            category_leans=(),
            selected_team_reasons=(),
            opponent_reasons=(),
            advanced_feature_rows=(),
            intercept_label="Model intercept",
        )

    categories = dict(explanation.category_totals)
    category_leans = tuple(
        _category_lean(
            category=category,
            total=categories.get(category, 0.0),
            home_team_name=prediction.home_team_name,
            away_team_name=prediction.away_team_name,
        )
        for category in PRIMARY_CATEGORY_ORDER
    )

    toward_home = prediction.predicted_team_id == prediction.home_team_id
    selected_items = _rank_directional_contributions(
        explanation.contributions,
        positive=toward_home,
    )[:top_n]
    opponent_items = _rank_directional_contributions(
        explanation.contributions,
        positive=not toward_home,
    )[:top_n]

    return MoneylineExplanationPresentation(
        title=title,
        authoritative=True,
        authority_message="Authoritative reconstruction",
        selected_team_name=prediction.predicted_team_name,
        opponent_team_name=prediction.opponent_team_name,
        active_input_message=active_input_message,
        inactive_input_message=inactive_input_message,
        category_leans=category_leans,
        selected_team_reasons=tuple(
            _feature_reason(item) for item in selected_items
        ),
        opponent_reasons=tuple(
            _feature_reason(item) for item in opponent_items
        ),
        advanced_feature_rows=tuple(
            _feature_reason(item) for item in explanation.contributions
        ),
        intercept_label="Model intercept",
    )


def humanize_moneyline_feature_name(feature_name: str) -> str:
    """Return a conservative readable label without adding causal meaning."""

    is_indicator = feature_name.startswith("missingindicator_")
    normalized = feature_name.removeprefix("missingindicator_")
    normalized = normalized.removeprefix("matchup_")
    normalized = normalized.removesuffix("_difference")

    prefixes = (
        ("starting_pitcher_", "Starting pitcher "),
        ("batting_", "Team batting "),
        ("pitching_", "Team pitching "),
        ("bullpen_bullpen_", "Bullpen "),
        ("bullpen_", "Bullpen "),
        ("schedule_", "Schedule "),
    )
    for prefix, replacement in prefixes:
        if normalized.startswith(prefix):
            normalized = replacement + normalized.removeprefix(prefix)
            break
    else:
        normalized = normalized.replace("_", " ").capitalize()

    label = normalized.replace("_", " ")
    replacements = (
        ("on base percentage", "on-base percentage"),
        ("slugging percentage", "slugging percentage"),
        ("earned run average", "ERA"),
        ("strikeouts per nine", "strikeout rate per nine"),
        ("walks per nine", "walk rate per nine"),
        ("home runs per nine", "home-run rate per nine"),
        ("home runs", "home runs"),
        ("back to back", "back-to-back"),
        ("whip", "WHIP"),
    )
    for source, replacement in replacements:
        label = label.replace(source, replacement)

    label = label[0].upper() + label[1:] if label else feature_name
    if is_indicator:
        label += " (missing-data indicator)"
    return label


def _category_lean(
    *,
    category: str,
    total: float,
    home_team_name: str,
    away_team_name: str,
) -> MoneylineCategoryLean:
    if abs(total) < NEUTRAL_CATEGORY_EPSILON:
        direction = "neutral"
        direction_team_name = None
    elif total > 0:
        direction = "home"
        direction_team_name = home_team_name
    else:
        direction = "away"
        direction_team_name = away_team_name

    return MoneylineCategoryLean(
        category=category,
        label=CATEGORY_LABELS.get(category, category.replace("_", " ").title()),
        direction=direction,
        direction_team_name=direction_team_name,
        total=total,
    )


def _rank_directional_contributions(
    contributions: tuple[MoneylineFeatureContribution, ...],
    *,
    positive: bool,
) -> tuple[MoneylineFeatureContribution, ...]:
    selected = (
        item
        for item in contributions
        if (item.contribution > 0 if positive else item.contribution < 0)
    )
    return tuple(
        sorted(
            selected,
            key=lambda item: (-abs(item.contribution), item.feature_name),
        )
    )


def _feature_reason(
    contribution: MoneylineFeatureContribution,
) -> MoneylineFeatureReason:
    return MoneylineFeatureReason(
        feature_name=contribution.feature_name,
        label=humanize_moneyline_feature_name(contribution.feature_name),
        category=contribution.category,
        contribution=contribution.contribution,
        standardized_value=contribution.standardized_value,
        coefficient=contribution.coefficient,
        imputed_value=contribution.imputed_value,
        is_missing_indicator=contribution.is_missing_indicator,
    )


def _active_input_message(active_names: tuple[str, ...]) -> str:
    count = len(active_names)
    if count == 0:
        return "Active model inputs: Complete."
    noun = "input" if count == 1 else "inputs"
    verb = "was" if count == 1 else "were"
    return (
        f"Active model inputs: {count} unavailable {noun} {verb} handled by the "
        "frozen production model's imputation pipeline."
    )


def _inactive_input_message(
    *,
    raw_missing_feature_names: tuple[str, ...],
    active_missing_feature_names: tuple[str, ...],
    inactive_missing_feature_names: tuple[str, ...],
) -> str | None:
    if (
        active_missing_feature_names
        or not raw_missing_feature_names
        or not inactive_missing_feature_names
    ):
        return None
    count = len(raw_missing_feature_names)
    noun = "field was" if count == 1 else "fields were"
    return (
        f"{count} unavailable raw {noun} inactive and did not affect this "
        "prediction."
    )
