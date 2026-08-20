from dataclasses import dataclass


@dataclass(frozen=True)
class StarterMatchResult:
    """Point-in-time comparison of prediction and current MLB starters."""

    status: str
    reason: str | None
    current_home_mlb_id: int | None
    current_away_mlb_id: int | None


def classify_starter_match(
    *,
    predicted_home_mlb_id: int | None,
    predicted_away_mlb_id: int | None,
    current_home_mlb_id: int | None,
    current_away_mlb_id: int | None,
) -> StarterMatchResult:
    """Compare canonical MLB player IDs; nulls never confirm a match."""

    unavailable_sides = []
    if predicted_home_mlb_id is None or current_home_mlb_id is None:
        unavailable_sides.append("home")
    if predicted_away_mlb_id is None or current_away_mlb_id is None:
        unavailable_sides.append("away")

    if unavailable_sides:
        suffix = (
            "both" if len(unavailable_sides) == 2 else unavailable_sides[0]
        )
        return StarterMatchResult(
            status="unavailable",
            reason=f"starter_unavailable_{suffix}",
            current_home_mlb_id=current_home_mlb_id,
            current_away_mlb_id=current_away_mlb_id,
        )

    changed_sides = []
    if predicted_home_mlb_id != current_home_mlb_id:
        changed_sides.append("home")
    if predicted_away_mlb_id != current_away_mlb_id:
        changed_sides.append("away")

    if changed_sides:
        suffix = "both" if len(changed_sides) == 2 else changed_sides[0]
        return StarterMatchResult(
            status="changed",
            reason=f"starter_changed_{suffix}",
            current_home_mlb_id=current_home_mlb_id,
            current_away_mlb_id=current_away_mlb_id,
        )

    return StarterMatchResult(
        status="matched",
        reason=None,
        current_home_mlb_id=current_home_mlb_id,
        current_away_mlb_id=current_away_mlb_id,
    )
